"""
미래에셋증권(securities.miraeasset.com) 리서치 수집

⚠️ 이용정책 참고: 이 페이지에는 "리서치 보고서를 다운로드 또는 자동 대량 수집하여 무단 전재
및 상업적 재배포하는 행위는 저작권법 위반"이라는 안내 문구가 명시돼 있다. 이 스크래퍼는
개인적으로 신규 리포트 발행 여부만 감지(제목/날짜/링크 수집)하는 용도로, 재배포하지 않고
개인 확인용으로만 사용한다는 전제로 작성됨 (사용자 확인, 2026-09-26).

목록: https://securities.miraeasset.com/bbs/board/message/list.do?categoryId={카테고리ID}
  카테고리ID: 기업분석=1800, 산업분석=1525, 투자전략=1527, 글로벌 ETF=1526

각 행은 `<a href="javascript:view('{messageId}','{boardId}')">제목</a>` 형태라 상세페이지
직링크는 없지만(JS 네비게이션), 첨부 PDF는 같은 행의
`<a href="javascript:downConfirm('https://securities.miraeasset.com/bbs/download/{fileId}.pdf?attachmentId={fileId}', ...)">`
문자열 안에 완전한 URL이 그대로 들어있고, 세션 없이 바로 GET 가능 (브라우저로 그래서 "링크" 필드는 이 PDF 직링크를 사용한다.
"""
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

LIST_URL = "https://securities.miraeasset.com/bbs/board/message/list.do"

# (표시명, categoryId)
BOARDS = [
    ("기업분석", "1800"),
    ("산업분석", "1525"),
    ("투자전략", "1527"),
    ("글로벌 ETF", "1526"),
]

PDF_URL_RE = re.compile(r"downConfirm\('([^']+\.pdf\?attachmentId=\d+)'")


def _parse_board(board_name: str, category_id: str) -> list[dict]:
    res = requests.get(LIST_URL, params={"categoryId": category_id}, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for row in soup.select("table tr"):
        subject_a = row.select_one("div.subject a")
        if not subject_a:
            continue
        title = subject_a.get_text(strip=True)
        if not title:
            continue

        date_td = row.find("td")
        date_str = date_td.get_text(strip=True) if date_td else None

        pdf_a = row.select_one("a[href*='downConfirm']")
        link = None
        if pdf_a and pdf_a.get("href"):
            m = PDF_URL_RE.search(pdf_a["href"])
            if m:
                link = m.group(1)
        if not link:
            # 첨부 PDF가 없는 글(공지 등)은 목록 페이지로 대체
            link = f"{LIST_URL}?categoryId={category_id}"

        items.append({
            "출처": f"미래에셋증권 리서치 - {board_name}",
            "제목": title,
            "작성일": date_str,
            "링크": link,
        })
    return items


def scrape_miraeasset() -> list[dict]:
    all_items = []
    for name, category_id in BOARDS:
        try:
            all_items.extend(_parse_board(name, category_id))
        except Exception as e:
            print(f"⚠️ 미래에셋증권[{name}] 수집 실패: {e}")
    return all_items


if __name__ == "__main__":
    for item in scrape_miraeasset()[:5]:
        print(item)
