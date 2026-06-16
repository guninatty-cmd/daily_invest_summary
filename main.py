import os
import re
import json
import datetime
from datetime import timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. 깃허브 Secrets 환경 변수 로드
API_ID = int(os.environ['TELEGRAM_API_ID'])
API_HASH = os.environ['TELEGRAM_API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION_STRING']

# 2. 한국 시간(KST) 설정
KST = timezone(timedelta(hours=9))

def sanitize_filename(name):
    """
    파일명에 사용할 수 없는 특수문자 제거 및 공백 정리
    에러를 방지하고 아이패드에서 깔끔하게 보이도록 정제합니다.
    """
    name = re.sub(r'[\\/*?:"<>|]', "", str(name))
    return name.strip()

async def main():
    now_utc = datetime.datetime.now(timezone.utc)
    twenty_four_hours_ago = now_utc - datetime.timedelta(hours=24)
    
    messages_data = []
    upload_file_paths = []
    
    os.makedirs('downloads', exist_ok=True)
    
    print("텔레그램 연결 중...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    print("지난 24시간 동안의 대화 및 PDF 일괄 수집 시작...")
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            chat_name = dialog.name
            clean_chat_name = sanitize_filename(chat_name)
            
            async for message in client.iter_messages(dialog.id):
                # 24시간이 지난 메시지는 탐색 중단
                if message.date < twenty_four_hours_ago:
                    break
                
                msg_time_kst = message.date.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
                msg_text = message.text or ""
                
                # [데이터 수집] 텍스트가 있는 경우
                if msg_text.strip():
                    messages_data.append({
                        '발송 시간': msg_time_kst,
                        '채널명': chat_name,
                        '내용': msg_text
                    })
                
                # [데이터 수집] PDF 파일이 첨부된 경우
                if message.file and message.file.ext == '.pdf':
                    original_filename = message.file.name or 'document.pdf'
                    
                    # PDF 파일명 자동화: "[채널명] 원래파일명.pdf" 구조로 직관성 극대화
                    safe_filename = f"[{clean_chat_name}] {sanitize_filename(original_filename)}"
                    filepath = os.path.join('downloads', safe_filename)
                    
                    print(f"PDF 다운로드 중: {safe_filename}")
                    await message.download_media(file=filepath)
                    upload_file_paths.append(filepath)

    await client.disconnect()

    # 3. 엑셀 정제 및 AI 복붙용 텍스트 생성
    if messages_data:
        df = pd.DataFrame(messages_data)
        # 시간순(과거->최신)으로 정렬하여 AI가 시간 흐름을 읽을 수 있게 함
        df = df.iloc[::-1].reset_index(drop=True)
        
        # [결과물 1] 엑셀 백업본 저장
        excel_path = 'downloads/01_오늘의_대화기록_전체본.xlsx'
        df.to_excel(excel_path, index=False)
        upload_file_paths.append(excel_path)
        
        # [결과물 2] AI 프롬프트 일체형 텍스트 저장
        prompt_path = 'downloads/00_AI_요약용_복붙텍스트.txt'
        with open(prompt_path, 'w', encoding='utf-8') as f:
            # AI에게 역할과 지시사항 부여
            f.write("너는 주식 투자 전문 애널리스트야. 아래 제공되는 텍스트는 지난 24시간 동안 여러 투자 채널에서 수집된 대화 내역이야.\n")
            f.write("데이터의 양이 방대하니, 단순 인사말이나 광고는 철저히 무시하고 '시장을 관통하는 핵심 투자 정보'만 아래 포맷으로 요약해줘.\n\n")
            f.write("1. 거시 경제 및 증시 시황 (금리, 환율, 지수 등)\n")
            f.write("2. 오늘 가장 뜨거웠던 주도 섹터 및 테마\n")
            f.write("3. 주목해야 할 개별 종목 호재/악재\n")
            f.write("4. 내일 장 대응을 위한 체크리스트\n\n")
            f.write("--- 데이터 시작 ---\n\n")
            
            for _, row in df.iterrows():
                # 출처와 시간을 명확히 구분하여 AI 할루시네이션(거짓 정보) 방지
                f.write(f"[{row['채널명']} | {row['발송 시간']}]\n{row['내용']}\n")
                f.write("-" * 40 + "\n\n")
                
        upload_file_paths.append(prompt_path)

    # 4. 구글 드라이브 업로드
    if upload_file_paths:
        today_str = datetime.datetime.now(KST).strftime('%Y-%m-%d')
        folder_name = f"{today_str}_주식리포트_모음"
        upload_to_google_drive(folder_name, upload_file_paths)
    else:
        print("지난 24시간 동안 수집된 데이터나 PDF가 없습니다.")

def upload_to_google_drive(folder_name, file_paths):
    print("\n구글 드라이브 업로드 시작...")
    creds_json = os.environ['GOOGLE_DRIVE_CREDENTIALS']
    creds_dict = json.loads(creds_json)
    
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)
    parent_id = os.environ.get('GOOGLE_DRIVE_PARENT_FOLDER_ID')
    
    # 오늘 날짜의 메인 폴더 생성
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        folder_metadata['parents'] = [parent_id]
        
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    folder_id = folder.get('id')
    print(f"새 폴더 생성 완료: {folder_name}")
    
    # 수집된 모든 파일 순차 업로드
    for path in file_paths:
        filename = os.path.basename(path)
        media = MediaFileUpload(path, resumable=True)
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        try:
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"✅ 업로드 성공: {filename}")
        except Exception as e:
            print(f"❌ 업로드 실패 ({filename}): {e}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
