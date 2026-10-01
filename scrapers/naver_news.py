"""
네이버 뉴스 수집 (통합본 - 이 파일 하나가 네이버 수집의 유일한 창구)

예전에는 두 저장소가 같은 6개 언론사(매일경제/이데일리/한국경제/파이낸셜뉴스/서울경제/머니투데이)를
각각 수집해서 중복이 생겼다. 통합 후에는 이 모듈만 네이버를 수집하고, 아래 두 가지를 합쳐서 한 번만 돌린다.
  1) 6대 경제지 '오늘 지면기사' (media.naver.com/press/<id>/newspaper)
  2) 네이버 금융/글로벌경제 속보 (어제 + 오늘 새벽분)
추가로 main.py 단계의 링크/제목 정규화 중복 제거가 같은 기사를 한 번 더 걸러낸다.

게시일은 원문(언론사) 페이지의 article:published_time 을 우선 사용하고 없으면 네이버 페이지 값을 쓴다.
"""
import time
import concurrent.futures

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from common import get_window

PRESS = {
    "매일경제": "009",
    "이데일리": "018",
    "한국경제": "015",
    "파이낸셜뉴스": "014",
    "서울경제": "011",
    "머니투데이": "008",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
EXCLUDE_WORDS = ['구독', '만명', '기자', '저작권', '무단전재', '코스피', '코스닥',
                 '지면기사', 'ⓒ', 'Copyright', '오피니언', '동영상기사', '기사 더보기']


def build_targets() -> list[dict]:
    start, end = get_window()
    d_prev = start.strftime("%Y%m%d")   # 구간 시작일(어제)
    d_today = end.strftime("%Y%m%d")    # 구간 종료일(오늘 새벽분)
    targets = [{"출처": name, "url": f"https://media.naver.com/press/{code}/newspaper", "max_scroll": 3}
               for name, code in PRESS.items()]
    targets.append({"출처": "네이버 글로벌경제 속보",
                    "url": f"https://news.naver.com/breakingnews/section/101/262?date={d_prev}", "max_scroll": 25})
    targets.append({"출처": "네이버 글로벌경제 속보",
                    "url": f"https://news.naver.com/breakingnews/section/101/262?date={d_today}", "max_scroll": 6})
    return targets


def _build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument(f'--user-agent={HEADERS["User-Agent"]}')
    options.add_argument('--window-size=1920,1080')
    options.page_load_strategy = 'eager'
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2,
    })
    return webdriver.Chrome(options=options)


def _fetch_origin_and_date(naver_url: str):
    """네이버 기사 페이지 -> (원문 링크, 게시일시 문자열 또는 None)"""
    origin, pub_date = "", None
    try:
        res = requests.get(naver_url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            tag = soup.select_one('a.media_end_head_origin_link')
            if tag and tag.has_attr('href'):
                origin = tag['href']
            if origin:  # 1순위: 원문 페이지의 발행시각 (네이버 등록일과 다를 수 있음)
                try:
                    r2 = requests.get(origin, headers=HEADERS, timeout=5)
                    if r2.status_code == 200:
                        m = BeautifulSoup(r2.text, 'html.parser').select_one('meta[property="article:published_time"]')
                        if m and m.has_attr('content'):
                            pub_date = m['content']
                except Exception:
                    pass
            if not pub_date:  # 2순위: 네이버 페이지 자체 값
                m = soup.select_one('meta[property="article:published_time"]')
                if m and m.has_attr('content'):
                    pub_date = m['content']
                else:
                    d = soup.select_one('span.media_end_head_info_datestamp_time')
                    if d is not None:
                        pub_date = d.get('data-date-time') or d.get_text(strip=True)
    except Exception:
        pass
    return origin, pub_date


def _scroll_and_collect(driver, target: dict) -> list[dict]:
    publisher, url, max_scroll = target["출처"], target["url"], target["max_scroll"]
    driver.get(url)
    time.sleep(1.5)
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    while True:
        clicked = False
        for btn in driver.find_elements(By.CSS_SELECTOR, '.section_more_inner, .cjs_btn_more, .section_more a'):
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1)
                scroll_count += 1
                clicked = True
                break
        if clicked:
            if scroll_count >= max_scroll:
                break
            continue
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height or scroll_count >= max_scroll:
            break
        last_height = new_height
        scroll_count += 1

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    titles_seen, items = set(), []
    for tag in soup.find_all(['strong', 'span', 'a', 'div', 'em', 'h4']):
        text = tag.get_text(strip=True)
        if not (8 < len(text) < 100):
            continue
        cls = ' '.join(tag.get('class', [])).lower()
        if not ('tit' in cls or 'text' in cls or 'headline' in cls or tag.name == 'strong'):
            continue
        if any(w in text for w in EXCLUDE_WORDS) or publisher in text or text in titles_seen:
            continue
        parent_a = tag if tag.name == 'a' else tag.find_parent('a')
        n_url = parent_a.get('href') if parent_a and parent_a.has_attr('href') else ""
        if n_url.startswith('/'):
            n_url = "https://news.naver.com" + n_url
        if "naver" not in n_url:
            continue
        titles_seen.add(text)
        items.append({"출처": publisher, "제목": text, "_naver_url": n_url})
    print(f"   ✔️ [{publisher}] {len(items)}건 ({url.split('?')[-1] if '?' in url else 'newspaper'})")
    return items


def scrape_naver_news() -> list[dict]:
    driver = _build_driver()
    raw = []
    try:
        for target in build_targets():
            try:
                raw.extend(_scroll_and_collect(driver, target))
            except Exception as e:
                print(f"   ⚠️ {target['출처']} 수집 실패: {e}")
    finally:
        driver.quit()

    print(f"🌐 {len(raw)}건 원문 링크/게시일 병렬 추출 중...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda a: _fetch_origin_and_date(a["_naver_url"]), raw))
    dated = 0
    for art, (origin, pub) in zip(raw, results):
        art["링크"] = origin or art["_naver_url"]
        art["게시일"] = pub
        dated += bool(pub)
        art.pop("_naver_url", None)
    print(f"🗓️ 게시일 추출 성공: {dated}/{len(raw)}건")
    return raw
