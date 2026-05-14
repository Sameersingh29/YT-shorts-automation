"""
Upload Clip — Main entry point for the daily upload pipeline.

Picks the next pending clip from the queue, downloads it from Google Drive,
uploads it to YouTube with scheduling, and updates analytics.

Runs 2x daily via GitHub Actions cron (9 AM & 9 PM IST).

Usage:
    python upload_clip.py [--slot morning|evening|auto]
"""

import sys
import argparse
from pathlib import Path

from src.config import TEMP_DIR, get_logger
from src.drive_handler import download_file
from src.youtube_uploader import (
    upload_video,
    set_thumbnail,
    get_next_schedule_time,
)
from src.queue_manager import (
    get_next_clip,
    mark_clip_uploaded,
    mark_clip_failed,
    get_queue_size,
)
from src.analytics import record_upload

logger = get_logger("upload_clip")


def upload_next_clip(time_slot: str = "auto") -> bool:
    """
    Upload the next pending clip from the queue to YouTube.

    Args:
        time_slot: "morning" (9 AM IST), "evening" (9 PM IST), or "auto".

    Returns:
        True if upload was successful, False otherwise.
    """
    # Step 1: Get next clip from queue
    logger.info("=" * 60)
    logger.info("STEP 1: Getting next clip from queue")
    logger.info("=" * 60)

    clip = get_next_clip()
    if not clip:
        logger.info("No pending clips in queue. Nothing to upload.")
        return False

    clip_id = clip["clip_id"]
    logger.info(f"Next clip: {clip_id} — {clip.get('title', 'Untitled')}")
    logger.info(f"Queue remaining: {get_queue_size()} clips")

    try:
        # Step 2: Download clip and thumbnail from Google Drive
        logger.info("=" * 60)
        logger.info("STEP 2: Downloading clip from Google Drive")
        logger.info("=" * 60)

        clip_path = TEMP_DIR / f"upload_{clip_id}.mp4"
        download_file(clip["drive_file_id"], clip_path)

        thumb_path = TEMP_DIR / f"thumb_{clip_id}.jpg"
        if clip.get("thumbnail_drive_id"):
            download_file(clip["thumbnail_drive_id"], thumb_path)

        # Step 3: Calculate schedule time
        logger.info("=" * 60)
        logger.info("STEP 3: Scheduling upload")
        logger.info("=" * 60)

        schedule_time = get_next_schedule_time(time_slot)
        logger.info(f"Scheduled publish time: {schedule_time}")

        # Step 4: Upload to YouTube
        logger.info("=" * 60)
        logger.info("STEP 4: Uploading to YouTube")
        logger.info("=" * 60)

        video_id = upload_video(
            video_path=clip_path,
            title=clip.get("title", "Untitled Short"),
            description=clip.get("description", ""),
            tags=clip.get("tags", []),
            schedule_time=schedule_time,
        )

        # Step 5: Set custom thumbnail
        if thumb_path.exists():
            logger.info("Setting custom thumbnail...")
            try:
                set_thumbnail(video_id, thumb_path)
            except Exception as e:
                logger.warning(f"Failed to set thumbnail: {e}")

        # Step 6: Update queue and analytics
        logger.info("=" * 60)
        logger.info("STEP 6: Updating queue and analytics")
        logger.info("=" * 60)

        mark_clip_uploaded(clip_id, video_id)
        record_upload(
            clip_id=clip_id,
            youtube_video_id=video_id,
            title=clip.get("title", ""),
            source_video_name=clip.get("source_video_name", ""),
            clip_type=clip.get("clip_type", "mixed"),
            scheduled_time=schedule_time,
        )

        # Cleanup temp files
        for p in [clip_path, thumb_path]:
            if p.exists():
                p.unlink(missing_ok=True)

        logger.info("=" * 60)
        logger.info(f"SUCCESS! Uploaded '{clip.get('title')}'")
        logger.info(f"YouTube URL: https://youtube.com/shorts/{video_id}")
        logger.info(f"Scheduled for: {schedule_time}")
        logger.info(f"Remaining in queue: {get_queue_size()} clips")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"Upload failed for clip {clip_id}: {e}", exc_info=True)
        mark_clip_failed(clip_id, str(e))

        # Cleanup on failure
        for p in [
            TEMP_DIR / f"upload_{clip_id}.mp4",
            TEMP_DIR / f"thumb_{clip_id}.jpg",
        ]:
            if p.exists():
                p.unlink(missing_ok=True)

        return False


def main():
    parser = argparse.ArgumentParser(description="Upload next queued clip to YouTube")
    parser.add_argument(
        "--slot",
        choices=["morning", "evening", "auto"],
        default="auto",
        help="Time slot for scheduling (default: auto-detect next slot)",
    )
    args = parser.parse_args()

    success = upload_next_clip(time_slot=args.slot)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
