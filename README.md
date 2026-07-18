# Daily Invest Digest (네이버 뉴스 + 텔레그램 통합 파이프라인)

매일 07:00 KST에 자동 실행되어 네이버 뉴스 + 텔레그램 대화/PDF를 수집하고,
하나의 엑셀(단일 시트, `구분` 컬럼)로 병합한 뒤 구글 드라이브에 업로드합니다.
콜랩은 더 이상 사용하지 않습니다.

## 파일 구성 (구조를 최대한 단순화함 - 폴더 없이 평평하게 배치)

- main.py            : 전체 파이프라인 실행
- naver_news.py       : 네이버 뉴스 수집 (Selenium)
- telegram_digest.py  : 텔레그램 메시지/PDF 수집 (Telethon)
- drive_upload.py     : 구글 드라이브 업로드 (기존 GAS 웹훅 재사용)
- requirements.txt
- .github/workflows/daily_invest_digest.yml : 매일 07:00 KST 실행 워크플로우

## 기존 저장소(daily_invest_summary)에 적용하는 방법

1. 기존 저장소의 main.py를 삭제하고, 위 파일들(main.py, naver_news.py,
   telegram_digest.py, drive_upload.py, requirements.txt)을 저장소 루트에 복사합니다.
2. 기존 .github/workflows/telegram_digest.yml을 삭제하고
   .github/workflows/daily_invest_digest.yml로 교체합니다.
3. GitHub Secrets는 기존과 동일하게 그대로 사용합니다(추가/변경 없음):
   TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING,
   GAS_WEBHOOK_URL, GOOGLE_DRIVE_PARENT_FOLDER_ID
4. 커밋 후 Actions 탭에서 수동 실행(workflow_dispatch)으로 테스트해보세요.

## 결과물

- {오늘날짜}_투자데이터_통합.xlsx : 연번, 구분(뉴스/텔레그램), 날짜, 시간, 출처/채널, 제목/내용, 원문 링크
- 00_AI_요약용_복붙텍스트.txt
- PDF 원본 파일들

모두 구글 드라이브의 {오늘날짜}_주식리포트_모음 폴더에 업로드됩니다.
