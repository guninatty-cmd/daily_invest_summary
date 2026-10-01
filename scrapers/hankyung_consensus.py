"""한경 컨센서스 - 정적 HTML 게시판 (2026-09-25 확인, 페이지 최초 GET에 목록 렌더링됨)"""
import re

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://consensus.hankyung.com/analysis/list"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_hankyung_consensus() -> list[dict]:
    res = requests.get(LIST_URL, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        date_text = tds[0].get_text(strip=True)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            continue

        title_tag = tr.select_one("a") or tds[2]
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href") if title_tag.name == "a" else None
        link = f"https://consensus.hankyung.com{href}" if href and href.startswith("/") else href

        items.append({
            "출처": "한경 컨센서스",
            "분류": tds[1].get_text(strip=True),
            "제목": title,
            "작성자": tds[3].get_text(strip=True) if len(tds) > 3 else None,
            "제공출처": tds[4].get_text(strip=True) if len(tds) > 4 else None,
            "작성일": date_text,
            "링크": link or LIST_URL,
        })
    return items


if __name__ == "__main__":
    for item in scrape_hankyung_consensus()[:5]:
        print(item)
