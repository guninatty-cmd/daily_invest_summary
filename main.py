"""
통합 투자 데이터 자동화 파이프라인 v2
1) 네이버 뉴스(6대 경제지 당일 지면기사 + 글로벌경제 속보 전날치) 수집
2) 텔레그램 대화(전날 24시간) + PDF(전날 하루치) 수집 — 크로스런 중복 방지
3) 유튜브 채널 전날 영상 자막 수집 (신규)
4) 관심 종목 전일 등락폭 수집 (신규)
5) 뉴스+텔레그램을 엑셀로 병합
6) 모든 파일을 구글 드라이브 날짜 폴더에 업로드

매일 KST 11:00 (UTC 02:00) GitHub Actions + cron-job.org 트리거
"""
import os
import re
import json
import asyncio
import datetime
import hashlib
from datetime import timezone, timedelta
from pathlib import Path

import pandas as pd

from naver_news import scrape_naver_news
from telegram_digest import run_telegram_digest
from drive_upload import upload_to_drive_via_gas
from youtube_transcript import collect_youtube_transcripts
from stock_prices import collect_stock_prices

KST = timezone(timedelta(hours=9))
DOWNLOAD_DIR = "downloads"
PROCESSED_HASHES_FILE = "processed_pdf_hashes.txt"


# ──────────────────────────────────────────────
# PDF 크로스런 중복 방지
# ──────────────────────────────────────────────

def load_processed_hashes() -> set[str]:
    """이전 실행에서 처리된 PDF 해시 목록 로드"""
    p = Path(PROCESSED_HASHES_FILE)
    if not p.exists():
        return set()
    return set(line.strip() for line in p.read_text(encoding='utf-8').splitlines() if line.strip())


def save_processed_hashes(hashes: set[str]):
    """처리된 PDF 해시 목록 저장 (GitHub Actions가 커밋)"""
    Path(PROCESSED_HASHES_FILE).write_text('\n'.join(sorted(hashes)), encoding='utf-8')


def filter_new_pdfs(pdf_paths: list[str], known_hashes: set[str]) -> tuple[list[str], set[str]]:
    """이미 처리된 PDF 제거. 반환: (새 파일 목록, 새 해시 set)"""
    new_paths = []
    new_hashes = set()
    for path in pdf_paths:
        with open(path, 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest()
        if h in known_hashes:
            print(f"  ⏭️  크로스런 중복 PDF 건너뜀: {os.path.basename(path)}")
            os.remove(path)
        else:
            new_paths.append(path)
            new_hashes.add(h)
    return new_paths, new_hashes


# ──────────────────────────────────────────────
# 데이터 병합 유틸
# ──────────────────────────────────────────────

def build_unified_dataframe(df_news: pd.DataFrame, df_telegram: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df_news.iterrows():
        rows.append({
            "구분": "뉴스",
            "날짜": r.get("기사 등록일", ""),
            "시간": "",
            "출처/채널": r.get("출처", ""),
            "제목/내용": r.get("기사 제목", ""),
            "원문 링크": r.get("원문 링크", ""),
        })
    for _, r in df_telegram.iterrows():
        sent_at = str(r.get("발송 시간", ""))
        date_part, _, time_part = sent_at.partition(" ")
        rows.append({
            "구분": "텔레그램",
            "날짜": date_part,
            "시간": time_part,
            "출처/채널": r.get("채널명", ""),
            "제목/내용": r.get("내용", ""),
            "원문 링크": "",
        })
    if not rows:
        return pd.DataFrame(columns=["연번", "구분", "날짜", "시간", "출처/채널", "제목/내용", "원문 링크"])
    df = pd.DataFrame(rows)
    df = df.sort_values(by=["날짜", "시간"], kind="stable").reset_index(drop=True)
    df.insert(0, "연번", range(1, len(df) + 1))
    return df


def write_ai_summary_text(filepath: str, df_news: pd.DataFrame, df_telegram: pd.DataFrame,
                           yt_transcripts: list[dict], stock_prices: list[dict]):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("너는 주식 투자 전문 애널리스트야. 아래 제공되는 텍스트는 지난 24시간 동안 수집된 "
                "경제 뉴스, 투자 채널 대화 내역, 유튜브 채널 자막, 관심 종목 등락폭 데이터야.\n")
        f.write("국내 주식, 국내 매크로, 원자재 선물 관련 내용은 제외하고, "
                "'미국 주식 투자에 직접 관련된 핵심 정보'만 요약해줘.\n\n")

        f.write("--- [네이버 뉴스] ---\n\n")
        for _, row in df_news.iterrows():
            f.write(f"[{row['출처']} | {row['기사 등록일']}] {row['기사 제목']}\n{row['원문 링크']}\n\n")

        f.write("\n--- [텔레그램 대화] ---\n\n")
        for _, row in df_telegram.iterrows():
            f.write(f"[{row['채널명']} | {row['발송 시간']}]\n{row['내용']}\n")
            f.write("-" * 40 + "\n\n")

        if yt_transcripts:
            f.write("\n--- [유튜브 채널 자막] ---\n\n")
            for yt in yt_transcripts:
                f.write(f"[제목] {yt['title']}\n[URL] {yt['url']}\n\n{yt['text']}\n\n")
                f.write("=" * 50 + "\n\n")

        if stock_prices:
            f.write("\n--- [관심 종목 전일 등락폭] ---\n\n")
            for s in stock_prices:
                alert = " ⚠️ 3%이상 등락" if s.get('alert') else ""
                f.write(f"{s['ticker']}: ${s['close']} ({s['change_pct']:+.1f}%){alert}\n")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    now_kst = datetime.datetime.now(KST)
    today_str = now_kst.strftime("%Y-%m-%d")
    yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_param = (now_kst - timedelta(days=1)).strftime("%Y%m%d")
    folder_name = f"{today_str}_주식리포트_모음"

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print(f"📅 실행 기준 시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   - 대상 날짜: {yesterday_str} | 업로드 폴더: {folder_name}\n")

    # ── 1. 네이버 뉴스 ──
    print("=== [1/4] 네이버 뉴스 수집 ===")
    df_news = scrape_naver_news(today_str=today_str, yesterday_str=yesterday_str, yesterday_param=yesterday_param)
    print(f"   ✔️ 뉴스 {len(df_news)}건\n")

    # ── 2. 텔레그램 (크로스런 중복 방지 포함) ──
    print("=== [2/4] 텔레그램 수집 ===")
    known_hashes = load_processed_hashes()
    print(f"   기존 처리된 PDF 해시: {len(known_hashes)}건")
    df_telegram, pdf_paths_raw = asyncio.run(run_telegram_digest(download_dir=DOWNLOAD_DIR))
    pdf_paths, new_hashes = filter_new_pdfs(pdf_paths_raw, known_hashes)
    print(f"   ✔️ 메시지 {len(df_telegram)}건 / 새 PDF {len(pdf_paths)}건\n")

    # ── 3. 유튜브 자막 ──
    print("=== [3/4] 유튜브 자막 수집 ===")
    yt_transcripts = collect_youtube_transcripts(download_dir=DOWNLOAD_DIR)

    # ── 4. 관심 종목 등락폭 ──
    print("=== [4/4] 관심 종목 등락폭 수집 ===")
    stock_prices = collect_stock_prices()

    # ── 엑셀 병합 ──
    print("=== 파일 생성 ===")
    unified_df = build_unified_dataframe(df_news, df_telegram)
    excel_path = os.path.join(DOWNLOAD_DIR, f"{today_str}_투자데이터_통합.xlsx")
    unified_df.to_excel(excel_path, index=False, engine='openpyxl')
    print(f"   엑셀: {excel_path} ({len(unified_df)}행)")

    # ── AI 요약용 텍스트 ──
    summary_path = os.path.join(DOWNLOAD_DIR, "00_AI_요약용_복붙텍스트.txt")
    write_ai_summary_text(summary_path, df_news, df_telegram, yt_transcripts, stock_prices)
    print(f"   요약 텍스트: {summary_path}")

    # ── 유튜브 자막 파일 저장 ──
    yt_paths = []
    for yt in yt_transcripts:
        safe_title = re.sub(r'[\\/:*?"<>|]', '', yt['title'])[:40].strip()
        fname = f"[YT] {yesterday_param}_{safe_title}.txt"
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        Path(fpath).write_text(
            f"제목: {yt['title']}\nURL: {yt['url']}\n{'─'*60}\n\n{yt['text']}\n",
            encoding='utf-8'
        )
        yt_paths.append(fpath)
    if yt_paths:
        print(f"   유튜브 자막 파일: {len(yt_paths)}개")

    # ── 등락폭 JSON 저장 ──
    stock_path = None
    if stock_prices:
        stock_path = os.path.join(DOWNLOAD_DIR, f"{yesterday_param}_등락폭.json")
        Path(stock_path).write_text(json.dumps(stock_prices, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"   등락폭 JSON: {stock_path}")

    # ── 구글 드라이브 업로드 ──
    print(f"\n=== 구글 드라이브 업로드 → {folder_name} ===")
    upload_targets = [summary_path, excel_path] + pdf_paths + yt_paths
    if stock_path:
        upload_targets.append(stock_path)

    for path in upload_targets:
        upload_to_drive_via_gas(path, folder_name)

    # ── PDF 해시 저장 (GitHub Actions가 커밋) ──
    updated_hashes = known_hashes | new_hashes
    save_processed_hashes(updated_hashes)
    print(f"\n처리된 PDF 해시 저장: 총 {len(updated_hashes)}건")
    print(f"\n✅ 파이프라인 완료: {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
