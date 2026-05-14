"""
YouTube Uploader — uploads Shorts to YouTube with scheduling.
Uses OAuth2 with a stored refresh token for headless operation.
"""

import json
import base64
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.config import (
    YOUTUBE_CLIENT_SECRET_JSON,
    YOUTUBE_REFRESH_TOKEN,
    SCHEDULE_TIMES_IST,
    IST_UTC_OFFSET_HOURS,
    get_logger,
)

logger = get_logger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# YouTube Shorts category (22 = People & Blogs, good default for podcasts)
DEFAULT_CATEGORY_ID = "22"


def _get_credentials() -> Credentials:
    """Build OAuth2 credentials from stored client secret + refresh token."""
    if not YOUTUBE_CLIENT_SECRET_JSON:
        raise ValueError("YOUTUBE_CLIENT_SECRET_JSON env var is not set.")
    if not YOUTUBE_REFRESH_TOKEN:
        raise ValueError("YOUTUBE_REFRESH_TOKEN env var is not set.")

    client_config = json.loads(base64.b64decode(YOUTUBE_CLIENT_SECRET_JSON))

    # Handle both "installed" and "web" client types
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
        scopes=YOUTUBE_SCOPES,
    )

    # Refresh the access token
    creds.refresh(Request())
    logger.info("YouTube OAuth2 credentials refreshed successfully.")
    return creds


def get_youtube_service():
    """Return an authenticated YouTube API service."""
    creds = _get_credentials()
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=creds)


def get_next_schedule_time(slot: str = "auto") -> str:
    """
    Calculate the next scheduled publish time in ISO 8601 format.

    Args:
        slot: "morning" (9 AM IST), "evening" (9 PM IST), or "auto" (next available).

    Returns:
        ISO 8601 datetime string for YouTube publishAt.
    """
    ist = timezone(timedelta(hours=IST_UTC_OFFSET_HOURS))
    now_ist = datetime.now(ist)

    morning = now_ist.replace(hour=9, minute=0, second=0, microsecond=0)
    evening = now_ist.replace(hour=21, minute=0, second=0, microsecond=0)

    if slot == "morning":
        target = morning if now_ist < morning else morning + timedelta(days=1)
    elif slot == "evening":
        target = evening if now_ist < evening else evening + timedelta(days=1)
    else:
        # Auto: pick the next available slot
        if now_ist < morning:
            target = morning
        elif now_ist < evening:
            target = evening
        else:
            target = morning + timedelta(days=1)

    # Convert to UTC for YouTube API
    target_utc = target.astimezone(timezone.utc)
    return target_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = DEFAULT_CATEGORY_ID,
    schedule_time: str = None,
) -> str:
    """
    Upload a video to YouTube as a scheduled Short.

    Args:
        video_path: Path to the MP4 file.
        title: Video title.
        description: Video description.
        tags: List of tags.
        category_id: YouTube category ID.
        schedule_time: ISO 8601 publish time (if None, publishes immediately).

    Returns:
        The YouTube video ID.
    """
    service = get_youtube_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "selfDeclaredMadeForKids": False,
        },
    }

    if schedule_time:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = schedule_time
        logger.info(f"Scheduling video for {schedule_time}")
    else:
        body["status"]["privacyStatus"] = "public"

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    logger.info(f"Uploading '{title}' to YouTube...")

    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            logger.info(f"Upload progress: {pct}%")

    video_id = response["id"]
    logger.info(f"Upload complete! Video ID: {video_id}")
    logger.info(f"URL: https://youtube.com/shorts/{video_id}")

    return video_id


def set_thumbnail(video_id: str, thumbnail_path: Path) -> None:
    """Set a custom thumbnail for an uploaded video."""
    service = get_youtube_service()

    media = MediaFileUpload(
        str(thumbnail_path),
        mimetype="image/jpeg",
    )

    service.thumbnails().set(
        videoId=video_id,
        media_body=media,
    ).execute()

    logger.info(f"Custom thumbnail set for video {video_id}")


def get_video_stats(video_id: str) -> dict:
    """Fetch statistics for a video (views, likes, comments)."""
    service = get_youtube_service()

    response = service.videos().list(
        part="statistics",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if not items:
        return {"views": 0, "likes": 0, "comments": 0}

    stats = items[0].get("statistics", {})
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
    }
