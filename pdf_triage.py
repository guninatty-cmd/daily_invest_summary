"""
증권사 PDF 리포트 선별 + 본문 추출 (토큰 절약용).

흐름: 모든 PDF의 '첫 페이지 일부'만 텍스트로 뽑아 점수화 -> 상위 N건(기본 10)만 본문(최대 8쪽)을 추출.
Claude는 '상위 N건 본문 시트'만 읽고, 나머지는 파일명/요약 한 줄 목록만 본다.
데일리 시황 PDF(예: SAVE 브리핑, 파일명이 날짜 형태)는 점수와 무관하게 항상 본문을 추출한다.
"""
import os
import re

from triage import score_text, load_watch_tickers

TOP_N = int(os.environ.get("PDF_TOP_N", "10"))
SNIPPET_CHARS = 1200
BODY_PAGES = 8
CELL_LIMIT = 30000
MARKET_WRAP_RE = re.compile(r"^\[[^\]]*\]\s*\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일")


def _extract_text(path: str, max_pages: int) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        total = len(reader.pages)
        parts = []
        for page in reader.pages[:max_pages]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        text = re.sub(r"[ \t]+", " ", "\n".join(parts))
        text = re.sub(r"\n{2,}", "\n", text).strip()
        return text, total
    except Exception as e:
        return f"(텍스트 추출 실패: {e})", 0


def triage_pdfs(pdf_paths: list[str]) -> tuple[list[dict], list[dict]]:
    """반환: (목록행 list, 본문행 list). 목록행은 전체 PDF, 본문행은 정독 대상만."""
    tickers = load_watch_tickers()
    rows = []
    for p in pdf_paths:
        base = os.path.basename(p)
        m = re.match(r"^\[(.+?)\]\s*(.*)$", base)
        channel, fname = (m.group(1), m.group(2)) if m else ("", base)
        snippet, pages = _extract_text(p, 1)
        score, reason, hint = score_text(f"{fname} {snippet}", tickers)
        is_wrap = bool(MARKET_WRAP_RE.match(base))
        rows.append({"파일명": base, "채널": channel, "쪽수": pages, "점수": score, "분류힌트": hint,
                     "유형": "일일시황PDF" if is_wrap else "증권사리포트", "제외사유": reason or "",
                     "첫쪽미리보기": snippet[:SNIPPET_CHARS], "_path": p})

    reports = sorted([r for r in rows if r["유형"] == "증권사리포트" and not r["제외사유"]],
                     key=lambda r: (-r["점수"], -r["쪽수"]))
    top = {r["파일명"] for r in reports[:TOP_N]}
    body_rows = []
    for rank, r in enumerate(sorted(rows, key=lambda r: (r["유형"] != "일일시황PDF", -r["점수"])), 1):
        r["정독대상"] = "Y" if (r["유형"] == "일일시황PDF" or r["파일명"] in top) else "N"
    for r in rows:
        if r["정독대상"] != "Y":
            continue
        pages = 20 if r["유형"] == "일일시황PDF" else BODY_PAGES
        text, _ = _extract_text(r["_path"], pages)
        for i in range(0, max(len(text), 1), CELL_LIMIT):
            body_rows.append({"파일명": r["파일명"], "유형": r["유형"], "분할": i // CELL_LIMIT + 1,
                              "본문": text[i:i + CELL_LIMIT]})
    for r in rows:
        r.pop("_path", None)
    rows.sort(key=lambda r: (r["정독대상"] != "Y", r["유형"] != "일일시황PDF", -r["점수"]))
    return rows, body_rows
