"""
유튜브 22개 채널: 전날 영상의 제목/링크/업로드시각 수집 (RSS, API 키 불필요, GitHub Actions에서도 동작)
- 자막(스크립트) 추출은 youtube_transcripts.py 가 담당한다 (구글 클라우드 IP 차단 때문에 별도 처리).
- 쇼츠/라이브(진행중·예정) 제외.
- 수집 구간(common.get_window) 안에 업로드된 영상만 남긴다 (기본: 어제 07:00 ~ 오늘 07:00 KST).
- 채널 목록은 이 파일의 CHANNELS 하나만 관리한다 (PC 자막 추출도 같은 목록 사용).
"""
import re
import concurrent.futures
from xml.etree import ElementTree

import requests

from common import get_window, parse_dt

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

CHANNELS = [  # (채널명, 채널ID)
    ("스노우볼랩스", "UCBF61jlG6g2CNHDLKaJhysw"),
    ("소수몽키", "UCC3yfxS5qC6PCwDzetUuEWg"),
    ("싱글파이어", "UC5CyCSvCdoEP-VgQmFq3iww"),
    ("내일은 투자왕-김단테", "UCKTMvIu9a4VGSrpWy-8bUrQ"),
    ("오늘도 미국 주식", "UCrOj-ImGWaDrk_a8fs_w-EA"),
    ("매일경제(MK_Invest)", "UCIipmgxpUxDmPP-ma3Ahvbw"),
    ("월텍남", "UCWV2Uy79TOpB1bk8hnq1nGw"),
    ("Jun's economy lab", "UCznImSIaxZR7fdLCICLdgaQ"),
    ("이효석아카데미", "UCxvdCnvGODDyuvnELnLkQWw"),
    ("Daishin TV", "UCWQf4EtNPWJSEiXEGv9y7nw"),
    ("T3chfeed", "UCH2sxkxg_vdJSK4KYRXNE0Q"),
    ("한경 글로벌마켓", "UCWskYkV4c4S9D__rsfOl2JA"),
    ("수페TV", "UCfnqgWlC5IvJEAPTmyjaixA"),
    ("너굴경제", "UCXD1p0ghcxXj8u4s5jYbGkw"),
    ("안될공학", "UCeN2YeJcBCRJoXgzF_OU3qw"),
    ("박곰희TV", "UCr7XsrSrvAn_WcU4kF99bbQ"),
    ("주덕", "UChZFFQS6ThJ_VmuE-Yzao8Q"),
    ("RISE ETF", "UCZ9jozYXT6BXl2TchjNH8hw"),
    ("깨비증권 마블TV[KB증권]", "UCD0k4Kq7SJROxxV-9N5v8IA"),
    ("매경 자이앤트", "UCPTy0BNqiv-0SdAvFgrXvXg"),
    ("기릿의 주식노트", "UCw8pcmyPWGSik7bjJpeInlA"),
    ("미국회계사 EK", "UCxUzt4AIpI1XO9cxHQ-ro1w"),
]

NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
LIVE_RE = re.compile(r'"liveBroadcastContent"\s*:\s*"(\w+)"')


def _parse_feed(channel_name: str, channel_id: str) -> list[dict]:
    res = requests.get(FEED_URL.format(channel_id=channel_id), headers=HEADERS, timeout=10)
    res.raise_for_status()
    root = ElementTree.fromstring(res.content)
    items = []
    for entry in root.findall("atom:entry", NS):
        t = entry.find("atom:title", NS)
        vid = entry.find("yt:videoId", NS)
        pub = entry.find("atom:published", NS)
        if t is None or vid is None or not t.text or not vid.text:
            continue
        items.append({
            "출처": f"유튜브 - {channel_name}",
            "채널": channel_name,
            "제목": t.text.strip(),
            "게시일": pub.text if pub is not None else None,
            "링크": f"https://www.youtube.com/watch?v={vid.text}",
            "video_id": vid.text,
        })
    return items


def _is_shorts(video_id: str) -> bool:
    try:
        res = requests.head(f"https://www.youtube.com/shorts/{video_id}", headers=HEADERS,
                            timeout=8, allow_redirects=True)
        return "/shorts/" in res.url
    except Exception:
        return False


def _is_live_or_upcoming(video_id: str) -> bool:
    try:
        res = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=HEADERS, timeout=8)
        m = LIVE_RE.search(res.text)
        return bool(m) and m.group(1) in ("live", "upcoming")
    except Exception:
        return False


def scrape_youtube() -> list[dict]:
    start, end = get_window()
    candidates = []
    for name, cid in CHANNELS:
        try:
            for it in _parse_feed(name, cid):
                dt = parse_dt(it["게시일"])
                if dt and start <= dt < end:       # 구간 안의 영상만 쇼츠 검사 대상 (요청 수 절약)
                    candidates.append(it)
        except Exception as e:
            print(f"⚠️ 유튜브[{name}] 수집 실패: {e}")
    if not candidates:
        return []
    print(f"🔎 유튜브 {len(candidates)}건 중 쇼츠/라이브 확인 중...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        flags = list(ex.map(lambda it: _is_shorts(it["video_id"]) or _is_live_or_upcoming(it["video_id"]), candidates))
    kept = [it for it, bad in zip(candidates, flags) if not bad]
    print(f"   → 쇼츠/라이브 {len(candidates) - len(kept)}건 제외, {len(kept)}건 유지")
    return kept
