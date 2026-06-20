"""
구글 드라이브 업로드 유틸리티 (기존 main.py의 GAS 웹훅 방식 재사용)
"""
import os
import re
import base64
import requests

GAS_URL = os.environ.get('GAS_WEBHOOK_URL')
PARENT_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_PARENT_FOLDER_ID')


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", str(name))
    return name.strip()


def upload_to_drive_via_gas(filepath: str, folder_name: str) -> bool:
    """파일 1개를 GAS 웹훅을 통해 지정한 날짜별 폴더로 업로드한다."""
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
        response = requests.post(GAS_URL, json=payload, timeout=60)
        if "Success" in response.text:
            print(f"✅ 구글 드라이브 업로드 성공: {filename}")
            return True
        else:
            print(f"❌ 구글 드라이브 업로드 실패 ({filename}): {response.text}")
            return False
    except Exception as e:
        print(f"❌ 업로드 에러 ({filename}): {e}")
        return False
