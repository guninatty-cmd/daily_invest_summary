"""
유튜브 영상 분석 (Gemini API 무료 티어, GitHub Actions에서 PC 없이 동작)
- 공개 유튜브 URL을 Gemini에 그대로 넘겨 영상(음성+화면)을 요약한다. 자막 추출/yt-dlp 불필요.
- 대상: 후보=Y(제목이 미국주식 관련) 영상만. 라이브/다시보기/1시간 초과/길이 불명은 제외.
- 무료 한도(하루 유튜브 영상 8시간) 보호: 하루 총 재생시간 상한(MAX_TOTAL_SEC)·건수 상한(MAX_VIDEOS).
- GEMINI_API_KEY 가 없으면 조용히 건너뛴다. 모델은 GEMINI_MODEL(쉼표 구분 목록 가능) 우선, 실패 시 다음 모델.
"""
import os
import time

MAX_SEC = 3600            # 영상 1개 상한 (1시간)
MAX_TOTAL_SEC = 7 * 3600  # 하루 합계 상한 (무료 한도 8시간 안쪽)
MAX_VIDEOS = 12
TOKENS_PER_SEC = 290      # 유튜브 영상 토큰 환산(프레임 258 + 음성 32 /초). 길이 추정용
MAX_RUN_SEC = 15 * 60     # 분석 전체 시간 상한(파이프라인 지연 방지)
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]

PROMPT = """이 유튜브 영상을 미국 주식 투자자 관점에서 한국어로 요약해라. 광고/인사/잡담은 빼고 아래 형식만 출력.
핵심요약: 3~5줄 (영상의 결론과 근거)
언급 종목/지수: 티커 또는 이름 (등락·가격 등 영상에서 말한 숫자 포함)
주요 수치/일정: 영상에서 직접 언급된 숫자와 날짜만
투자 시사점: 1~2줄 (영상 주장 그대로이며 추측 금지)
영상에 없는 내용은 만들지 말고, 확실하지 않으면 '불명'이라고 적어라."""


def _models():
    env = os.environ.get("GEMINI_MODEL", "").strip()
    lst = [m.strip() for m in env.split(",") if m.strip()] if env else []
    return lst + [m for m in DEFAULT_MODELS if m not in lst]


def pick_targets(videos: list[dict]) -> tuple[list[dict], dict]:
    """분석 대상 선정. videos: 후보/점수/길이초/라이브/링크 포함. 반환: (대상, {video_id: 제외사유})"""
    skip, targets, total = {}, [], 0
    for v in sorted(videos, key=lambda x: -x.get("점수", 0)):
        vid = v.get("video_id", "")
        sec = v.get("길이초")
        if v.get("후보") != "Y":
            skip[vid] = "후보 아님"
        elif v.get("라이브"):
            skip[vid] = "라이브/다시보기 제외"
        elif sec is None:
            skip[vid] = "길이 불명 제외"
        elif sec > MAX_SEC:
            skip[vid] = f"1시간 초과({sec // 60}분) 제외"
        elif len(targets) >= MAX_VIDEOS or total + sec > MAX_TOTAL_SEC:
            skip[vid] = "일일 한도 보호로 제외"
        else:
            targets.append(v)
            total += sec
    return targets, skip


def _estimate_len(client, types, models, v):
    """GitHub IP에서는 유튜브 페이지로 길이를 못 읽으므로 Gemini count_tokens 로 길이를 추정한다(영상 분석 비용 없음)."""
    for m in models:
        for attempt in range(2):
            try:
                n = client.models.count_tokens(model=m, contents=types.Content(parts=[
                    types.Part(file_data=types.FileData(file_uri=v["링크"])), types.Part(text="x")]))
                return int(n.total_tokens / TOKENS_PER_SEC)
            except Exception as e:
                msg = str(e)
                if "404" in msg or "NOT_FOUND" in msg:
                    break
                if "503" in msg or "UNAVAILABLE" in msg:
                    time.sleep(5)
                    continue
                return None      # 라이브/비공개/기타 오류는 길이 불명으로 두어 분석에서 제외
    return None


def analyze(videos: list[dict]) -> str:
    """videos 각 항목에 '분석', '분석상태' 를 채운다. 반환: 로그 한 줄."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        targets, skip = pick_targets(videos)
        for v in videos:
            v["분석"] = ""
            v["분석상태"] = skip.get(v.get("video_id", ""), "대기")
        for v in targets:
            v["분석상태"] = "GEMINI_API_KEY 없음"
        return "Gemini 분석 건너뜀: GEMINI_API_KEY 미설정"
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        for v in videos:
            v["분석"], v["분석상태"] = "", "google-genai 미설치"
        return f"Gemini 분석 실패: {e}"

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=240000))  # 요청당 4분 상한(무한 대기 방지)
    models = _models()
    n_est = 0
    for v in videos:       # 길이를 모르는 후보 영상은 토큰 수로 길이 추정
        if v.get("후보") == "Y" and not v.get("라이브") and v.get("길이초") is None:
            sec = _estimate_len(client, types, models, v)
            if sec is not None:
                v["길이초"], v["길이추정"] = sec, True
                n_est += 1
    targets, skip = pick_targets(videos)
    for v in videos:
        v["분석"] = ""
        v["분석상태"] = skip.get(v.get("video_id", ""), "대기")
    if not targets:
        return f"Gemini 분석 대상 0건 (길이 추정 {n_est}건)"
    ok = fail = 0
    quota_hit = False
    t_start = time.time()
    for v in targets:
        if quota_hit:
            v["분석상태"] = "무료 한도 소진"
            continue
        if time.time() - t_start > MAX_RUN_SEC:
            v["분석상태"] = "분석 시간 상한으로 건너뜀"
            continue
        last = ""
        for m in list(models):
            done = False
            for attempt in range(3):          # 503(과부하)는 같은 모델로 최대 3번 재시도
                t0 = time.time()
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=types.Content(parts=[
                            types.Part(file_data=types.FileData(file_uri=v["링크"])),
                            types.Part(text=PROMPT),
                        ]),
                        config=types.GenerateContentConfig(
                            media_resolution="MEDIA_RESOLUTION_LOW", temperature=0.2),
                    )
                    print(f"[gemini] {v.get('video_id')} {m} {time.time() - t0:.0f}s 응답")
                    txt = (resp.text or "").strip()
                    if txt:
                        v["분석"], v["분석상태"] = txt, f"완료({m})"
                        ok += 1
                        models = [m] + [x for x in models if x != m]   # 성공 모델을 우선 사용
                        done = True
                    else:
                        last = "빈 응답"
                    break
                except Exception as e:
                    msg = str(e)
                    last = f"{type(e).__name__}: {msg[:90]}"
                    print(f"[gemini] {v.get('video_id')} {m} {time.time() - t0:.0f}s 오류 {last}")
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        quota_hit = True
                        break
                    if "404" in msg or "NOT_FOUND" in msg:
                        models = [x for x in models if x != m] or models   # 없는 모델은 이후 건너뜀
                        break
                    if "503" in msg or "UNAVAILABLE" in msg:
                        time.sleep(15 * (attempt + 1))
                        continue
                    time.sleep(2)
                    break
            if done or quota_hit:
                break
        if not v["분석"]:
            v["분석상태"] = f"실패: {last}"
            fail += 1
        time.sleep(1)
    return f"Gemini 분석 완료 {ok}건 / 실패 {fail}건 / 대상 {len(targets)}건 / 길이추정 {n_est}건 (모델: {','.join(models[:2])})"
