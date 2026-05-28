"""
Google Drive Handler — download source videos & upload processed clips.

Authentication strategy:
  - Downloads: service account (shared folder access, no quota needed for reads)
  - Uploads:   YouTube OAuth2 credentials (real user account with Drive storage quota)

Service accounts cannot upload to regular "My Drive" folders because they have
no storage quota of their own (Google limitation). Reusing the existing YouTube
OAuth credentials avoids needing a separate auth flow.
"""

import io
import json
import base64
import tempfile
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from src.config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
    YOUTUBE_CLIENT_SECRET_JSON,
    YOUTUBE_REFRESH_TOKEN,
    DRIVE_SOURCE_FOLDER_ID,
    DRIVE_QUEUE_FOLDER_ID,
    get_logger,
)

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_credentials():
    """Build credentials from base64-encoded service account JSON."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON env var is not set. "
            "Run scripts/setup_google_auth.py first."
        )
    sa_json = json.loads(base64.b64decode(GOOGLE_SERVICE_ACCOUNT_JSON))
    return service_account.Credentials.from_service_account_info(sa_json, scopes=SCOPES)


def get_drive_service():
    """Return an authenticated Google Drive API service (service account — for reads)."""
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


def _get_oauth_credentials() -> Credentials:
    """
    Build OAuth2 credentials from stored YouTube client secret + refresh token.
    These are real user credentials with Drive storage quota, used for uploads.
    """
    if not YOUTUBE_CLIENT_SECRET_JSON:
        raise ValueError(
            "YOUTUBE_CLIENT_SECRET_JSON env var is not set. "
            "Run scripts/setup_youtube_auth.py first."
        )
    if not YOUTUBE_REFRESH_TOKEN:
        raise ValueError(
            "YOUTUBE_REFRESH_TOKEN env var is not set. "
            "Run scripts/setup_youtube_auth.py first."
        )

    client_config = json.loads(base64.b64decode(YOUTUBE_CLIENT_SECRET_JSON))
    if "installed" in client_config:
        client_info = client_config["installed"]
    elif "web" in client_config:
        client_info = client_config["web"]
    else:
        client_info = client_config

    creds = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri=client_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_info["client_id"],
        client_secret=client_info["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    creds.refresh(Request())
    return creds


def get_drive_service_oauth():
    """Return a Drive API service authenticated as the real user (for uploads)."""
    creds = _get_oauth_credentials()
    return build("drive", "v3", credentials=creds)


def list_video_files(folder_id: Optional[str] = None) -> list[dict]:
    """
    List video files in a Google Drive folder.
    Returns list of dicts with 'id', 'name', 'mimeType', 'size'.
    """
    folder = folder_id or DRIVE_SOURCE_FOLDER_ID
    if not folder:
        raise ValueError("No folder ID provided and DRIVE_SOURCE_FOLDER_ID is not set.")

    service = get_drive_service()
    query = (
        f"'{folder}' in parents and "
        f"mimeType contains 'video/' and "
        f"trashed = false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, createdTime)",
        orderBy="createdTime desc",
        pageSize=50,
    ).execute()

    files = results.get("files", [])
    logger.info(f"Found {len(files)} video(s) in folder {folder}")
    return files


def download_file(file_id: str, destination: Path) -> Path:
    """
    Download a file from Google Drive to a local path.
    Shows progress for large files.
    """
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)

    destination.parent.mkdir(parents=True, exist_ok=True)

    with open(destination, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"Download progress: {pct}%")

    logger.info(f"Downloaded file {file_id} → {destination}")
    return destination


def upload_file(
    local_path: Path,
    folder_id: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    """
    Upload a file to a Google Drive folder using OAuth2 user credentials.
    Service accounts cannot upload to regular My Drive folders (no storage quota),
    so we use the YouTube OAuth credentials which have real Drive quota.
    Returns the uploaded file's Drive ID.
    """
    folder = folder_id or DRIVE_QUEUE_FOLDER_ID
    if not folder:
        raise ValueError("No folder ID provided and DRIVE_QUEUE_FOLDER_ID is not set.")

    if mime_type is None:
        suffix = local_path.suffix.lower()
        mime_map = {
            ".mp4": "video/mp4",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".json": "application/json",
        }
        mime_type = mime_map.get(suffix, "application/octet-stream")

    # Use OAuth credentials (real user account) — service accounts lack Drive quota
    service = get_drive_service_oauth()
    file_metadata = {
        "name": local_path.name,
        "parents": [folder],
    }
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    file_id = file.get("id")
    logger.info(f"Uploaded {local_path.name} → Drive ID: {file_id}")
    return file_id


def create_folder(name: str, parent_folder_id: Optional[str] = None) -> str:
    """Create a folder in Google Drive using OAuth credentials. Returns the folder ID."""
    # Use OAuth credentials so the folder is created in the user's Drive
    service = get_drive_service_oauth()
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder.get("id")
    logger.info(f"Created folder '{name}' → Drive ID: {folder_id}")
    return folder_id


def delete_file(file_id: str) -> None:
    """Delete a file from Google Drive (move to trash)."""
    service = get_drive_service()
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
    logger.info(f"Trashed file {file_id}")
