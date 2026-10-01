"""
유안타증권(myasset.com) 리서치 수집

핵심 발견 (2026-09-25):
처음에 추측했던 파라미터(cno=RS0301 등)는 전부 "오늘 0건"만 반환했다. 홈페이지의 리서치
메인(`/myasset/research/RS_0000000_M.cmd`)에서 실제 메뉴 링크를 모두 추출해 보니 진짜
파라미터 체계는 cd007(대분류)+cd008(소분류) 조합이었다:

  목록: https://www.myasset.com/myasset/research/rs_list/rs_list.cmd?cd006=&cd007={대}&cd008={소}
  상세: https://www.myasset.com/myasset/research/rs_list/rs_view.cmd?cd006=&cd007={대}&cd008={소}&SEQ={글번호}

글 목록 HTML의 각 행에 `<a ... cmd-type="view" data-seq="207573">제목</a>` 형태로 글번호(SEQ)가
바로 노출돼 있어서 상세 링크를 그대로 재구성할 수 있다 (글로벌 투자전략 보드에서
data-seq="207573" 확인, 총 72건 정상 표시 — "0건" 문제 해결됨).
"""
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BASE = "https://www.myasset.com/myasset/research/rs_list/rs_list.cmd"
VIEW_BASE = "https://www.myasset.com/myasset/research/rs_list/rs_view.cmd"

# (표시명, cd007, cd008) - 필요하면 같은 패턴으로 더 추가 가능 (예: 채권분석 RF09, ESG RB13 등)
BOARDS = [
    ("한국 투자전략", "RB30", "RB30A"),
    ("글로벌 투자전략", "RB30", "RB30B"),
    ("경제분석", "RB30", "RB30C"),
    ("기업분석", "RE01", ""),
    ("산업분석", "RE02", ""),
    ("Asia Daily", "NR03", "NR03D"),
]


def _parse_board(board_name: str, cd007: str, cd008: str) -> list[dict]:
    params = {"cd006": "", "cd007": cd007, "cd008": cd008}
    res = requests.get(BASE, params=params, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for a in soup.select("a[data-seq][cmd-type='view']"):
        seq = a.get("data-seq")
        if not seq or not seq.isdigit():
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        link = f"{VIEW_BASE}?cd006=&cd007={cd007}&cd008={cd008}&SEQ={seq}"
        items.append({
            "출처": f"유안타증권 리서치 - {board_name}",
            "제목": title,
            "링크": link,
        })
    return items


def scrape_myasset() -> list[dict]:
    all_items = []
    for name, cd007, cd008 in BOARDS:
        try:
            all_items.extend(_parse_board(name, cd007, cd008))
        except Exception as e:
            print(f"⚠️ 유안타증권[{name}] 수집 실패: {e}")
    return all_items


if __name__ == "__main__":
    for item in scrape_myasset()[:5]:
        print(item)
