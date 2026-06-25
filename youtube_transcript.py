"""
유튜브 채널 한국어 자막 자동 수집 모듈
- youtube_channels.txt 에 등록된 채널의 전날 영상 자막 추출
- yt-dlp 자막 추출 방식 (오디오 다운로드 없음)
"""
import os
import re
import datetime
import shutil
import feedparser
import requests
import yt_dlp
from datetime import timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def resolve_channel_id(channel_input: str) -> str | None:
    channel_input = channel_input.strip()
    if re.match(r'^UC[a-zA-Z0-9_-]{22}$', channel_input):
        return channel_input
    id_match = re.search(r'youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})', channel_input)
    if id_match:
        return id_match.group(1)
    handle_match = re.search(r'youtube\.com/@([^/?&\s]+)', channel_input)
    handle = handle_match.group(1) if handle_match else channel_input.lstrip('@')
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(f"https://www.youtube.com/@{handle}", headers=headers, timeout=15)
        for pattern in [r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', r'"externalId":"(UC[a-zA-Z0-9_-]{22})"']:
            m = re.search(pattern, resp.text)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"  채널 ID 조회 실패 ({handle}): {e}")
    return None


def get_videos_by_date(channel_id: str, target_date: datetime.date) -> list[dict]:
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(feed_url)
        return [
            {
                'id': e.get('yt_videoid', ''),
                'title': e.title,
                'url': f"https://www.youtube.com/watch?v={e.get('yt_videoid', '')}",
            }
            for e in feed.entries
            if datetime.datetime(*e.published_parsed[:6]).date() == target_date
        ]
    except Exception as e:
        print(f"  RSS 피드 오류: {e}")
        return []


def clean_vtt(vtt_text: str) -> str:
    seen = []
    for line in vtt_text.splitlines():
        line = line.strip()
        if (not line or line.startswith('WEBVTT') or line.startswith('Kind:')
                or line.startswith('Language:') or re.match(r'^\d+$', line)
                or re.match(r'[\d:.,\s]+-->', line)):
            continue
        line = re.sub(r'<[^>]+>', '', line).strip()
        if line and (not seen or seen[-1] != line):
            seen.append(line)
    text = ' '.join(seen)
    text = re.sub(r'([.!?])\s+', r'\1\n', text)
    return text.strip()


def download_subtitle(video_url: str, video_id: str, temp_dir: str) -> str | None:
    ydl_opts = {
        'skip_download': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['ko'],
        'subtitlesformat': 'vtt',
        'outtmpl': os.path.join(temp_dir, video_id),
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        vtt_files = list(Path(temp_dir).glob(f"{video_id}*.vtt"))
        if not vtt_files:
            print(f"  자막 없음 (자동자막 미제공 영상)")
            return None
        text = clean_vtt(vtt_files[0].read_text(encoding='utf-8'))
        for f in vtt_files:
            f.unlink()
        return text or None
    except Exception as e:
        print(f"  자막 다운로드 실패: {e}")
        return None


def collect_youtube_transcripts(
    channels_file: str = "youtube_channels.txt",
    download_dir: str = "downloads"
) -> list[dict]:
    """
    전날 유튜브 영상 자막 수집.
    반환: [{'title': str, 'url': str, 'text': str}, ...]
    """
    if not os.path.exists(channels_file):
        print(f"⚠️  {channels_file} 없음, 유튜브 수집 건너뜀")
        return []

    lines = Path(channels_file).read_text(encoding='utf-8').splitlines()
    channels_raw = [l.strip() for l in lines if l.strip() and not l.startswith('#')]

    if not channels_raw:
        print("⚠️  youtube_channels.txt 에 채널이 없음")
        return []

    target_date = (datetime.datetime.now(KST) - timedelta(days=1)).date()
    temp_dir = os.path.join(download_dir, "_yt_temp")
    os.makedirs(temp_dir, exist_ok=True)

    results = []
    print(f"\n=== [유튜브 자막] 대상: {target_date} | 채널 {len(channels_raw)}개 ===")

    for raw in channels_raw:
        channel_id = resolve_channel_id(raw)
        if not channel_id:
            print(f"  채널 ID 해석 실패: {raw}")
            continue

        videos = get_videos_by_date(channel_id, target_date)
        print(f"  {raw}: {len(videos)}개 영상")

        for video in videos:
            print(f"  ▶ {video['title']}")
            text = download_subtitle(video['url'], video['id'], temp_dir)
            if text:
                results.append({'title': video['title'], 'url': video['url'], 'text': text})

    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"  ✔️ 유튜브 자막 {len(results)}건 수집 완료\n")
    return results
