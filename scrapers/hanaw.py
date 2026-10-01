"""
하나증권(hanaw.com) 리서치 수집

핵심 발견 (2026-09-25):
처음에 추측했던 파라미터(pid=HAA10101000)는 "0건"이었다. 그런데 실제로는 카테고리 파라미터
없이 목록 페이지 자체(`/main/research/research/list.cmd`)에 접속하면 전체 카테고리(해외주식/
산업기업/Daily/투자전략 등)가 섞인 최신순 목록이 이미 렌더링돼 있다 — 오히려 "새 글 감지"
목적에는 더 편리하다 (카테고리별로 따로 돌 필요 없이 한 번의 GET으로 전체 커버).

각 리포트 행의 "추천하기" 버튼(`a.icon_heart`)에 게시글 식별자가 속성으로 그대로 노출돼 있다:
  <a class="icon_heart" key="1288868" bbscd="1260" subject="[중국 테마 전략] ...">

같은 블록 안의 첨부파일 링크(`a[href*=download.cmd]`)는 세션 없이 바로 접근 가능한 직링크이고,
실제로는 file.hanaw.com의 정적 PDF URL로 302 리다이렉트된다 (예:
https://file.hanaw.com/download/research/FileServer/WEB/strategy/market/2026/09/23/China_Space_260928.pdf).
"상세페이지"(view.cmd)는 세션/리퍼러 없이 직접 GET하면 "연결이 잠시 중단되었습니다" 오류가
떠서(폼 제출 기반 네비게이션으로 추정), 링크 필드는 대신 이 PDF 직다운로드 링크를 사용한다.
"""
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LIST_URL = "https://www.hanaw.com/main/research/research/list.cmd"
BASE = "https://www.hanaw.com"

DATE_RE = re.compile(r"일시\s*:\s*(\d{4}\.\d{2}\.\d{2})")
CATEGORY_RE = re.compile(r"(\S+)\s*>\s*(\S+)")


def scrape_hanaw() -> list[dict]:
    res = requests.get(LIST_URL, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for heart in soup.select("a.icon_heart"):
        bbs_seq = heart.get("key")
        bbs_cd = heart.get("bbscd")
        title = (heart.get("subject") or "").strip()
        if not bbs_seq or not title:
            continue

        # 같은 리포트 블록(div.con) 안에서 다운로드 링크와 날짜/카테고리 텍스트를 찾는다
        con = heart.find_parent("div", class_="con")
        block_text = con.get_text(" ", strip=True) if con else ""

        date_m = DATE_RE.search(block_text)
        date_str = date_m.group(1) if date_m else None

        cat_m = CATEGORY_RE.search(block_text)
        category = f"{cat_m.group(1)} > {cat_m.group(2)}" if cat_m else None

        dl_a = con.select_one("a[href*='download.cmd']") if con else None
        if dl_a and dl_a.get("href"):
            link = BASE + dl_a["href"] if dl_a["href"].startswith("/") else dl_a["href"]
        else:
            # 첨부파일 링크를 못 찾으면 최소한 목록 페이지라도 남긴다
            link = LIST_URL

        items.append({
            "출처": f"하나증권 리서치{(' - ' + category) if category else ''}",
            "제목": title,
            "작성일": date_str,
            "링크": link,
        })
    return items


if __name__ == "__main__":
    for item in scrape_hanaw()[:5]:
        print(item)
