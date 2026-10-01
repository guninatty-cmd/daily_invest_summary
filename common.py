"""
공통 유틸: KST 시간대, 수집 구간(window), 링크/제목 정규화.

[수집 구간 규칙] 모든 수집기가 이 하나의 구간을 공유한다 (예전엔 텔레그램 19시~19시,
유튜브 21시~21시, 뉴스는 '어제 날짜'로 제각각이었음).
  구간 = (직전 07:00 KST) ~ (그 24시간 전 07:00 KST)
  - 평일 07:00에 실행되면: 어제 07:00 ~ 오늘 07:00
  - 늦게 지연 실행되거나 수동 실행해도 같은 구간 (기준은 '실행 시각 이전의 가장 최근 07:00')
  - 재실행/과거 날짜 재수집: 환경변수 WINDOW_END="2026-10-02 07:00" 로 고정 가능
"""
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from dateutil import parser as dateparser

KST = timezone(timedelta(hours=9))
RUN_HOUR_KST = 7


def get_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """(start, end) KST aware datetime. end = 실행 시각 이전의 가장 최근 07:00."""
    override = os.environ.get("WINDOW_END", "").strip()
    if override:
        end = dateparser.parse(override).replace(tzinfo=KST, minute=0, second=0, microsecond=0)
    else:
        now = now or datetime.now(KST)
        end = now.replace(hour=RUN_HOUR_KST, minute=0, second=0, microsecond=0)
        if now < end:
            end -= timedelta(days=1)
    return end - timedelta(days=1), end


def parse_dt(raw) -> datetime | None:
    """다양한 형식의 날짜/시각 문자열 -> KST aware datetime. 시각이 없으면 00:00으로 간주하되
    has_time 판단은 has_time_part()로 따로 한다. 실패 시 None."""
    if not raw:
        return None
    try:
        dt = dateparser.parse(str(raw), fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    this_year = datetime.now(KST).year
    if not (this_year - 2 <= dt.year <= this_year + 1):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def has_time_part(raw) -> bool:
    return bool(re.search(r"\d{1,2}:\d{2}", str(raw or "")))


_TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                  "fbclid", "gclid", "ref", "from"}


def normalize_link(link: str | None) -> str:
    if not link or not link.startswith("http"):
        return ""
    p = urlsplit(link.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in _TRACKING_KEYS]
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""), path, urlencode(q), ""))


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", title)  # [속보], (단독) 접두 태그 제거
    t = re.sub(r"[^\w가-힣]", "", t)
    return t.lower()
