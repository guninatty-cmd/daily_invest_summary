"""
텔레그램 메시지 / PDF 수집 (수집 구간은 common.get_window: 어제 07:00 ~ 오늘 07:00 KST)
"""
import os
import asyncio
import hashlib

from telethon import TelegramClient
from telethon.sessions import StringSession

from common import KST, get_window
from drive_upload import sanitize_filename


async def run_telegram_digest(download_dir: str = "downloads"):
    """반환: (messages: list[dict], pdf_paths: list[str])"""
    start, end = get_window()
    api_id = int(os.environ['TELEGRAM_API_ID'])
    api_hash = os.environ['TELEGRAM_API_HASH']
    session = os.environ['TELEGRAM_SESSION_STRING']

    messages, pdf_paths, seen_hashes = [], [], set()
    os.makedirs(download_dir, exist_ok=True)

    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    try:
        async for dialog in client.iter_dialogs():
            if not (dialog.is_channel or dialog.is_group):
                continue
            chat = dialog.name
            clean_chat = sanitize_filename(chat)
            async for message in client.iter_messages(dialog.id):
                msg_dt = message.date.astimezone(KST)
                if msg_dt < start:
                    break
                if msg_dt >= end:      # 구간 이후(07:00 이후) 메시지는 다음 날 구간으로 넘긴다
                    continue
                text = message.text or ""
                if text.strip():
                    messages.append({"시각": msg_dt.strftime('%Y-%m-%d %H:%M'), "채널": chat, "내용": text})

                if message.file and message.file.ext == '.pdf':
                    name = message.file.name or 'document.pdf'
                    filepath = os.path.join(download_dir, f"[{clean_chat}] {sanitize_filename(name)}")
                    try:
                        await message.download_media(file=filepath)
                        with open(filepath, 'rb') as fh:
                            h = hashlib.sha256(fh.read()).hexdigest()
                        if h in seen_hashes:      # 여러 채널에 재전달된 동일 PDF
                            os.remove(filepath)
                        else:
                            seen_hashes.add(h)
                            pdf_paths.append(filepath)
                        await asyncio.sleep(2)
                    except Exception as e:
                        print(f"⚠️ PDF 다운로드 실패 (건너뜀): {e}")
    finally:
        await client.disconnect()

    messages.reverse()   # 오래된 것 -> 최신 순
    return messages, pdf_paths
