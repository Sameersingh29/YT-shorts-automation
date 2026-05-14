"""
Analytics Tracker — records upload performance data.
Stored in data/analytics.json for the GitHub Pages dashboard.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR, get_logger

logger = get_logger(__name__)

ANALYTICS_FILE = DATA_DIR / "analytics.json"


def _read_analytics() -> dict:
    """Read analytics data from file."""
    try:
        with open(ANALYTICS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"uploads": [], "last_updated": ""}


def _write_analytics(data: dict) -> None:
    """Write analytics data to file."""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def record_upload(
    clip_id: str,
    youtube_video_id: str,
    title: str,
    source_video_name: str,
    clip_type: str,
    scheduled_time: str,
) -> None:
    """Record a successful upload for analytics."""
    data = _read_analytics()
    uploads = data.get("uploads", [])

    uploads.append({
        "clip_id": clip_id,
        "youtube_video_id": youtube_video_id,
        "title": title,
        "source_video": source_video_name,
        "clip_type": clip_type,
        "scheduled_time": scheduled_time,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "views": 0,
        "likes": 0,
        "comments": 0,
    })

    data["uploads"] = uploads
    _write_analytics(data)
    logger.info(f"Recorded upload analytics for '{title}'")


def get_upload_stats() -> dict:
    """Get summary statistics of all uploads."""
    data = _read_analytics()
    uploads = data.get("uploads", [])

    total = len(uploads)
    total_views = sum(u.get("views", 0) for u in uploads)
    total_likes = sum(u.get("likes", 0) for u in uploads)

    # Uploads by type
    viral_count = sum(1 for u in uploads if u.get("clip_type") == "viral")
    info_count = sum(1 for u in uploads if u.get("clip_type") == "informative")
    mixed_count = sum(1 for u in uploads if u.get("clip_type") == "mixed")

    return {
        "total_uploads": total,
        "total_views": total_views,
        "total_likes": total_likes,
        "avg_views": total_views / max(total, 1),
        "by_type": {
            "viral": viral_count,
            "informative": info_count,
            "mixed": mixed_count,
        },
        "recent_uploads": uploads[-10:] if uploads else [],
    }


def update_video_stats(youtube_video_id: str, views: int, likes: int, comments: int) -> None:
    """Update stats for a specific uploaded video (called by analytics refresh)."""
    data = _read_analytics()
    uploads = data.get("uploads", [])

    for upload in uploads:
        if upload.get("youtube_video_id") == youtube_video_id:
            upload["views"] = views
            upload["likes"] = likes
            upload["comments"] = comments
            upload["stats_updated_at"] = datetime.now(timezone.utc).isoformat()
            break

    data["uploads"] = uploads
    _write_analytics(data)


def get_all_uploads() -> list[dict]:
    """Return all upload records."""
    data = _read_analytics()
    return data.get("uploads", [])
