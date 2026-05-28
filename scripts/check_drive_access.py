"""
Quick script to show which Google account the stored OAuth token belongs to,
and whether it can see the queue Drive folder.
"""
import sys
import os
# Add project root to path (this script lives in scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from dotenv import load_dotenv
load_dotenv()

import json, base64
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from src.config import YOUTUBE_CLIENT_SECRET_JSON, YOUTUBE_REFRESH_TOKEN, DRIVE_QUEUE_FOLDER_ID

# Build OAuth creds
client_config = json.loads(base64.b64decode(YOUTUBE_CLIENT_SECRET_JSON))
client_info = client_config.get("installed") or client_config.get("web") or client_config

creds = Credentials(
    token=None,
    refresh_token=YOUTUBE_REFRESH_TOKEN,
    token_uri=client_info.get("token_uri", "https://oauth2.googleapis.com/token"),
    client_id=client_info["client_id"],
    client_secret=client_info["client_secret"],
    scopes=[
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/drive",
    ],
)
creds.refresh(Request())
print("[OK] OAuth token refreshed")

# Get email from token metadata if possible
try:
    import urllib.request, json as _json
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/tokeninfo",
        headers={"Authorization": f"Bearer {creds.token}"}
    )
    with urllib.request.urlopen(req) as resp:
        info = _json.loads(resp.read())
    print(f"  Authenticated as: {info.get('email', 'unknown')} (sub: {info.get('sub','')})")
except Exception as e:
    print(f"  (Could not fetch email: {e})")

# Try to access the queue folder
drive = build("drive", "v3", credentials=creds)
print(f"\nChecking access to queue folder: {DRIVE_QUEUE_FOLDER_ID}")
try:
    folder = drive.files().get(
        fileId=DRIVE_QUEUE_FOLDER_ID,
        fields="id,name,owners",
        supportsAllDrives=True,
    ).execute()
    print(f"[OK] Queue folder accessible: '{folder.get('name')}'")
    owners = folder.get("owners", [])
    for o in owners:
        print(f"  Owned by: {o.get('emailAddress')}")
except Exception as e:
    print(f"[FAIL] Cannot access queue folder: {e}")
    print(f"\n  -> Share folder ID {DRIVE_QUEUE_FOLDER_ID} (as Editor) in Google Drive")
    print(f"     with the email shown above (the OAuth account).")


