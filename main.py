"""
통합 투자 데이터 자동화 파이프라인
1) 네이버 뉴스(6대 경제지 당일 지면기사 + 글로벌경제 속보 전날치) 수집
2) 텔레그램 대화(전날 24시간) + PDF(전날 하루치) 수집
3) 위 두 결과를 하나의 엑셀(단일 시트, '구분' 컬럼으로 구분)로 병합
4) 엑셀 + AI 요약용 텍스트 + PDF 전체를 같은 날짜 폴더로 구글 드라이브 업로드

매일 11:00 KST(=02:00 UTC)에 GitHub Actions로 실행되는 것을 전제로 한다.
"""
import os
import asyncio
import datetime
from datetime import timezone, timedelta

import pandas as pd

from naver_news import scrape_naver_news
from telegram_digest import run_telegram_digest
from drive_upload import upload_to_drive_via_gas

KST = timezone(timedelta(hours=9))
DOWNLOAD_DIR = "downloads"


def build_unified_dataframe(df_news: pd.DataFrame, df_telegram: pd.DataFrame) -> pd.DataFrame:
    """뉴스 + 텔레그램 결과를 단일 시트용 공통 스키마로 병합한다."""
    rows = []

    for _, r in df_news.iterrows():
        rows.append({
            "구분": "뉴스",
            "날짜": r.get("기사 등록일", ""),
            "시간": "",
            "출처/채널": r.get("출처", ""),
            "제목/내용": r.get("기사 제목", ""),
            "원문 링크": r.get("원문 링크", ""),
        })

    for _, r in df_telegram.iterrows():
        sent_at = str(r.get("발송 시간", ""))
        date_part, _, time_part = sent_at.partition(" ")
        rows.append({
            "구분": "텔레그램",
            "날짜": date_part,
            "시간": time_part,
            "출처/채널": r.get("채널명", ""),
            "제목/내용": r.get("내용", ""),
            "원문 링크": "",
        })

    if not rows:
        return pd.DataFrame(columns=["연번", "구분", "날짜", "시간", "출처/채널", "제목/내용", "원문 링크"])

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["날짜", "시간"], kind="stable").reset_index(drop=True)
    df.insert(0, "연번", range(1, len(df) + 1))
    return df


def write_ai_summary_text(filepath: str, df_news: pd.DataFrame, df_telegram: pd.DataFrame):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("너는 주식 투자 전문 애널리스트야. 아래 제공되는 텍스트는 지난 24시간 동안 수집된 "
                "경제 뉴스와 여러 투자 채널 대화 내역이야.\n")
        f.write("데이터의 양이 방대하니, 단순 인사말이나 광고는 철저히 무시하고 "
                "'시장을 관통하는 핵심 투자 정보'만 요약해줘.\n\n")

        f.write("--- [네이버 뉴스] ---\n\n")
        for _, row in df_news.iterrows():
            f.write(f"[{row['출처']} | {row['기사 등록일']}] {row['기사 제목']}\n{row['원문 링크']}\n\n")

        f.write("\n--- [텔레그램 대화] ---\n\n")
        for _, row in df_telegram.iterrows():
            f.write(f"[{row['채널명']} | {row['발송 시간']}]\n{row['내용']}\n")
            f.write("-" * 40 + "\n\n")


def main():
    now_kst = datetime.datetime.now(KST)
    today_str = now_kst.strftime("%Y-%m-%d")
    yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_param = (now_kst - timedelta(days=1)).strftime("%Y%m%d")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print(f"📅 실행 기준 시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   - 네이버 지면기사 기준일: {today_str} / 글로벌경제 속보 기준일: {yesterday_str}")
    print(f"   - 텔레그램 수집 범위: 최근 24시간\n")

    print("=== [1/3] 네이버 뉴스 수집 시작 ===")
    df_news = scrape_naver_news(today_str=today_str, yesterday_str=yesterday_str, yesterday_param=yesterday_param)
    print(f"   ✔️ 뉴스 {len(df_news)}건 수집 완료\n")

    print("=== [2/3] 텔레그램 메시지 및 PDF 수집 시작 ===")
    df_telegram, pdf_paths = asyncio.run(run_telegram_digest(download_dir=DOWNLOAD_DIR))
    print(f"   ✔️ 메시지 {len(df_telegram)}건 / PDF {len(pdf_paths)}건 수집 완료\n")

    print("=== [3/3] 엑셀 병합 및 구글 드라이브 업로드 ===")
    unified_df = build_unified_dataframe(df_news, df_telegram)

    excel_path = os.path.join(DOWNLOAD_DIR, f"{today_str}_투자데이터_통합.xlsx")
    unified_df.to_excel(excel_path, index=False, engine='openpyxl')
    print(f"   ✔️ 엑셀 생성 완료: {excel_path} (총 {len(unified_df)}행)")

    summary_path = os.path.join(DOWNLOAD_DIR, "00_AI_요약용_복붙텍스트.txt")
    write_ai_summary_text(summary_path, df_news, df_telegram)

    upload_file_paths = [summary_path, excel_path] + pdf_paths

    folder_name = f"{today_str}_주식리포트_모음"
    print(f"\n구글 드라이브 업로드 시작... 대상 폴더: {folder_name}")
    for path in upload_file_paths:
        upload_to_drive_via_gas(path, folder_name)


if __name__ == "__main__":
    main()
