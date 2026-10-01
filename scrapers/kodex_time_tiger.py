"""
KODEX / TIME / TIGER ETF 인사이트 - 2026-09-25 재확인 결과 셋 다 '클릭해야만 알 수 있는 링크'가
아니라 정적 HTML 안에 실제 href(또는 href로 바로 재구성 가능한 onclick 문자열)가 그대로 들어있어
Playwright 없이 requests만으로 충분하다. (기존 리포트에서 Tier B로 분류했던 것을 정정)

- KODEX: <a class="content-texts" href="view.do?seqn=79693">
- TIME  : <div class="tit"><a href="?bbsid=report&idx=46">
- TIGER : <a class="c-card" href="javascript:cmmCtrl.details('detailsKey', '757', './view.do');">
          → 정규식으로 detailsKey 추출 후 URL 재구성
"""
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_kodex() -> list[dict]:
    base = "https://m.samsungfund.com/etf/insight/newsroom/"
    res = requests.get(base + "index.do?seq=0", headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for a in soup.select("a.content-texts[href]"):
        title_tag = a.select_one("h5, .content-title") or a
        title = title_tag.get_text(strip=True)
        if not title:
            continue
        items.append({
            "출처": "삼성 KODEX 뉴스룸",
            "제목": title,
            "링크": base + a["href"],
        })
    return items


def scrape_time_etf() -> list[dict]:
    base = "https://timeetf.co.kr/board/board.php"
    res = requests.get(base, params={"bbsid": "report"}, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for tit_div in soup.select("div.tit"):
        a = tit_div.find("a", href=True)
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a["href"]
        link = base + href if href.startswith("?") else href
        items.append({"출처": "TIME ETF 리포트", "제목": title, "링크": link})
    return items


def scrape_tiger_etf() -> list[dict]:
    list_url = "https://investments.miraeasset.com/tigeretf/ko/insight/etf-insight/list.do"
    res = requests.get(list_url, params={"listCnt": 20, "pageIndex": 1}, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for a in soup.select("a.c-card[href*='cmmCtrl.details']"):
        m = re.search(r"cmmCtrl\.details\('detailsKey',\s*'(\d+)'", a["href"])
        if not m:
            continue
        title_tag = a.select_one(".c-card-header, h5, .tit")
        title = title_tag.get_text(strip=True) if title_tag else a.get_text(strip=True)
        detail_key = m.group(1)
        items.append({
            "출처": "TIGER ETF 인사이트",
            "제목": title,
            "링크": f"https://investments.miraeasset.com/tigeretf/ko/insight/etf-insight/hot-etf/view.do?detailsKey={detail_key}",
        })
    return items


if __name__ == "__main__":
    for fn in (scrape_kodex, scrape_time_etf, scrape_tiger_etf):
        print(f"--- {fn.__name__} ---")
        for item in fn()[:3]:
            print(item)
