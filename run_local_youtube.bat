@echo off
REM PC에서 매일 아침 유튜브 자막을 추출하는 스크립트 (Windows 작업 스케줄러가 호출)
REM 사전 준비: Python 설치, 이 폴더에서 pip install -r requirements.txt
REM 선택: cookies.txt(유튜브 로그인 쿠키)를 이 폴더에 두면 차단이 줄어듭니다. Deno 설치 권장: winget install DenoLand.Deno
cd /d "%~dp0"
set YTDLP_COOKIES_FILE=%~dp0cookies.txt
REM 구글 드라이브 자동 업로드를 쓰려면 아래 두 줄의 값을 채우세요 (GitHub Secret과 같은 값)
REM set GAS_WEBHOOK_URL=
REM set GOOGLE_DRIVE_PARENT_FOLDER_ID=
python main.py --youtube-only
