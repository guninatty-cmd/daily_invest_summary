"""
네이버 뉴스 수집 모듈
- 6대 경제 언론사 지면기사(당일) + 글로벌경제 속보(전날)를 수집한다.
"""
import time
import concurrent.futures

import requests
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


def build_targets(today_str: str, yesterday_str: str, yesterday_param: str) -> dict:
    return {
        "매일경제": {"url": "https://media.naver.com/press/009/newspaper", "max_scroll": 3, "date": today_str},
        "이데일리": {"url": "https://media.naver.com/press/018/newspaper", "max_scroll": 3, "date": today_str},
        "한국경제": {"url": "https://media.naver.com/press/015/newspaper", "max_scroll": 3, "date": today_str},
        "파이낸셜뉴스": {"url": "https://media.naver.com/press/014/newspaper", "max_scroll": 3, "date": today_str},
        "서울경제": {"url": "https://media.naver.com/press/011/newspaper", "max_scroll": 3, "date": today_str},
        "머니투데이": {"url": "https://media.naver.com/press/008/newspaper", "max_scroll": 3, "date": today_str},
        "글로벌경제_속보": {
            "url": f"https://news.naver.com/breakingnews/section/101/262?date={yesterday_param}",
            "max_scroll": 25,
            "date": yesterday_str,
        },
    }


def _build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    options.add_argument('--window-size=1920,1080')
    options.page_load_strategy = 'eager'

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2,
    }
    options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=options)


def _fetch_origin(data: dict) -> dict:
    req_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    n_url = data['네이버_URL']
    origin_url = "원문 링크 없음"
    try:
        res = requests.get(n_url, headers=req_headers, timeout=5)
        if res.status_code == 200:
            art_soup = BeautifulSoup(res.text, 'html.parser')
            origin_tag = art_soup.select_one('a.media_end_head_origin_link')
            if origin_tag and origin_tag.has_attr('href'):
                origin_url = origin_tag['href']
    except Exception:
        pass

    return {
        "기사 등록일": data['기사 등록일'],
        "출처": data['출처'],
        "기사 제목": data['기사 제목'],
        "원문 링크": origin_url,
    }


def scrape_naver_news(today_str: str, yesterday_str: str, yesterday_param: str) -> pd.DataFrame:
    """
    6대 경제지(당일 지면기사) + 글로벌경제 속보(전날)를 수집해 DataFrame으로 반환한다.
    컬럼: 기사 등록일, 출처, 기사 제목, 원문 링크
    """
    targets = build_targets(today_str, yesterday_str, yesterday_param)
    driver = _build_driver()
    article_data_1st = []

    try:
        for publisher, info in targets.items():
            # Reset the dedup set per publisher (was global before).
            # Bug: a shared titles_seen across all outlets meant that once an
            # earlier outlet (e.g. 매일경제) collected a wire-style headline that
            # other outlets also ran verbatim, later outlets in dict order
            # (파이낸셜뉴스, 머니투데이) had that headline silently dropped, causing
            # systematically sparser results for outlets processed later.
            titles_seen = set()
            print(f"📰 [{publisher}] 수집 중...")
            url = info["url"]
            max_scroll = info["max_scroll"]
            target_date = info["date"]

            driver.get(url)
            time.sleep(1.5)

            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0

            while True:
                clicked_more = False
                more_btns = driver.find_elements(By.CSS_SELECTOR, '.section_more_inner, .cjs_btn_more, .section_more a')

                for btn in more_btns:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        scroll_count += 1
                        clicked_more = True
                        break

                if clicked_more:
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
            collected_count = 0

            for tag in soup.find_all(['strong', 'span', 'a', 'div', 'em', 'h4']):
                text = tag.get_text(strip=True)

                if 8 < len(text) < 100:
                    class_attrs = tag.get('class', [])
                    class_str = ' '.join(class_attrs).lower()

                    if 'tit' in class_str or 'text' in class_str or 'headline' in class_str or tag.name == 'strong':
                        exclude_words = ['구독', '만명', '기자', '저작권', '무단전재', '코스피', '코스닥',
                                          '지면기사', 'ⓒ', 'Copyright', '오피니언', '동영상기사', '기사 더보기', publisher]
                        if not any(word in text for word in exclude_words):
                            if text not in titles_seen:
                                parent_a = tag if tag.name == 'a' else tag.find_parent('a')
                                naver_url = parent_a.get('href') if parent_a and parent_a.has_attr('href') else ""

                                if naver_url.startswith('/'):
                                    naver_url = "https://news.naver.com" + naver_url

                                if "naver" in naver_url:
                                    titles_seen.add(text)
                                    article_data_1st.append({
                                        "기사 등록일": target_date,
                                        "출처": publisher,
                                        "기사 제목": text,
                                        "네이버_URL": naver_url,
                                    })
                                    collected_count += 1

            print(f"   ✔️ {collected_count}개 추출 완료")

        print(f"\n🌐 총 {len(article_data_1st)}개 기사의 '원문 링크'를 병렬 추출합니다...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            final_articles = list(executor.map(_fetch_origin, article_data_1st))
        print("   ✔️ 원문 추출 완료!")

    except Exception as e:
        print(f"❌ 네이버 뉴스 수집 중 오류가 발생했습니다: {e}")
        final_articles = []

    finally:
        driver.quit()

    if not final_articles:
        return pd.DataFrame(columns=["기사 등록일", "출처", "기사 제목", "원문 링크"])

    return pd.DataFrame(final_articles)
