"""
유튜브 채널 URL 수집 모듈 (GitHub Actions용)
- youtube_channels.txt 등록 채널의 전날 영상 URL을 RSS로 수집
- 실제 트랜스크립트 추출은 로컬 Claude 스케줄 태스크(NotebookLM)가 담당
- yt-dlp 봇 감지 문제로 URL 수집만 수행
"""
import os
import re
import datetime
import requests
import feedparser
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


def is_youtube_short(video_id: str) -> bool:
    """
    /shorts/{id} URL로 접근했을 때 그대로 유지되면 Shorts.
    일반 영상은 /watch?v={id} 로 리디렉션됨.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.head(
            f"https://www.youtube.com/shorts/{video_id}",
            headers=headers, allow_redirects=True, timeout=10
        )
        return '/shorts/' in resp.url
    except Exception:
        return False  # 확인 실패 시 일반 영상으로 간주


def get_videos_by_date(channel_id: str, target_date: datetime.date) -> list[dict]:
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(feed_url)
        candidates = [
            {
                'id': e.get('yt_videoid', ''),
                'title': e.title,
                'url': f"https://www.youtube.com/watch?v={e.get('yt_videoid', '')}",
                'channel': channel_id,
            }
            for e in feed.entries
            if datetime.datetime(*e.published_parsed[:6]).date() == target_date
        ]
        # Shorts 필터링
        results = []
        for v in candidates:
            if is_youtube_short(v['id']):
                print(f"  ⏭️  Shorts 제외: {v['title']}")
            else:
                results.append(v)
        return results
    except Exception as e:
        print(f"  RSS 피드 오류: {e}")
        return []


def collect_youtube_urls(
    channels_file: str = "youtube_channels.txt",
    output_file: str = "downloads/youtube_urls.txt"
) -> list[dict]:
    """
    전날 유튜브 영상 URL 수집 (RSS 기반, yt-dlp 없음).
    반환: [{'title': str, 'url': str, 'text': ''}, ...]
    youtube_urls.txt 파일에도 저장 (Claude 스케줄 태스크용).
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
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    results = []
    print(f"\n=== [유튜브 URL 수집] 대상: {target_date} | 채널 {len(channels_raw)}개 ===")

    for raw in channels_raw:
        channel_id = resolve_channel_id(raw)
        if not channel_id:
            print(f"  채널 ID 해석 실패: {raw}")
            continue

        videos = get_videos_by_date(channel_id, target_date)
        print(f"  {raw}: {len(videos)}개 영상")

        for video in videos:
            print(f"  ▶ {video['title']} → {video['url']}")
            results.append({
                'title': video['title'],
                'url': video['url'],
                'text': '',   # 트랜스크립트는 NotebookLM에서 추출
            })

    # URL 목록을 파일로 저장 (Claude 스케줄 태스크가 읽음)
    if results:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# 유튜브 URL 목록 | 수집일: {target_date}\n")
            for r in results:
                f.write(f"{r['url']}\t{r['title']}\n")
        print(f"  ✔️ URL {len(results)}건 저장: {output_file}\n")
    else:
        print("  ℹ️  어제 업로드된 영상 없음\n")

    return results


# 하위 호환성 유지 (main.py가 collect_youtube_transcripts 를 호출하는 경우)
def collect_youtube_transcripts(
    channels_file: str = "youtube_channels.txt",
    download_dir: str = "downloads"
) -> list[dict]:
    """collect_youtube_urls의 alias (main.py 호환용)"""
    output_file = os.path.join(download_dir, "youtube_urls.txt")
    return collect_youtube_urls(channels_file=channels_file, output_file=output_file)
