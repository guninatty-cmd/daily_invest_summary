import os
import re
import datetime
import asyncio
import base64
import requests
from datetime import timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
import pandas as pd

API_ID = int(os.environ['TELEGRAM_API_ID'])
API_HASH = os.environ['TELEGRAM_API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION_STRING']
GAS_URL = os.environ['GAS_WEBHOOK_URL']
PARENT_FOLDER_ID = os.environ['GOOGLE_DRIVE_PARENT_FOLDER_ID']

KST = timezone(timedelta(hours=9))

def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", str(name))
    return name.strip()

def upload_to_drive_via_gas(filepath, folder_name):
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        encoded_data = base64.b64encode(f.read()).decode('utf-8')
        
    payload = {
        "parentFolderId": PARENT_FOLDER_ID,
        "folderName": folder_name,
        "filename": filename,
        "fileData": encoded_data
    }
    
    try:
        response = requests.post(GAS_URL, json=payload)
        if "Success" in response.text:
            print(f"✅ 구글 드라이브 업로드 성공: {filename}")
        else:
            print(f"❌ 구글 드라이브 업로드 실패 ({filename}): {response.text}")
    except Exception as e:
        print(f"❌ 업로드 에러 ({filename}): {e}")

async def main():
    now_utc = datetime.datetime.now(timezone.utc)
    twenty_four_hours_ago = now_utc - datetime.timedelta(hours=24)
    
    messages_data = []
    upload_file_paths = []
    
    os.makedirs('downloads', exist_ok=True)
    
    print("텔레그램 연결 중...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    
    print("지난 24시간 동안의 대화 및 PDF 수집 시작...")
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            chat_name = dialog.name
            clean_chat_name = sanitize_filename(chat_name)
            
            async for message in client.iter_messages(dialog.id):
                if message.date < twenty_four_hours_ago:
                    break
                
                msg_time_kst = message.date.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')
                msg_text = message.text or ""
                
                if msg_text.strip():
                    messages_data.append({
                        '발송 시간': msg_time_kst,
                        '채널명': chat_name,
                        '내용': msg_text
                    })
                
                if message.file and message.file.ext == '.pdf':
                    original_filename = message.file.name or 'document.pdf'
                    safe_filename = f"[{clean_chat_name}] {sanitize_filename(original_filename)}"
                    filepath = os.path.join('downloads', safe_filename)
                    
                    try:
                        await message.download_media(file=filepath)
                        upload_file_paths.append(filepath)
                        await asyncio.sleep(2)
                    except Exception as e:
                        print(f"⚠️ PDF 다운로드 실패 (건너뜀): {e}")
                        continue

    if messages_data:
        df = pd.DataFrame(messages_data)
        df = df.iloc[::-1].reset_index(drop=True)
        
        excel_path = 'downloads/01_오늘의_대화기록.xlsx'
        df.to_excel(excel_path, index=False)
        upload_file_paths.insert(0, excel_path)
        
        prompt_path = 'downloads/00_AI_요약용_복붙텍스트.txt'
        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write("너는 주식 투자 전문 애널리스트야. 아래 제공되는 텍스트는 지난 24시간 동안 여러 투자 채널에서 수집된 대화 내역이야.\n")
            f.write("데이터의 양이 방대하니, 단순 인사말이나 광고는 철저히 무시하고 '시장을 관통하는 핵심 투자 정보'만 요약해줘.\n\n")
            f.write("--- 데이터 시작 ---\n\n")
            for _, row in df.iterrows():
                f.write(f"[{row['채널명']} | {row['발송 시간']}]\n{row['내용']}\n")
                f.write("-" * 40 + "\n\n")
        upload_file_paths.insert(0, prompt_path)

    if upload_file_paths:
        today_str = datetime.datetime.now(KST).strftime('%Y-%m-%d')
        folder_name = f"{today_str}_주식리포트_모음"
        
        print(f"\n구글 드라이브(가벼운 백도어 방식) 업로드 시작... 대상 폴더: {folder_name}")
        for path in upload_file_paths:
            upload_to_drive_via_gas(path, folder_name)
    else:
        print("지난 24시간 동안 수집된 데이터가 없습니다.")

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
