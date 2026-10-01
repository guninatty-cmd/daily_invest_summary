"""
Tier A 중 '게시판 목록 페이지 + 실제 글 직링크' 패턴인 사이트들을 하나의 설정 테이블로 처리.

각 사이트마다 전용 CSS 셀렉터를 일일이 만드는 대신, 2026-09-25 조사에서 확인한
"실제 글 URL이 매칭되는 href 패턴"을 기준으로 목록 페이지의 <a> 태그를 모두 훑어서
그 패턴에 맞는 링크만 골라내는 방식으로 구현했다 (naver_news.py에서 쓰던 방식과 동일한 접근).

주의: 여기 적힌 href_pattern들은 2026-09-25에 브라우저로 직접 확인한 것이지만,
CSS 셀렉터 기반이 아니라 정규식 기반이라 오탐(다른 링크가 우연히 패턴에 걸리는 경우)이나
누락이 있을 수 있다. 처음 실행 시 결과 개수/제목이 그럴듯한지 한 번 눈으로 확인 권장.
"""
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SITES = [
    {
        "name": "다음 금융 해외뉴스",
        "list_url": "https://finance.daum.net/global/news",
        "href_pattern": r"v\.daum\.net/v/",
    },
    {
        "name": "매경 미라클AI 뉴스레터",
        "list_url": "https://www.mk.co.kr/mirakleai/newsletter",
        "href_pattern": r"mk\.co\.kr/(news|mirakleai)/.+\d{6,}",
    },
    {
        "name": "KB Think",
        "list_url": "https://kbthink.com/investment.html",
        "href_pattern": r"kbthink\.com/.+\.html",
    },
    {
        "name": "KB금융 리서치",
        "list_url": "https://www.kbfg.com/kbresearch/report/reportList.do",
        "href_pattern": r"reportId=\d+",
    },
    {
        "name": "한국경제 글로벌마켓",
        "list_url": "https://www.hankyung.com/globalmarket/1120",
        "href_pattern": r"hankyung\.com/article/\d+",
    },
    {
        "name": "KB자산운용 RISE ETF 인사이트",
        "list_url": "https://kbam.co.kr/insights",
        "href_pattern": r"kbam\.co\.kr/insights?/[\w-]+",
    },
    {
        "name": "PLUS ETF 리포트",
        "list_url": "https://www.plusetf.co.kr/insight/report/list",
        "href_pattern": r"detail\?n=\d+",
    },
    {
        "name": "Investing.com 코리아 뉴스",
        "list_url": "https://kr.investing.com/news/latest-news",
        "href_pattern": r"kr\.investing\.com/news/[\w-]+-\d+",
    },
    {
        "name": "머니네버슬립",
        "list_url": "https://moneyneversleeps.co.kr/",
        "href_pattern": r"articleView\.html\?idxno=\d+",
    },
    {
        "name": "순살브리핑",
        "list_url": "https://soonsal.com/newsletters/",
        "href_pattern": r"soonsal\.com/newsletters/[\w-]+",
    },
    {
        "name": "삼성 KoAct 인사이트",
        "list_url": "https://www.samsungactive.co.kr/insight/koactinsight/list.do?seq=0",
        "href_pattern": r"koactinsight/(view|detail)\.do",
    },
]


def _scrape_one(site: dict) -> list[dict]:
    res = requests.get(site["list_url"], headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    pattern = re.compile(site["href_pattern"])
    seen = set()
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.search(href):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 4:
            continue
        link = href if href.startswith("http") else requests.compat.urljoin(site["list_url"], href)
        if link in seen:
            continue
        seen.add(link)
        items.append({"출처": site["name"], "제목": title, "링크": link})
    return items


def scrape_generic_sites() -> list[dict]:
    all_items = []
    for site in SITES:
        try:
            found = _scrape_one(site)
            print(f"✔️ {site['name']}: {len(found)}건")
            all_items.extend(found)
        except Exception as e:
            print(f"⚠️ {site['name']} 수집 실패: {e}")
    return all_items


if __name__ == "__main__":
    for item in scrape_generic_sites()[:20]:
        print(item)
