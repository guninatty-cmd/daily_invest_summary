"""SOL ETF(신한자산운용) 인사이트 - JSON API 직접 호출 (2026-09-25 확인)"""
import requests

API_URL = "https://www.soletf.com/api/information/insight"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_sol_etf() -> list[dict]:
    params = {"keyword": "", "boardType": "report", "categoryType": ""}
    res = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
    res.raise_for_status()
    data = res.json()

    # 응답 최상위가 list이거나 {"list":[...]} / {"data":[...]} 형태일 수 있어 방어적으로 처리
    rows = data if isinstance(data, list) else data.get("list") or data.get("data") or []

    items = []
    for row in rows:
        serial_no = row.get("SERIAL_NO")
        # 실제 개별 글 상세 URL 패턴이 확인되지 않아, 목록 페이지 URL에 SERIAL_NO를 쿼리로
        # 붙여 항목별로 링크를 고유하게 만든다 (전부 같은 링크면 노션 업서트 단계에서
        # 첫 항목 이후로는 전부 "이미 존재함"으로 오인되어 스킵되는 문제가 있었음).
        link = (
            f"https://www.soletf.com/ko/information/insight?serial={serial_no}"
            if serial_no else "https://www.soletf.com/ko/information/insight"
        )
        items.append({
            "출처": "SOL ETF 인사이트",
            "제목": row.get("SUBJECT"),
            "작성일": row.get("REG_DATE"),
            "첨부파일": row.get("UPLOAD_FILE1"),
            "SERIAL_NO": serial_no,
            "링크": link,
        })
    return items


if __name__ == "__main__":
    for item in scrape_sol_etf()[:5]:
        print(item)
