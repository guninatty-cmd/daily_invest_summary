"""
키움증권 리서치 수집 (bbn.kiwoom.com 게시판 - koscom 위젯 아님, 인증 불필요)

핵심 발견 (2026-09-25):
www3.kiwoom.com/h/invest/research/... 는 koscom 보안 위젯(VestSign 암호화 등)으로 감싸여 있어
requests로는 접근 불가능하지만, 실제 리서치 원문은 bbn.kiwoom.com 이라는 별도 서브도메인의
평범한 게시판(HTML 서버렌더링)에 인증 없이 그대로 올라와 있다.

확인된 보드 목록 (VAnal{CODE}View 페이지가 곧 게시판, 페이지 최초 GET에 1페이지 결과가 이미 렌더링돼 있음):
  TP : 글로벌 ETF 투자전략   https://bbn.kiwoom.com/research/VAnalTPView
  CI : 기업/산업분석         https://bbn.kiwoom.com/research/VAnalCIView
  UD : 해외증시(미국 시황 등) https://bbn.kiwoom.com/research/VAnalUDView (www3에도 동일 코드로 존재)
필요시 다른 코드(예: 시장전략/투자전략 등)도 같은 패턴으로 존재할 가능성이 높음 - 사이트 내
"리서치" 메뉴를 한 번 더 순회해 VAnal????View 링크를 모으면 전체 카테고리를 확정할 수 있음.

각 게시글의 첨부 PDF는 별도 인증 없이 직접 다운로드 가능한 것으로 보이나(예: bbn.kiwoom.com/rfXXNNNN),
이 스크립트는 "새 글 감지"가 목적이므로 목록 페이지 파싱까지만 하고 첨부파일 다운로드는 하지 않는다.
"""
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

BOARDS = {
    "글로벌 ETF 투자전략": "https://bbn.kiwoom.com/research/VAnalTPView",
    "기업/산업분석": "https://bbn.kiwoom.com/research/VAnalCIView",
    "해외증시": "https://bbn.kiwoom.com/research/VAnalUDView",
}


def _parse_board(board_name: str, url: str) -> list[dict]:
    res = requests.get(url, headers=HEADERS, timeout=10)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    rows = soup.select("table tr")
    items = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        # 번호 컬럼이 숫자가 아니면 헤더 행이므로 skip
        first = tds[0].get_text(strip=True)
        if not first.isdigit():
            continue

        title_link = tr.select_one("a.link-title") or tr.find("a")
        title = title_link.get_text(strip=True) if title_link else tds[-5].get_text(strip=True)

        # 날짜는 YYYY.MM.DD 형태 셀에서 정규식으로 추출 (컬럼 수가 보드마다 다름 - 업종명 컬럼 유무 등)
        date_str = None
        for td in tds:
            text = td.get_text(strip=True)
            if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", text):
                date_str = text
                break

        analyst = None
        for td in tds:
            text = td.get_text(strip=True)
            if text and not text.isdigit() and "첨부" not in text and "스크랩" not in text \
                    and text != title and not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", text):
                analyst = text
                break

        items.append({
            "출처": f"키움증권 리서치 - {board_name}",
            "제목": title,
            "작성일": date_str,
            "작성자": analyst,
            "링크": url,  # 상세 개별 URL은 JS 클릭 기반이라 우선 보드 URL로 기록 (필요시 rSqno로 후속 확정)
        })
    return items


def scrape_kiwoom() -> list[dict]:
    all_items = []
    for name, url in BOARDS.items():
        try:
            all_items.extend(_parse_board(name, url))
        except Exception as e:
            print(f"⚠️ 키움증권[{name}] 수집 실패: {e}")
    return all_items


if __name__ == "__main__":
    for item in scrape_kiwoom()[:5]:
        print(item)
