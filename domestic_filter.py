"""
국내 개별 종목 리포트 제외 (수집 단계에서 걸러 다운로드·업로드 시간을 줄인다).

사용자는 미국 주식·미국 상장 ETF만 다룬다. 국내 상장사(코스피·코스닥) 단독 리포트는 대상이 아니다.
판단은 2단계:
  1) 다운로드 전: 파일명·메시지 글에 국내 종목 단서(6자리 종목코드, .KS/.KQ, 기업설명회/IR 개최 공시 등)
  2) 다운로드 후: 첫 쪽 텍스트에 국내 종목 단서((005300), 005300 KS, KOSPI/KOSDAQ 종목 표기)
미국 종목 단서(예: 'NVDA US', 'TSLA.O' 등)가 함께 있으면 국내 종목으로 보지 않는다 (국내 증권사의 미국주식 리포트 보호).
"""
import re

SKIPPED: list[str] = []   # 이번 실행에서 제외한 파일명 (main.py가 건수를 로그에 남김)

_CODE_PAREN = re.compile(r"\(\s*\d{6}\s*(?:[.\s]*(?:KS|KQ|KRX|KOSPI|KOSDAQ))?\s*\)")
_CODE_SUFFIX = re.compile(r"\b\d{6}\s*[.\s]?\s*(?:KS|KQ|KOSPI|KOSDAQ)\b", re.I)
_TICKER_SUFFIX = re.compile(r"\b[A-Z]{1,5}\s*[.\s]?\s*(?:KS|KQ)\b")
_NAME_CUES = re.compile(r"기업설명회|IR[_\s]*개최|IR개최|공시|주주총회|유상증자|무상증자|전환사채|자기주식")
_US_CUE = re.compile(r"\b[A-Z]{1,5}\s*(?:US|\.O|\.N|\.K)\b|NASDAQ|NYSE|S&P\s?500|나스닥|뉴욕증시|미국")


def is_domestic_by_name(name: str, caption: str = "") -> bool:
    """다운로드 전 판단 (파일명 + 메시지 글)."""
    text = f"{name} {caption}"
    if _US_CUE.search(text):
        return False
    return bool(_CODE_PAREN.search(text) or _CODE_SUFFIX.search(text) or _TICKER_SUFFIX.search(text) or _NAME_CUES.search(name))


def is_domestic_by_text(first_page_text: str) -> bool:
    """다운로드 후 판단 (첫 쪽 텍스트)."""
    t = first_page_text or ""
    if _US_CUE.search(t):
        return False
    return bool(_CODE_PAREN.search(t) or _CODE_SUFFIX.search(t))


def first_page_text(path: str) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        return (r.pages[0].extract_text() or "")[:3000] if r.pages else ""
    except Exception:
        return ""
