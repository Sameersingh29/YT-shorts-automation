"""
Check Google Cloud APIs — verifies that required APIs are enabled.
Run this locally to confirm your Google Cloud project is set up correctly.

Usage:
    python scripts/check_apis.py
"""

import sys
import json
import base64
import os

# Add parent to path so we can import src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def check_with_service_account():
    """Check APIs using service account credentials."""
    sa_json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_b64:
        print("⚠  GOOGLE_SERVICE_ACCOUNT_JSON not set. Skipping service account check.")
        return False

    try:
        sa_json = json.loads(base64.b64decode(sa_json_b64))
        project_id = sa_json.get("project_id", "unknown")
        print(f"✓ Service account loaded for project: {project_id}")
        print(f"  Email: {sa_json.get('client_email', 'N/A')}")
    except Exception as e:
        print(f"✗ Failed to parse service account JSON: {e}")
        return False

    # Test Google Drive API
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_info(
            sa_json, scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        drive = build("drive", "v3", credentials=creds)
        drive.about().get(fields="user").execute()
        print("✓ Google Drive API: ENABLED and accessible")
    except Exception as e:
        print(f"✗ Google Drive API: FAILED — {e}")
        print("  → Enable it at: https://console.cloud.google.com/apis/library/drive.googleapis.com")

    return True


def check_gemini():
    """Check Gemini API key."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("⚠  GEMINI_API_KEY not set.")
        print("  → Get a free key at: https://aistudio.google.com/app/apikey")
        return False

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content("Say 'API working' in exactly 2 words.")
        print(f"✓ Gemini API: WORKING (response: {response.text.strip()[:50]})")
        return True
    except Exception as e:
        print(f"✗ Gemini API: FAILED — {e}")
        return False


def check_youtube():
    """Check YouTube OAuth2 setup."""
    client_json = os.environ.get("YOUTUBE_CLIENT_SECRET_JSON", "")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

    if not client_json:
        print("⚠  YOUTUBE_CLIENT_SECRET_JSON not set.")
        print("  → Run: python scripts/setup_google_auth.py")
        return False

    try:
        config = json.loads(base64.b64decode(client_json))
        client_type = "installed" if "installed" in config else "web"
        print(f"✓ YouTube OAuth2 client loaded (type: {client_type})")
    except Exception as e:
        print(f"✗ Failed to parse YouTube client JSON: {e}")
        return False

    if not refresh_token:
        print("⚠  YOUTUBE_REFRESH_TOKEN not set.")
        print("  → Run: python scripts/setup_google_auth.py")
        return False

    try:
        from src.youtube_uploader import get_youtube_service
        service = get_youtube_service()
        # Try a simple API call
        response = service.channels().list(part="snippet", mine=True).execute()
        channels = response.get("items", [])
        if channels:
            name = channels[0]["snippet"]["title"]
            print(f"✓ YouTube API: WORKING (channel: {name})")
        else:
            print("✓ YouTube API: WORKING (no channel found)")
        return True
    except Exception as e:
        print(f"✗ YouTube API: FAILED — {e}")
        return False


def check_ffmpeg():
    """Check FFmpeg installation."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        print(f"✓ FFmpeg: INSTALLED ({version_line})")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("✗ FFmpeg: NOT FOUND")
        print("  → Install: https://ffmpeg.org/download.html")
        return False


def check_drive_folders():
    """Check Google Drive folder IDs are set."""
    source = os.environ.get("DRIVE_SOURCE_FOLDER_ID", "")
    queue = os.environ.get("DRIVE_QUEUE_FOLDER_ID", "")

    if source:
        print(f"✓ Source folder ID: {source}")
    else:
        print("⚠  DRIVE_SOURCE_FOLDER_ID not set")

    if queue:
        print(f"✓ Queue folder ID: {queue}")
    else:
        print("⚠  DRIVE_QUEUE_FOLDER_ID not set")

    return bool(source and queue)


def main():
    print("=" * 60)
    print("YT Shorts Automation — API & Dependency Check")
    print("=" * 60)
    print()

    results = {}

    print("── FFmpeg ──")
    results["ffmpeg"] = check_ffmpeg()
    print()

    print("── Google Drive ──")
    results["drive"] = check_with_service_account()
    print()

    print("── Drive Folders ──")
    results["folders"] = check_drive_folders()
    print()

    print("── Gemini AI ──")
    results["gemini"] = check_gemini()
    print()

    print("── YouTube ──")
    results["youtube"] = check_youtube()
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_ok = all(results.values())
    for name, ok in results.items():
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")

    if all_ok:
        print("\n🎉 All checks passed! You're ready to go.")
    else:
        print("\n⚠  Some checks failed. Fix the issues above before running.")
        print("\nSETUP GUIDE:")
        print("1. Create a Google Cloud service account and download the JSON key")
        print("2. Base64 encode it: base64 -i key.json | tr -d '\\n'")
        print("3. Set GOOGLE_SERVICE_ACCOUNT_JSON in your .env file")
        print("4. Get a Gemini API key from https://aistudio.google.com/app/apikey")
        print("5. Run: python scripts/setup_google_auth.py (for YouTube OAuth)")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
