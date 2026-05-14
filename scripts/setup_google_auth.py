"""
Google Auth Setup — interactive script to set up OAuth2 for YouTube API.

This script:
1. Guides you through creating OAuth2 credentials in Google Cloud Console
2. Runs the OAuth2 flow to get a refresh token
3. Outputs the values to add to your .env file

Usage:
    python scripts/setup_google_auth.py

Prerequisites:
    - Google Cloud project with YouTube Data API v3 enabled
    - OAuth2 Client ID (Desktop app type) downloaded as JSON
"""

import sys
import os
import json
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def setup_youtube_oauth():
    """Interactive setup for YouTube OAuth2 credentials."""
    print("=" * 60)
    print("YouTube OAuth2 Setup")
    print("=" * 60)
    print()
    print("This script will help you get a refresh token for YouTube API.")
    print()
    print("PREREQUISITES:")
    print("1. Go to https://console.cloud.google.com/apis/credentials")
    print(f"   (Project: {os.environ.get('GOOGLE_PROJECT_ID', 'yt-automation-496118')})")
    print("2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'")
    print("3. Application type: 'Desktop app'")
    print("4. Download the JSON file")
    print()
    print("Also make sure these APIs are ENABLED:")
    print("  - YouTube Data API v3:")
    print("    https://console.cloud.google.com/apis/library/youtube.googleapis.com")
    print("  - Google Drive API:")
    print("    https://console.cloud.google.com/apis/library/drive.googleapis.com")
    print()

    # Get the client secret JSON file
    json_path = input("Enter path to downloaded OAuth client JSON file: ").strip().strip('"')

    if not os.path.exists(json_path):
        print(f"✗ File not found: {json_path}")
        return

    with open(json_path, "r") as f:
        client_config = json.load(f)

    # Base64 encode the client secret
    client_json_b64 = base64.b64encode(json.dumps(client_config).encode()).decode()

    print(f"\n✓ Client config loaded")

    # Run OAuth2 flow
    print("\nOpening browser for authorization...")
    print("(Allow access to your YouTube channel when prompted)\n")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
            ],
        )
        credentials = flow.run_local_server(port=8080, prompt="consent")

        refresh_token = credentials.refresh_token

        if not refresh_token:
            print("✗ No refresh token received. Try again with prompt='consent'.")
            return

        print("\n✓ Authorization successful!")
        print()
        print("=" * 60)
        print("ADD THESE TO YOUR .env FILE:")
        print("=" * 60)
        print()
        print(f"YOUTUBE_CLIENT_SECRET_JSON={client_json_b64}")
        print()
        print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")
        print()
        print("=" * 60)
        print()
        print("For GitHub Actions, add these as repository secrets:")
        print("  Settings → Secrets → Actions → New repository secret")
        print()

        # Optionally write to .env
        write = input("Write these to .env file automatically? (y/n): ").strip().lower()
        if write == "y":
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                ".env",
            )
            with open(env_path, "a") as f:
                f.write(f"\nYOUTUBE_CLIENT_SECRET_JSON={client_json_b64}\n")
                f.write(f"YOUTUBE_REFRESH_TOKEN={refresh_token}\n")
            print(f"✓ Written to {env_path}")

    except ImportError:
        print("✗ google-auth-oauthlib not installed.")
        print("  Run: pip install google-auth-oauthlib")
    except Exception as e:
        print(f"✗ OAuth flow failed: {e}")


def setup_service_account():
    """Interactive setup for Google Drive service account."""
    print()
    print("=" * 60)
    print("Google Drive Service Account Setup")
    print("=" * 60)
    print()
    print("STEPS:")
    print("1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts")
    print("2. Click '+ CREATE SERVICE ACCOUNT'")
    print("3. Name: 'yt-shorts-automation'")
    print("4. Grant role: 'Editor' (or at minimum 'Storage Object Admin')")
    print("5. Click on the service account → Keys → Add Key → JSON")
    print("6. Download the JSON key file")
    print()

    json_path = input("Enter path to service account JSON key file (or 'skip'): ").strip().strip('"')

    if json_path.lower() == "skip":
        return

    if not os.path.exists(json_path):
        print(f"✗ File not found: {json_path}")
        return

    with open(json_path, "r") as f:
        sa_json = json.load(f)

    sa_b64 = base64.b64encode(json.dumps(sa_json).encode()).decode()

    print(f"\n✓ Service account: {sa_json.get('client_email')}")
    print(f"  Project: {sa_json.get('project_id')}")
    print()
    print("ADD THIS TO YOUR .env FILE:")
    print(f"GOOGLE_SERVICE_ACCOUNT_JSON={sa_b64}")
    print()
    print("IMPORTANT: Share your Google Drive folders with the service account email:")
    print(f"  {sa_json.get('client_email')}")
    print()

    write = input("Write to .env file automatically? (y/n): ").strip().lower()
    if write == "y":
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env",
        )
        with open(env_path, "a") as f:
            f.write(f"\nGOOGLE_SERVICE_ACCOUNT_JSON={sa_b64}\n")
        print(f"✓ Written to {env_path}")


def setup_drive_folders():
    """Help set up Google Drive folder IDs."""
    print()
    print("=" * 60)
    print("Google Drive Folder Setup")
    print("=" * 60)
    print()
    print("You need two folders in Google Drive:")
    print("1. SOURCE folder — where you put long podcast videos")
    print("2. QUEUE folder — where processed clips are stored before upload")
    print()
    print("To get a folder ID:")
    print("  Open the folder in Google Drive → copy the ID from the URL")
    print("  https://drive.google.com/drive/folders/FOLDER_ID_HERE")
    print()

    source_id = input("Source folder ID (or 'skip'): ").strip()
    queue_id = input("Queue folder ID (or 'skip'): ").strip()

    env_lines = []
    if source_id and source_id != "skip":
        env_lines.append(f"DRIVE_SOURCE_FOLDER_ID={source_id}")
    if queue_id and queue_id != "skip":
        env_lines.append(f"DRIVE_QUEUE_FOLDER_ID={queue_id}")

    if env_lines:
        write = input("Write to .env file? (y/n): ").strip().lower()
        if write == "y":
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                ".env",
            )
            with open(env_path, "a") as f:
                for line in env_lines:
                    f.write(f"\n{line}")
            print(f"✓ Written to {env_path}")


def main():
    print("=" * 60)
    print("YT Shorts Automation — Full Setup Wizard")
    print("=" * 60)
    print()
    print("This wizard will help you set up all required credentials.")
    print("You can run individual sections or all of them.")
    print()
    print("1. Service Account (for Google Drive)")
    print("2. YouTube OAuth2 (for video uploads)")
    print("3. Drive Folders (source & queue)")
    print("4. All of the above")
    print()

    choice = input("Choose (1/2/3/4): ").strip()

    if choice in ("1", "4"):
        setup_service_account()
    if choice in ("2", "4"):
        setup_youtube_oauth()
    if choice in ("3", "4"):
        setup_drive_folders()

    print()
    print("Done! Run 'python scripts/check_apis.py' to verify your setup.")


if __name__ == "__main__":
    main()
