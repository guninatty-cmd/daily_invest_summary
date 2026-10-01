"""
1차 선별(triage) - 토큰을 쓰지 않는 '규칙 기반' 필터.

목적: Claude가 리포트를 만들 때 '읽어야 할 후보'만 읽도록, 코드가 미리 (1) 구간 밖/중복 항목을 제거하고
(2) 미국주식 관련도 점수와 분류 힌트를 붙이고 (3) 후보가 아닌 항목에 제외 사유를 표시한다.
유료 AI API는 쓰지 않는다. (분류 힌트는 '힌트'일 뿐, 최종 분류/요약은 Claude가 후보만 읽고 한다)
"""
import json
import re
from datetime import datetime
from pathlib import Path

from common import KST, get_window, parse_dt, has_time_part, normalize_link, normalize_title

SEEN_FILE = Path("state/seen_items.json")
SEEN_KEEP_DAYS = 14

# ── 미국 주식 관련 키워드 (하나라도 걸리면 후보, 많이 걸릴수록 높은 점수) ──
US_KEYWORDS = [
    "미국", "미 증시", "뉴욕증시", "월가", "월스트리트", "연준", "Fed", "FOMC", "파월", "트럼프", "관세",
    "나스닥", "S&P", "다우", "러셀", "VIX", "빅테크", "매그니피센트", "엔비디아", "테슬라", "애플", "마이크로소프",
    "구글", "알파벳", "아마존", "메타", "브로드컴", "팔란티어", "AMD", "인텔", "마이크론", "TSMC", "넷플릭스",
    "미 국채", "미국채", "국채", "달러", "CPI", "PCE", "고용", "비농업", "실업", "셧다운", "재무부",
    "어닝", "실적", "가이던스", "해외주식", "미국주식", "미국 ETF", "ETF", "옵션", "반도체", "AI", "인공지능",
    "데이터센터", "원전", "SMR", "방산", "로봇", "양자", "S&P500", "나스닥100", "배당",
]
# 한 번이라도 걸리면 '국내 전용/비주식' 후보 감점 (미국 키워드가 하나도 없을 때만 제외)
DOMESTIC_ONLY = ["코스피", "코스닥", "국내증시", "공모주", "청약", "아파트", "부동산", "전세", "분양", "원자재 선물"]
CRYPTO = ["비트코인", "이더리움", "가상자산", "암호화폐", "코인", "리플", "도지코인", "스테이블코인"]
NOISE_TITLE = [r"^\s*\[?(포토|사진|부고|인사|오늘의 운세|게시판|이벤트|채용|모집)", r"세미나|웨비나|수강|등록 안내|공지"]

# ── 분류 힌트 (최종 분류는 Claude가 SKILL의 '1건=1섹션' 규칙으로 확정) ──
HINT_RULES = [
    ("실적", ["실적", "어닝", "EPS", "가이던스", "분기 매출", "컨센서스 상회", "컨센서스 하회", "어닝서프라이즈", "어닝쇼크"]),
    ("시장", ["마감", "장중", "뉴욕증시", "지수", "나스닥", "S&P", "다우", "VIX", "수급", "랠리", "급락", "급등", "시황"]),
    ("거시·정책", ["연준", "Fed", "FOMC", "금리", "CPI", "PCE", "고용", "물가", "GDP", "관세", "무역", "재정", "셧다운", "국채", "달러", "환율", "유가"]),
    ("산업·테마", ["반도체", "AI", "인공지능", "데이터센터", "전력", "원전", "SMR", "방산", "로봇", "양자", "바이오", "헬스케어", "클라우드", "섹터", "업종", "테마", "ETF"]),
]


def load_watch_tickers(path: str = "watchlist.txt") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [l.strip().upper() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _kw_hits(text: str, kws: list[str]) -> list[str]:
    low = text.lower()
    hits = []
    for k in kws:
        if k.isascii():   # 영문 키워드는 단어 경계로 (예: 'AI'가 'said'에 걸리지 않게)
            if re.search(rf"(?<![a-z]){re.escape(k.lower())}(?![a-z])", low):
                hits.append(k)
        elif k in text:
            hits.append(k)
    return hits


def score_text(text: str, tickers: list[str]) -> tuple[int, str | None, str]:
    """(점수, 제외사유 또는 None, 분류힌트)"""
    us = _kw_hits(text, US_KEYWORDS)
    tk = [t for t in tickers if re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text)]
    score = min(len(us), 5) + 2 * min(len(tk), 2)
    reason = None
    if any(re.search(p, text) for p in NOISE_TITLE):
        reason = "공지/광고성"
    elif _kw_hits(text, CRYPTO) and not (set(us) - {"달러"}) and not tk:
        reason = "암호화폐 단독"
    elif _kw_hits(text, DOMESTIC_ONLY) and score == 0:
        reason = "국내/비주식"
    elif score == 0:
        reason = "미국 관련 키워드 없음"
    hint = ""
    for name, kws in HINT_RULES:
        if _kw_hits(text, kws):
            hint = name
            break
    if not hint and score:
        hint = "기업"
    return score, reason, hint


# ───────────── 구간 필터 / 중복 제거 / 이전 실행 대비 신규 ─────────────
def in_window(raw_date) -> bool:
    """날짜 불명 -> 통과(신규 여부는 seen 상태가 판단). 날짜만 있으면 구간 시작일/종료일에 해당하면 통과."""
    start, end = get_window()
    dt = parse_dt(raw_date)
    if dt is None:
        return True
    if has_time_part(raw_date):
        return start <= dt < end
    return dt.date() in (start.date(), end.date())


def filter_window(items: list[dict]) -> tuple[list[dict], int]:
    kept, dropped = [], 0
    for it in items:
        raw = it.get("게시일") or it.get("작성일")
        if in_window(raw):
            kept.append(it)
        else:
            dropped += 1
    return kept, dropped


def mark_link_keys(items: list[dict]) -> None:
    """링크 중복 판단용 키(_lk)를 붙인다. 키움/하나/미래에셋 일부처럼 '여러 글이 같은 목록 링크'를 쓰는 경우
    (같은 링크에 서로 다른 제목이 3건 이상)에는 링크가 글을 식별하지 못하므로 키를 비워 제목으로만 중복을 판단한다."""
    titles_by_link: dict[str, set] = {}
    for it in items:
        nl = normalize_link(it.get("링크"))
        if nl:
            titles_by_link.setdefault(nl, set()).add(normalize_title(it.get("제목")))
    for it in items:
        nl = normalize_link(it.get("링크"))
        it["_lk"] = "" if (nl and len(titles_by_link[nl]) >= 3) else nl


def _lk(it: dict) -> str:
    return it["_lk"] if "_lk" in it else normalize_link(it.get("링크"))


def dedupe(items: list[dict]) -> list[dict]:
    """같은 실행 안에서 링크 또는 정규화 제목이 같으면 첫 항목만 유지 (네이버 지면/속보/타 사이트 중복 포함)."""
    seen_l, seen_t, kept = set(), set(), []
    for it in items:
        nl, nt = _lk(it), normalize_title(it.get("제목"))
        if (nl and nl in seen_l) or (nt and nt in seen_t):
            continue
        if nl:
            seen_l.add(nl)
        if nt:
            seen_t.add(nt)
        kept.append(it)
    return kept


class SeenState:
    """이전 실행에서 이미 수집한 링크/제목 (날짜 표시 없는 사이트의 '어제 대비 신규' 판단용, 노션 대체)."""

    def __init__(self):
        self.data = {"links": {}, "titles": {}}
        if SEEN_FILE.exists():
            try:
                self.data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

    def is_seen(self, it: dict) -> bool:
        nl, nt = _lk(it), normalize_title(it.get("제목"))
        return bool(nl and nl in self.data["links"]) or bool(nt and nt in self.data["titles"])

    def filter_new(self, items: list[dict]) -> list[dict]:
        return [it for it in items if not self.is_seen(it)]

    def add_and_save(self, items: list[dict]):
        today = datetime.now(KST).strftime("%Y-%m-%d")
        for it in items:
            nl, nt = _lk(it), normalize_title(it.get("제목"))
            if nl:
                self.data["links"][nl] = today
            if nt:
                self.data["titles"][nt] = today
        cutoff = (datetime.now(KST).date().toordinal() - SEEN_KEEP_DAYS)
        for key in ("links", "titles"):
            self.data[key] = {k: v for k, v in self.data[key].items()
                              if datetime.strptime(v, "%Y-%m-%d").date().toordinal() >= cutoff}
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


def annotate(items: list[dict], text_keys: tuple[str, ...], tickers: list[str]) -> list[dict]:
    for it in items:
        text = " ".join(str(it.get(k) or "") for k in text_keys)
        score, reason, hint = score_text(text, tickers)
        it["점수"], it["분류힌트"] = score, hint
        it["후보"] = "Y" if reason is None else "N"
        it["제외사유"] = reason or ""
    return items
