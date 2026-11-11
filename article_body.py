"""
후보 기사(후보=Y)의 본문 수집.

네이버 뉴스는 봇 접근을 막으므로 원칙은 '언론사 원문 페이지'에서 본문을 읽는 것이다.
  1) 링크가 이미 언론사 직링크면 그 페이지에서 본문 추출
  2) 링크가 네이버(n.news.naver.com)면 원문 링크(a.media_end_head_origin_link)를 찾아 그 언론사 페이지에서 추출
     - requests 로 못 찾으면 Selenium(목록 수집에 이미 쓰는 헤드리스 Chrome)으로 한 번 더 시도
  3) 언론사 페이지 본문을 못 얻으면 마지막 수단으로 네이버 페이지 본문(#dic_area)을 쓰고 '본문출처'에 표시
결과: it["본문"] (최대 BODY_MAX자), it["본문출처"] ('원문'/'네이버'/'없음'), 원문 링크를 찾으면 it["링크"] 도 직링크로 교체.
수집 실패는 조용히 '없음'으로 넘어가며 파이프라인을 멈추지 않는다.
"""
import re
import time
import concurrent.futures

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "ko-KR,ko;q=0.9"}
BODY_MAX = 3000
MIN_BODY = 150
BODY_SELECTORS = ["[itemprop=articleBody]", "#dic_area", "#newsct_article", "#articleBody", "#article-view-content-div",
                  "#articletxt", "#article_txt", "#newsEndContents", ".article_body", ".article-body", ".articleBody",
                  ".news_cnt_detail_wrap", ".view_cont", ".art_txt", "#content article", "article"]
JUNK_SEL = "script,style,noscript,nav,footer,aside,header,form,iframe,figure,.ad,.advertisement,.reporter_area,.byline,.copyright,.btn_area"
JUNK_LINE = re.compile(r"(무단\s*전재|재배포\s*금지|Copyright|ⓒ|구독하기|기자\s*구독|관련기사|저작권자|\S+@\S+\.\S+)")


def is_naver(url: str) -> bool:
    return "naver.com" in (url or "")


def _clean(text: str) -> str:
    lines = [re.sub(r"\s+", " ", l).strip() for l in re.split(r"[\r\n]+", text)]
    lines = [l for l in lines if l and not JUNK_LINE.search(l)]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def extract_body(html: str) -> str:
    """HTML -> 본문 텍스트. 기사 본문 셀렉터를 우선, 없으면 긴 <p> 들을 이어 붙인다."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select(JUNK_SEL):
        tag.decompose()
    for sel in BODY_SELECTORS:
        node = soup.select_one(sel)
        if node:
            t = _clean(node.get_text("\n"))
            if len(t) >= MIN_BODY:
                return t[:BODY_MAX]
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    t = _clean("\n".join(p for p in paras if len(p) >= 30))
    return t[:BODY_MAX] if len(t) >= MIN_BODY else ""


def _get(url: str, timeout=8):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    if r.status_code != 200:
        return ""
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding
    return r.text


def _origin_from_html(html: str) -> str:
    tag = BeautifulSoup(html, "html.parser").select_one("a.media_end_head_origin_link")
    return tag["href"] if tag and tag.has_attr("href") else ""


def _fetch_direct(url: str):
    """언론사 직링크 -> (본문, 사용한 링크)"""
    try:
        return extract_body(_get(url)), url
    except Exception:
        return "", url


def _fetch_via_requests(it: dict):
    url = it.get("링크", "")
    if not url:
        return
    if not is_naver(url):
        body, _ = _fetch_direct(url)
        if body:
            it["본문"], it["본문출처"] = body, "원문"
        return
    try:
        html = _get(url, timeout=6)
    except Exception:
        return
    if not html:
        return
    origin = _origin_from_html(html)
    if origin:
        it["링크"] = origin
        body, _ = _fetch_direct(origin)
        if body:
            it["본문"], it["본문출처"] = body, "원문"
            return
    nb = extract_body(html)
    if nb:
        it["_naver_body"] = nb


def _fetch_via_selenium(items: list, budget_sec: int):
    """requests 로 원문 링크를 못 찾은 네이버 기사만, 헤드리스 Chrome 으로 한 번 더."""
    todo = [it for it in items if not it.get("본문") and is_naver(it.get("링크", ""))]
    if not todo:
        return
    from scrapers.naver_news import _build_driver
    driver = _build_driver()
    t0 = time.time()
    try:
        for it in todo:
            if time.time() - t0 > budget_sec:
                break
            try:
                driver.get(it["링크"])
                time.sleep(1.0)
                html = driver.page_source
                origin = _origin_from_html(html)
                if origin:
                    it["링크"] = origin
                    body, _ = _fetch_direct(origin)
                    if body:
                        it["본문"], it["본문출처"] = body, "원문"
                        continue
                nb = extract_body(html)
                if nb and not it.get("_naver_body"):
                    it["_naver_body"] = nb
            except Exception:
                continue
    finally:
        driver.quit()


def attach_article_bodies(items: list, workers=8, selenium_budget_sec=420) -> dict:
    """후보=Y 기사에 본문을 붙인다. 반환: 집계 dict"""
    cands = [it for it in items if it.get("후보") == "Y"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_fetch_via_requests, cands))
    try:
        _fetch_via_selenium(cands, selenium_budget_sec)
    except Exception as e:
        print(f"   ⚠️ Selenium 본문 보강 실패: {type(e).__name__}: {str(e)[:80]}")
    stat = {"원문": 0, "네이버": 0, "없음": 0}
    for it in cands:
        if it.get("본문"):
            stat["원문"] += 1
        elif it.get("_naver_body"):
            it["본문"], it["본문출처"] = it["_naver_body"], "네이버"
            stat["네이버"] += 1
        else:
            it["본문"], it["본문출처"] = "", "없음"
            stat["없음"] += 1
        it.pop("_naver_body", None)
    return stat
