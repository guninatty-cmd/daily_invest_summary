"""
통합 투자 데이터 수집 파이프라인 (daily_invest_summary + invest-today-digest 통합본)

실행:  python main.py                  # 전체 수집 -> 엑셀/후보목록 생성 -> 구글 드라이브 업로드
       python main.py --youtube-only   # (PC용) 유튜브 전날 영상 목록 + 자막 추출만 -> '{날짜}_유튜브_자막.xlsx'
       python main.py --no-upload      # 로컬 테스트: 업로드/상태저장 없이 파일만 생성

수집 구간(전 수집기 공통): 어제 07:00 ~ 오늘 07:00 KST  (common.get_window 참고)
노션 업로드는 제거되었다. 결과물은 엑셀 + 후보목록(txt) 이고, Claude가 이 파일을 읽어 리포트를 만든다.

출력 파일 (downloads/ -> 드라이브 '{오늘}_주식리포트_모음' 폴더)
  {오늘}_투자데이터_통합.xlsx   시트: 00_안내 / 기사_리서치 / 텔레그램 / 유튜브 / PDF목록 / PDF정독본 / 주가
  00_후보목록.txt               미국주식 관련 '후보'만 한 줄씩 압축한 목록 (Claude가 가장 먼저 읽는 파일)
  {오늘}_유튜브_자막.xlsx       (자막이 추출된 경우) 영상별 자막 전문 - 제목으로 고른 영상만 읽는다
  [채널] 파일명.pdf             텔레그램에서 받은 증권사 PDF 원본
"""
import os
import re
import sys
import asyncio
import hashlib
import datetime
import traceback
from pathlib import Path

import pandas as pd

from common import KST, get_window, parse_dt, has_time_part
from triage import (SeenState, annotate, dedupe, filter_window, load_watch_tickers, mark_link_keys, score_text)

DOWNLOAD_DIR = "downloads"
PROCESSED_HASHES_FILE = "processed_pdf_hashes.txt"
MAX_TXT_LINES = int(os.environ.get("MAX_CANDIDATE_LINES", "400"))
TRANSCRIPTS_ON_ACTIONS = os.environ.get("ACTIONS_TRANSCRIPTS", "0") == "1"


# ───────────── 유틸 ─────────────
def fmt_date(raw) -> str:
    dt = parse_dt(raw)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M") if has_time_part(raw) else dt.strftime("%Y-%m-%d")


def kind_of(source: str) -> str:
    s = source or ""
    if s.startswith("유튜브"):
        return "유튜브"
    if any(k in s for k in ("증권", "컨센서스", "KB금융 리서치", "리서치")):
        return "증권사·리서치"
    if any(k in s for k in ("ETF", "KODEX", "TIGER", "TIME", "RISE", "KoAct", "KB자산운용", "KB Think")):
        return "ETF·운용사"
    return "뉴스·미디어"


def load_hashes() -> set[str]:
    p = Path(PROCESSED_HASHES_FILE)
    return set(l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()) if p.exists() else set()


def filter_new_pdfs(paths: list[str], known: set[str]):
    new_paths, path_hash = [], {}
    for p in paths:
        if not os.path.exists(p):
            continue
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if h in known:
            os.remove(p)
        else:
            new_paths.append(p)
            path_hash[p] = h
    return new_paths, path_hash


def collect_sources() -> tuple[list[dict], dict]:
    """기사/리서치 계열 수집기를 모두 실행. 실패해도 나머지는 계속. 반환: (items, 수집기별 상태)"""
    from scrapers.hankyung_consensus import scrape_hankyung_consensus
    from scrapers.generic_link_sites import scrape_generic_sites
    from scrapers.sol_etf import scrape_sol_etf
    from scrapers.kiwoom import scrape_kiwoom
    from scrapers.kodex_time_tiger import scrape_kodex, scrape_time_etf, scrape_tiger_etf
    from scrapers.ace_etf import scrape_ace_etf
    from scrapers.myasset import scrape_myasset
    from scrapers.hanaw import scrape_hanaw
    from scrapers.miraeasset import scrape_miraeasset
    from scrapers.naver_news import scrape_naver_news

    scrapers = [
        ("한경 컨센서스", scrape_hankyung_consensus), ("직링크 11개 사이트", scrape_generic_sites),
        ("SOL ETF", scrape_sol_etf), ("키움증권", scrape_kiwoom), ("KODEX", scrape_kodex),
        ("TIME ETF", scrape_time_etf), ("TIGER ETF", scrape_tiger_etf), ("ACE ETF", scrape_ace_etf),
        ("유안타증권", scrape_myasset), ("하나증권", scrape_hanaw), ("미래에셋증권", scrape_miraeasset),
        ("네이버 뉴스(6개 언론사+속보)", scrape_naver_news),
    ]
    items, status = [], {}
    for label, fn in scrapers:
        try:
            got = fn()
            for it in got:
                it.setdefault("게시일", it.get("작성일"))
            items.extend(got)
            status[label] = f"OK {len(got)}건"
            print(f"✅ {label}: {len(got)}건")
        except Exception as e:
            status[label] = f"실패: {type(e).__name__}: {str(e)[:80]}"
            print(f"❌ {label} 실패:")
            traceback.print_exc()
    return items, status


# ───────────── 엑셀/후보목록 ─────────────
def one_line(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


def write_candidate_txt(path, window, arts, tgs, yts, pdf_rows, stocks):
    start, end = window
    L = [f"# 후보목록 | 수집구간 {start:%m/%d %H:%M} ~ {end:%m/%d %H:%M} KST",
         "# 형식: ID|분류힌트|출처|제목  (전체 원문/링크는 엑셀의 같은 ID 행). 후보=Y 만 수록, 점수 높은 순.",
         "# 읽기 원칙: 이 파일만 먼저 읽고, 본문이 꼭 필요한 항목만 ID로 엑셀에서 추가 조회할 것.", ""]
    used = 0

    def section(title, lines):
        nonlocal used
        L.append(f"## {title} ({len(lines)}건)")
        room = max(MAX_TXT_LINES - used, 0)
        L.extend(lines[:room])
        if len(lines) > room:
            L.append(f"(… {len(lines) - room}건은 엑셀 참조)")
        used += min(len(lines), room)
        L.append("")

    section("기사·리서치", [f"{a['ID']}|{a['분류힌트']}|{a['출처']}|{one_line(a['제목'], 90)}" for a in arts if a["후보"] == "Y"])
    section("텔레그램", [f"{t['ID']}|{t['분류힌트']}|{t['채널']}|{t['시각'][5:]}|{one_line(t['내용'], 260)}" for t in tgs if t["후보"] == "Y"])
    section("유튜브(제목 후보. '분석:완료' 영상은 엑셀 '유튜브' 시트의 영상분석 열에 Gemini 요약이 있음)", [f"{y['ID']}|{y['분류힌트']}|{y['채널']}|{one_line(y['제목'], 90)}|분석:{y.get('자막상태', '대기')}" for y in yts if y["후보"] == "Y"])
    section("PDF (정독대상=Y 만 'PDF정독본' 시트에 본문 있음)", [f"{p['ID']}|{p['유형']}|{p['채널']}|{p['파일명']}|{p['쪽수']}쪽|정독:{p['정독대상']}" for p in pdf_rows])
    if stocks:
        L.append("## 관심종목 전일 등락")
        L.append(", ".join(f"{s['ticker']} {s['change_pct']:+.1f}%{'⚠' if s.get('alert') else ''}" for s in stocks if s.get("change_pct") is not None))
    Path(path).write_text("\n".join(L), encoding="utf-8")


def write_workbook(path, window, log_lines, arts, tgs, yts, pdf_rows, pdf_body, stocks):
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        info = [["수집 구간(KST)", f"{window[0]:%Y-%m-%d %H:%M} ~ {window[1]:%Y-%m-%d %H:%M}"],
                ["읽는 법", "후보=Y 이고 점수 높은 행만 읽는다. 후보=N 은 제외사유 확인용(읽지 않는다)."],
                ["분류힌트", "규칙 기반 힌트일 뿐이며 최종 분류는 리포트 작성 시 확정"], ["", ""]] + [[k, v] for k, v in log_lines]
        pd.DataFrame(info, columns=["항목", "내용"]).to_excel(w, sheet_name="00_안내", index=False)
        a_cols = ["ID", "후보", "점수", "분류힌트", "구분", "출처", "제목", "게시일", "링크", "제외사유"]
        pd.DataFrame(arts, columns=a_cols).to_excel(w, sheet_name="기사_리서치", index=False)
        t_cols = ["ID", "후보", "점수", "분류힌트", "시각", "채널", "내용", "제외사유"]
        pd.DataFrame(tgs, columns=t_cols).to_excel(w, sheet_name="텔레그램", index=False)
        y_cols = ["ID", "후보", "점수", "분류힌트", "채널", "제목", "게시일", "링크", "길이(분)", "자막상태", "영상분석", "제외사유"]
        pd.DataFrame(yts, columns=y_cols).to_excel(w, sheet_name="유튜브", index=False)
        p_cols = ["ID", "정독대상", "유형", "채널", "파일명", "쪽수", "점수", "분류힌트", "첫쪽미리보기", "제외사유"]
        pd.DataFrame(pdf_rows, columns=p_cols).to_excel(w, sheet_name="PDF목록", index=False)
        pd.DataFrame(pdf_body, columns=["파일명", "유형", "분할", "본문"]).to_excel(w, sheet_name="PDF정독본", index=False)
        if stocks:
            pd.DataFrame([{"티커": s["ticker"], "날짜": s["date"], "종가($)": s["close"], "전일종가($)": s["prev_close"],
                           "등락률(%)": s["change_pct"], "±3%이상": "⚠" if s["alert"] else ""} for s in stocks]
                         ).to_excel(w, sheet_name="주가", index=False)


# ───────────── 유튜브 전용 모드 (PC) ─────────────
def run_youtube_only(upload: bool):
    from scrapers.youtube import scrape_youtube
    from youtube_transcripts import extract_transcripts, write_transcript_excel
    window = get_window()
    date_label = f"{window[1]:%Y-%m-%d}"
    print(f"📺 유튜브 전용 모드 | 구간 {window[0]:%m/%d %H:%M} ~ {window[1]:%m/%d %H:%M} KST")
    videos = extract_transcripts(scrape_youtube())
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    out = os.path.join(DOWNLOAD_DIR, f"{date_label}_유튜브_자막.xlsx")
    write_transcript_excel(videos, out)
    done = sum(v.get("자막상태") == "완료" for v in videos)
    print(f"✅ {out} | 영상 {len(videos)}건 중 자막 완료 {done}건")
    if upload and os.environ.get("GAS_WEBHOOK_URL"):
        from drive_upload import upload_to_drive_via_gas
        if not upload_to_drive_via_gas(out, f"{date_label}_주식리포트_모음"):
            sys.exit(1)


# ───────────── 메인 ─────────────
def main():
    args = set(sys.argv[1:])
    upload = "--no-upload" not in args
    if "--youtube-only" in args:
        return run_youtube_only(upload)

    from scrapers.youtube import scrape_youtube
    from stock_prices import collect_stock_prices
    from telegram_digest import run_telegram_digest
    from pdf_triage import triage_pdfs

    window = get_window()
    start, end = window
    date_label = f"{end:%Y-%m-%d}"
    folder_name = f"{date_label}_주식리포트_모음"
    last_run = Path("state/last_run.txt")
    if upload and os.environ.get("FORCE_RUN") != "1" and last_run.exists() and last_run.read_text().strip() == date_label:
        print(f"⏭️ {date_label} 구간은 이미 성공적으로 실행됨 - 중복 실행(지연된 스케줄 등) 건너뜀. 다시 하려면 FORCE_RUN=1")
        return
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"📅 수집 구간(KST): {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} | 업로드 폴더: {folder_name}\n")
    tickers = load_watch_tickers()
    log = [("실행 시각(KST)", f"{datetime.datetime.now(KST):%Y-%m-%d %H:%M:%S}")]

    # 1) 기사·리서치 (네이버 포함, 단일 수집기)
    items, status = collect_sources()
    log += [(f"수집기: {k}", v) for k, v in status.items()]
    for it in items:
        it["게시일"] = it.get("게시일") or it.get("작성일")
    mark_link_keys(items)
    n0 = len(items)
    items, dropped_old = filter_window(items)
    items = dedupe(items)
    seen = SeenState()
    items = seen.filter_new(items)
    log.append(("기사·리서치 정리", f"수집 {n0} → 구간밖 {dropped_old}건 제거 → 중복/이전 실행분 제거 후 {len(items)}건"))
    annotate(items, ("제목",), tickers)
    items.sort(key=lambda i: (i["후보"] != "Y", -i["점수"]))
    arts = []
    for n, it in enumerate(items, 1):
        arts.append({"ID": f"A{n}", **{k: it.get(k, "") for k in ("후보", "점수", "분류힌트", "출처", "제목", "링크", "제외사유")},
                     "구분": kind_of(it.get("출처", "")), "게시일": fmt_date(it.get("게시일")), "_lk": it.get("_lk", "")})

    # 2) 유튜브 (제목/링크 + 선택적 자막)
    try:
        videos = scrape_youtube()
        log.append(("유튜브 목록", f"OK {len(videos)}건"))
    except Exception as e:
        videos = []
        log.append(("유튜브 목록", f"실패: {e}"))
        traceback.print_exc()
    yt_new = [v for v in videos if not seen.is_seen(v)]
    transcript_path = None
    if TRANSCRIPTS_ON_ACTIONS and yt_new:
        from youtube_transcripts import extract_transcripts, write_transcript_excel
        yt_new = extract_transcripts(yt_new)
        transcript_path = os.path.join(DOWNLOAD_DIR, f"{date_label}_유튜브_자막.xlsx")
        write_transcript_excel(yt_new, transcript_path)
    annotate(yt_new, ("제목",), tickers)
    try:
        from youtube_gemini import analyze
        log.append(("유튜브 Gemini 분석", analyze(yt_new)))
    except Exception as e:
        log.append(("유튜브 Gemini 분석", f"실패: {type(e).__name__}: {str(e)[:80]}"))
        traceback.print_exc()
    yts = []
    for n, v in enumerate(sorted(yt_new, key=lambda i: -i["점수"]), 1):
        yts.append({"ID": f"Y{n}", **{k: v.get(k, "") for k in ("후보", "점수", "분류힌트", "채널", "제목", "링크", "제외사유")},
                    "게시일": fmt_date(v.get("게시일")), "자막상태": v.get("분석상태") or v.get("자막상태", "자막대기"),
                    "영상분석": v.get("분석", ""), "길이(분)": round(v["길이초"] / 60) if v.get("길이초") else ""})

    # 3) 텔레그램 + PDF
    tgs, pdf_rows, pdf_body, pdf_paths, pdf_hash = [], [], [], [], {}
    known = load_hashes()
    try:
        msgs, pdf_raw = asyncio.run(run_telegram_digest(DOWNLOAD_DIR))
        pdf_paths, pdf_hash = filter_new_pdfs(pdf_raw, known)
        log.append(("텔레그램", f"OK 메시지 {len(msgs)}건 / 새 PDF {len(pdf_paths)}건 (이미 처리한 PDF {len(pdf_raw) - len(pdf_paths)}건 제외)"))
    except Exception as e:
        msgs = []
        log.append(("텔레그램", f"실패: {type(e).__name__}: {str(e)[:80]}"))
        traceback.print_exc()
    for m in msgs:
        score, reason, hint = score_text(m["내용"], tickers)
        if reason is None and len(m["내용"].strip()) < 30:
            reason = "너무 짧은 메시지"
        m.update({"점수": score, "분류힌트": hint, "후보": "N" if reason else "Y", "제외사유": reason or ""})
    msgs.sort(key=lambda m: (m["후보"] != "Y", -m["점수"]))
    for n, m in enumerate(msgs, 1):
        tgs.append({"ID": f"T{n}", **m})
    if pdf_paths:
        pdf_rows, pdf_body = triage_pdfs(pdf_paths)
        for n, r in enumerate(pdf_rows, 1):
            r["ID"] = f"P{n}"
        log.append(("PDF 선별", f"전체 {len(pdf_rows)}건 중 정독대상 {sum(r['정독대상'] == 'Y' for r in pdf_rows)}건 (본문 추출)"))

    # 4) 주가
    try:
        stocks = collect_stock_prices()
        log.append(("주가", f"OK {len(stocks)}종목"))
    except Exception as e:
        stocks = []
        log.append(("주가", f"실패: {e}"))

    # 5) 파일 생성
    excel_path = os.path.join(DOWNLOAD_DIR, f"{date_label}_투자데이터_통합.xlsx")
    txt_path = os.path.join(DOWNLOAD_DIR, "00_후보목록.txt")
    write_workbook(excel_path, window, log, arts, tgs, yts, pdf_rows, pdf_body, stocks)
    write_candidate_txt(txt_path, window, arts, tgs, yts, pdf_rows, stocks)
    cand = lambda rows: sum(r.get("후보") == "Y" for r in rows)
    print(f"\n📊 기사 {len(arts)}(후보 {cand(arts)}) | 텔레그램 {len(tgs)}(후보 {cand(tgs)}) | "
          f"유튜브 {len(yts)} | PDF {len(pdf_rows)}")

    if not (arts or tgs or yts or pdf_rows):
        print("❌ 수집된 데이터가 전혀 없습니다 (모든 수집기 실패 가능).")
        sys.exit(1)
    if not upload:
        return

    # 6) 드라이브 업로드 - 하나라도 실패하면 실행 자체를 '실패'로 표시한다 (조용한 성공 방지)
    from drive_upload import upload_to_drive_via_gas
    targets = [txt_path, excel_path] + ([transcript_path] if transcript_path else []) + pdf_paths
    failed, ok_pdf_hashes = [], set()
    for p in targets:
        if upload_to_drive_via_gas(p, folder_name):
            if p in pdf_hash:
                ok_pdf_hashes.add(pdf_hash[p])
        else:
            failed.append(os.path.basename(p))

    core_ok = not any(n in failed for n in (os.path.basename(txt_path), os.path.basename(excel_path)))
    if core_ok:   # 핵심 파일이 올라간 경우에만 '이미 수집함' 상태를 저장 (실패 시 다음 실행이 재시도)
        seen.add_and_save([{"링크": a["링크"], "제목": a["제목"], "_lk": a["_lk"]} for a in arts] +
                          [{"링크": y["링크"], "제목": y["제목"]} for y in yts])
    Path(PROCESSED_HASHES_FILE).write_text("\n".join(sorted(known | ok_pdf_hashes)), encoding="utf-8")
    if core_ok:
        last_run.parent.mkdir(parents=True, exist_ok=True)
        last_run.write_text(date_label)
    if failed:
        print(f"\n❌ 업로드 실패 {len(failed)}건: {failed}")
        sys.exit(1)
    print(f"\n✅ 완료: {folder_name}")


if __name__ == "__main__":
    main()
