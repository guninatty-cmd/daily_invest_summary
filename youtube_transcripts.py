"""
유튜브 자막(스크립트) 추출 -> '{날짜}_유튜브_자막.xlsx' 로 저장.

⚠️ GitHub Actions(클라우드 IP)에서는 유튜브가 자막 요청을 막는 경우가 많다(기존 프로그램의 주석에도 같은 내용).
   그래서 두 가지 모드를 둔다.
   - PC 모드(권장): 사용자 PC에서 `python main.py --youtube-only` (Windows 작업 스케줄러로 매일 자동 실행)
   - Actions 모드(선택): 환경변수 ACTIONS_TRANSCRIPTS=1 일 때만 시도. 연속 실패가 나면 즉시 포기하고
     나머지는 '자막대기'로 표시해 둔다(계정 쿠키를 클라우드 IP로 반복 노출하지 않기 위함).

환경변수(모두 선택): YTDLP_COOKIES_FILE, YTDLP_COOKIES_BROWSER, YTDLP_REQUEST_DELAY_SEC(기본 3),
                    YTDLP_SLEEP_BEFORE_SUBTITLE_SEC(기본 60), MAX_CONSECUTIVE_FAILS(기본 3)
"""
import os
import re
import glob
import time
import shutil
import tempfile

import pandas as pd

MAX_CELL_CHARS = 32000
REQUEST_DELAY_SEC = float(os.environ.get("YTDLP_REQUEST_DELAY_SEC", "3"))
SLEEP_BEFORE_SUBTITLE_SEC = int(os.environ.get("YTDLP_SLEEP_BEFORE_SUBTITLE_SEC", "60"))
MAX_CONSECUTIVE_FAILS = int(os.environ.get("MAX_CONSECUTIVE_FAILS", "3"))

_cookies_file = os.environ.get("YTDLP_COOKIES_FILE", "").strip()
COOKIES_FILE = _cookies_file if _cookies_file and os.path.isfile(_cookies_file) else None
COOKIES_BROWSER = None if COOKIES_FILE else (os.environ.get("YTDLP_COOKIES_BROWSER", "").strip() or None)


def _vtt_to_text(vtt_path: str) -> str:
    with open(vtt_path, encoding="utf-8") as f:
        content = f.read()
    lines = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            lines.append(line)
    deduped = []
    for line in lines:  # 자동 자막의 롤링 중복 제거
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return " ".join(" ".join(deduped).split())


class RateLimited(Exception):
    pass


def _download_one_language(video_id: str, lang: str, tmpdir: str, max_retries: int = 3):
    import yt_dlp
    ydl_opts = {
        "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": [lang],
        "subtitlesformat": "vtt", "skip_download": True,
        "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True,
        "sleep_interval_subtitles": SLEEP_BEFORE_SUBTITLE_SEC,
        "extractor_args": {"youtube": {"skip": ["translated_subs"]}},
        "format": "best",
    }
    if COOKIES_FILE:
        ydl_opts["cookiefile"] = COOKIES_FILE
    elif COOKIES_BROWSER:
        ydl_opts["cookiesfrombrowser"] = (COOKIES_BROWSER,)
    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            return glob.glob(os.path.join(tmpdir, f"{video_id}.{lang}*.vtt"))
        except Exception as e:
            msg = str(e)
            blocked = "429" in msg or "Too Many Requests" in msg or "Sign in to confirm" in msg
            if blocked and attempt < max_retries:
                time.sleep(60 * attempt)
                continue
            if blocked:
                raise RateLimited(msg)
            return []
    return []


def get_transcript(video_id: str) -> tuple[str, str]:
    """(상태, 텍스트). 상태: 완료 / 자막없음 / 차단"""
    for lang in ("ko", "en"):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                files = _download_one_language(video_id, lang, tmp)
            except RateLimited:
                return "차단", ""
            if not files:
                continue
            try:
                text = _vtt_to_text(files[0])
            except Exception:
                continue
            if text:
                return "완료", text[:MAX_CELL_CHARS] + (" ...(생략)" if len(text) > MAX_CELL_CHARS else "")
    return "자막없음", ""


def extract_transcripts(videos: list[dict]) -> list[dict]:
    """videos: scrape_youtube() 결과. 각 항목에 '자막상태','자막' 추가해서 반환."""
    if not videos:
        return []
    if not shutil.which("yt-dlp") and not _has_module("yt_dlp"):
        print("⚠️ yt-dlp 미설치 - 자막 추출 건너뜀")
        for v in videos:
            v.update({"자막상태": "자막대기", "자막": ""})
        return videos
    fails = 0
    for i, v in enumerate(videos, 1):
        if fails >= MAX_CONSECUTIVE_FAILS:
            v.update({"자막상태": "자막대기", "자막": ""})
            continue
        status, text = get_transcript(v["video_id"])
        v.update({"자막상태": status, "자막": text})
        fails = fails + 1 if status == "차단" else 0
        print(f"  [{i}/{len(videos)}] {status} ({len(text)}자) {v['제목'][:40]}")
        if fails >= MAX_CONSECUTIVE_FAILS:
            print(f"⚠️ 연속 {fails}회 차단 → 남은 영상은 '자막대기'로 표시하고 중단합니다.")
        time.sleep(REQUEST_DELAY_SEC)
    return videos


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def write_transcript_excel(videos: list[dict], path: str):
    cols = ["채널", "제목", "링크", "게시일", "자막상태", "자막"]
    rows = [{c: v.get(c, "") for c in cols} for v in videos]
    pd.DataFrame(rows, columns=cols).to_excel(path, index=False)
