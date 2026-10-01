"""
ACE ETF(한투운용) 리서치 - Next.js SSR 페이지라 requests만으로 충분 (2026-09-25 확인).
목록 페이지 최초 HTML(__NEXT_DATA__ script 태그)에 전체 목록이 JSON으로 그대로 박혀 있고,
개별 글 URL은 /info/research/{숫자ID} 패턴.
"""
import json
import re

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.aceetf.co.kr/info/research"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_ace_etf() -> list[dict]:
    res = requests.get(LIST_URL, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    script_tag = soup.find("script", id="__NEXT_DATA__")
    items = []

    if script_tag and script_tag.string:
        try:
            data = json.loads(script_tag.string)
            # 정확한 경로는 Next.js 버전/페이지 구조에 따라 달라질 수 있어 재귀적으로
            # "id"+"title"(또는 유사 키) 조합을 가진 dict를 찾아내는 방식으로 방어적으로 파싱한다.
            def walk(node):
                if isinstance(node, dict):
                    keys = {k.lower() for k in node.keys()}
                    if {"id"}.issubset(keys) and any(k in keys for k in ("title", "subject", "titl")):
                        yield node
                    for v in node.values():
                        yield from walk(v)
                elif isinstance(node, list):
                    for v in node:
                        yield from walk(v)

            for node in walk(data):
                node_lower = {k.lower(): v for k, v in node.items()}
                _id = node_lower.get("id")
                title = node_lower.get("title") or node_lower.get("subject") or node_lower.get("titl")
                date = node_lower.get("date") or node_lower.get("regdate") or node_lower.get("createdat")
                if not _id or not title:
                    continue
                items.append({
                    "출처": "ACE ETF 리서치",
                    "제목": title,
                    "작성일": date,
                    "링크": f"https://www.aceetf.co.kr/info/research/{_id}",
                })
        except Exception as e:
            print(f"⚠️ ACE ETF __NEXT_DATA__ 파싱 실패, 정규식 폴백 시도: {e}")

    if not items:
        # 폴백: 페이지 본문 텍스트에서 "제목 날짜" 패턴과 /info/research/{id} 링크를 각각 추출해 순서대로 매칭
        links = re.findall(r'/info/research/(\d+)', res.text)
        items = [{"출처": "ACE ETF 리서치", "제목": None,
                   "링크": f"https://www.aceetf.co.kr/info/research/{i}"} for i in dict.fromkeys(links)]

    return items


if __name__ == "__main__":
    for item in scrape_ace_etf()[:5]:
        print(item)
