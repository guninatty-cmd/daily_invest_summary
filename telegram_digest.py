"""
텔레그램 메시지 / PDF 수집 모듈
"""
import os
import hashlib
import datetime
from datetime import timezone, timedelta

import pandas as pd
from telethon import TelegramClient
from telethon.sessions import StringSession

from drive_upload import sanitize_filename

API_ID = int(os.environ['TELEGRAM_API_ID'])
API_HASH = os.environ['TELEGRAM_API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION_STRING']

KST = timezone(timedelta(hours=9))


async def run_telegram_digest(download_dir: str = "downloads"):
    """
    전날 19:00 ~ 당일 07:00(KST) 동안의 텔레그램 대화 + PDF를 수집한다.
    반환값: (messages_df, pdf_filepaths)
    """
    now_kst = datetime.datetime.now(KST)
    window_end_kst = now_kst.replace(hour=7, minute=0, second=0, microsecond=0)
    if now_kst < window_end_kst:
        window_end_kst -= datetime.timedelta(days=1)
    window_start_kst = window_end_kst - datetime.timedelta(hours=12)

    messages_data = []
    pdf_filepaths = []
    seen_hashes = set()  # content-hash dedup: same PDF re-shared across channels

    os.makedirs(download_dir, exist_ok=True)

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
                        '내용': msg_text,
                    })

                if message.file and message.file.ext == '.pdf':
                    original_filename = message.file.name or 'document.pdf'
                    safe_filename = f"[{clean_chat_name}] {sanitize_filename(original_filename)}"
                    filepath = os.path.join(download_dir, safe_filename)

                    try:
                        await message.download_media(file=filepath)

                        # Content-hash dedup: the same report is often forwarded
                        # into multiple channels/groups under a different filename.
                        # Without this check, both copies got summarized twice
                        # downstream. Hash the actual bytes, not the filename.
                        with open(filepath, 'rb') as fh:
                            file_hash = hashlib.sha256(fh.read()).hexdigest()

                        if file_hash in seen_hashes:
                            print(f"⏭️  중복 PDF 건너뜀 (동일 내용, 다른 채널/파일명): {safe_filename}")
                            os.remove(filepath)
                        else:
                            seen_hashes.add(file_hash)
                            pdf_filepaths.append(filepath)

                        await __import__("asyncio").sleep(2)
                    except Exception as e:
                        print(f"⚠️ PDF 다운로드 실패 (건너뜀): {e}")
                        continue

    await client.disconnect()

    if messages_data:
        df = pd.DataFrame(messages_data)
        df = df.iloc[::-1].reset_index(drop=True)
    else:
        df = pd.DataFrame(columns=['발송 시간', '채널명', '내용'])

    return df, pdf_filepaths
