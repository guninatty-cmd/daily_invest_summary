# Daily Invest Digest (통합본)

`daily_invest_summary`(텔레그램+네이버) 와 `invest-today-digest`(사이트 45곳+유튜브) 를 하나로 합친 저장소.
**노션 업로드 없음.** 결과는 엑셀 + 후보목록(txt)이며 Claude가 이 파일을 읽어 데일리 리포트를 만든다.

## 한눈에
- 실행: GitHub Actions 매주 화~토 07:00 KST (`0 22 * * 1-5` UTC). 미국장 결과가 나오는 요일 기준. 월~금로 바꾸려면 `0 22 * * 0-4`.
- 수집 구간(전 수집기 공통): 어제 07:00 ~ 오늘 07:00 KST  → `common.py`의 `get_window()` 한 곳에서만 정의.
- 네이버: `scrapers/naver_news.py` 하나만 수집(6개 언론사 지면 + 글로벌경제 속보). 같은 기사는 링크/제목 정규화로 1건만 남김.
- 이전 실행에서 이미 본 항목은 `state/seen_items.json`(14일)으로 제외 → 날짜 표시 없는 사이트도 "신규만" 나옴.
- 같은 날짜 재실행(지연된 스케줄 등)은 `state/last_run.txt`로 자동 건너뜀. 강제 재실행은 Actions 수동 실행에서 `force_run=1`.
- 드라이브 업로드가 하나라도 실패하면 Actions 실행이 **빨간색(실패)** 으로 표시됨.

## 결과물 (드라이브 `{오늘}_주식리포트_모음/`)
| 파일 | 용도 |
|---|---|
| `00_후보목록.txt` | Claude가 **제일 먼저, 이것만** 읽는 압축 목록(후보=Y만, ID|분류힌트|출처|제목) |
| `{오늘}_투자데이터_통합.xlsx` | 00_안내 / 기사_리서치 / 텔레그램 / 유튜브 / PDF목록 / PDF정독본 / 주가 (후보·점수·분류힌트·제외사유 컬럼) |
| `{오늘}_유튜브_자막.xlsx` | PC에서 추출한 자막 전문 (제목으로 고른 영상만 읽음) |
| `[채널] 파일명.pdf` | 텔레그램 PDF 원본 (상위 10건 + 일일시황 PDF는 본문이 `PDF정독본` 시트에 추출됨) |

## 유튜브 자막 (PC 자동 실행)
유튜브는 클라우드(GitHub) IP의 자막 요청을 자주 차단한다. 그래서 목록(제목/링크)은 Actions가, 자막은 PC가 맡는다.
1. 이 저장소를 PC에 받고 `pip install -r requirements.txt` (Deno 권장: `winget install DenoLand.Deno`)
2. (선택) 유튜브 로그인 `cookies.txt`를 같은 폴더에 둠 / `run_local_youtube.bat`에 GAS_WEBHOOK_URL 등 입력하면 드라이브 자동 업로드
3. 작업 스케줄러: `schtasks /Create /SC DAILY /ST 07:10 /TN "InvestYoutube" /TR "<경로>\run_local_youtube.bat"`
   (PC가 꺼져 있었다면 작업 설정에서 "예약된 시작 시간을 놓친 경우 가능한 한 빨리 작업 시작" 체크)
시험 삼아 Actions에서 시도하려면 워크플로의 `ACTIONS_TRANSCRIPTS`를 `'1'`로 (연속 3회 차단되면 자동 중단).

## 필요한 GitHub Secrets (기존과 동일, 추가 없음)
TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING, GAS_WEBHOOK_URL, GOOGLE_DRIVE_PARENT_FOLDER_ID
(NOTION_*, YOUTUBE_COOKIES 는 더 이상 필요 없음)

## 설정 파일
- `watchlist.txt` 관심 종목(점수 가산) / `scrapers/youtube.py` 의 `CHANNELS` 유튜브 22채널 / `triage.py` 키워드·분류 힌트
