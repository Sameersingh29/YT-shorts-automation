"""
Queue Manager — manages the clip queue stored in data/queue.json.
Tracks which clips are ready for upload, uploaded, or failed.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import DATA_DIR, get_logger

logger = get_logger(__name__)

QUEUE_FILE = DATA_DIR / "queue.json"
PROCESSED_FILE = DATA_DIR / "processed_videos.json"


def _read_json(path: Path) -> dict:
    """Read a JSON file, return empty structure if missing/corrupt."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Write data to a JSON file with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ─── Clip Queue ───────────────────────────────────────────


def get_queue() -> list[dict]:
    """Return the current clip queue."""
    data = _read_json(QUEUE_FILE)
    return data.get("clips", [])


def get_pending_clips() -> list[dict]:
    """Return only clips that haven't been uploaded yet."""
    return [c for c in get_queue() if c.get("status") == "pending"]


def get_queue_size() -> int:
    """Return the number of pending clips."""
    return len(get_pending_clips())


def add_clip_to_queue(clip_info: dict) -> None:
    """
    Add a processed clip to the upload queue.

    clip_info should contain:
        - clip_id: str (unique identifier)
        - source_video_id: str (Drive ID of source video)
        - source_video_name: str
        - clip_number: int
        - start_time: float
        - end_time: float
        - duration: float
        - drive_file_id: str (Drive ID of processed clip MP4)
        - thumbnail_drive_id: str
        - title: str
        - description: str
        - tags: list[str]
        - hashtags: list[str]
        - status: "pending"
        - created_at: str (ISO timestamp)
    """
    data = _read_json(QUEUE_FILE)
    clips = data.get("clips", [])

    clip_info.setdefault("status", "pending")
    clip_info.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    clips.append(clip_info)
    data["clips"] = clips
    _write_json(QUEUE_FILE, data)
    logger.info(f"Added clip '{clip_info.get('clip_id')}' to queue (total: {len(clips)})")


def get_next_clip() -> Optional[dict]:
    """Get the next pending clip from the queue (FIFO)."""
    pending = get_pending_clips()
    if not pending:
        logger.info("No pending clips in queue.")
        return None
    return pending[0]


def mark_clip_uploaded(clip_id: str, youtube_video_id: str) -> None:
    """Mark a clip as uploaded with the YouTube video ID."""
    data = _read_json(QUEUE_FILE)
    clips = data.get("clips", [])

    for clip in clips:
        if clip.get("clip_id") == clip_id:
            clip["status"] = "uploaded"
            clip["youtube_video_id"] = youtube_video_id
            clip["uploaded_at"] = datetime.now(timezone.utc).isoformat()
            break

    data["clips"] = clips
    _write_json(QUEUE_FILE, data)
    logger.info(f"Marked clip '{clip_id}' as uploaded (YT: {youtube_video_id})")


def mark_clip_failed(clip_id: str, error: str) -> None:
    """Mark a clip as failed with an error message."""
    data = _read_json(QUEUE_FILE)
    clips = data.get("clips", [])

    for clip in clips:
        if clip.get("clip_id") == clip_id:
            clip["status"] = "failed"
            clip["error"] = error
            clip["failed_at"] = datetime.now(timezone.utc).isoformat()
            break

    data["clips"] = clips
    _write_json(QUEUE_FILE, data)
    logger.warning(f"Marked clip '{clip_id}' as failed: {error}")


# ─── Processed Videos Tracker ─────────────────────────────


def get_processed_videos() -> list[str]:
    """Return list of Drive file IDs that have been processed."""
    data = _read_json(PROCESSED_FILE)
    return [v.get("drive_id") for v in data.get("videos", [])]


def mark_video_processed(drive_id: str, video_name: str, clips_generated: int) -> None:
    """Record that a source video has been fully processed."""
    data = _read_json(PROCESSED_FILE)
    videos = data.get("videos", [])

    videos.append({
        "drive_id": drive_id,
        "name": video_name,
        "clips_generated": clips_generated,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })

    data["videos"] = videos
    _write_json(PROCESSED_FILE, data)
    logger.info(f"Marked video '{video_name}' as processed ({clips_generated} clips)")


def is_video_processed(drive_id: str) -> bool:
    """Check if a video has already been processed."""
    return drive_id in get_processed_videos()
