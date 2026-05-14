"""
Google Drive Handler — download source videos & upload processed clips.
Uses a service account for authentication.
"""

import io
import json
import base64
import tempfile
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from src.config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
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
    """Return an authenticated Google Drive API service."""
    creds = _get_credentials()
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
    Upload a file to a Google Drive folder.
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

    service = get_drive_service()
    file_metadata = {
        "name": local_path.name,
        "parents": [folder],
    }
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
    ).execute()

    file_id = file.get("id")
    logger.info(f"Uploaded {local_path.name} → Drive ID: {file_id}")
    return file_id


def create_folder(name: str, parent_folder_id: Optional[str] = None) -> str:
    """Create a folder in Google Drive. Returns the folder ID."""
    service = get_drive_service()
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
