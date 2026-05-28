"""
Process Video — Main entry point for the video processing pipeline.

Downloads a source video from Google Drive, transcribes it, selects best clips
using AI, processes each clip (split layout + captions), generates thumbnails
and metadata, then uploads processed clips to the Drive queue.

Usage:
    python process_video.py [--folder-id FOLDER_ID] [--video-id VIDEO_ID]
"""

import sys
import json
import argparse
import uuid
from pathlib import Path
from datetime import datetime, timezone

from src.config import (
    TEMP_DIR,
    DRIVE_SOURCE_FOLDER_ID,
    DRIVE_QUEUE_FOLDER_ID,
    get_logger,
)
from src.drive_handler import (
    list_video_files,
    download_file,
    upload_file,
    create_folder,
)
from src.transcriber import transcribe
from src.clip_selector import select_clips
from src.video_processor import process_all_clips, extract_frame
from src.thumbnail_generator import generate_thumbnail
from src.metadata_generator import generate_metadata
from src.queue_manager import (
    add_clip_to_queue,
    is_video_processed,
    mark_video_processed,
    get_queue_size,
)

logger = get_logger("process_video")


def process_video(video_drive_id: str = None, source_folder_id: str = None) -> int:
    """
    Main processing pipeline.

    Args:
        video_drive_id: Specific Drive file ID to process. If None, picks
                        the first unprocessed video from the source folder.
        source_folder_id: Google Drive folder ID with source videos.

    Returns:
        Number of clips successfully processed and queued.
    """
    source_folder = source_folder_id or DRIVE_SOURCE_FOLDER_ID

    # Step 1: Find a video to process
    logger.info("=" * 60)
    logger.info("STEP 1: Finding source video")
    logger.info("=" * 60)

    if video_drive_id:
        video_name = f"video_{video_drive_id[:8]}.mp4"
        logger.info(f"Processing specific video: {video_drive_id}")
    else:
        videos = list_video_files(source_folder)
        if not videos:
            logger.error("No videos found in source folder!")
            return 0

        # Find first unprocessed video
        video_info = None
        for v in videos:
            if not is_video_processed(v["id"]):
                video_info = v
                break

        if not video_info:
            logger.info("All videos in source folder have been processed.")
            return 0

        video_drive_id = video_info["id"]
        video_name = video_info["name"]
        logger.info(f"Selected: {video_name} (ID: {video_drive_id})")

    # Step 2: Download video
    logger.info("=" * 60)
    logger.info("STEP 2: Downloading video from Google Drive")
    logger.info("=" * 60)

    local_video = TEMP_DIR / video_name
    download_file(video_drive_id, local_video)

    # Step 3: Transcribe
    logger.info("=" * 60)
    logger.info("STEP 3: Transcribing video with Whisper")
    logger.info("=" * 60)

    transcript = transcribe(local_video)
    logger.info(f"Transcript: {len(transcript.segments)} segments, {transcript.duration:.0f}s")

    # Build timestamped transcript for clip selection
    timestamped_text = ""
    for seg in transcript.segments:
        mins = int(seg.start // 60)
        secs = int(seg.start % 60)
        timestamped_text += f"[{mins:02d}:{secs:02d}] {seg.text}\n"

    # Step 4: AI Clip Selection
    logger.info("=" * 60)
    logger.info("STEP 4: Selecting best clips with Gemini AI")
    logger.info("=" * 60)

    clips = select_clips(timestamped_text, transcript.duration)
    logger.info(f"AI selected {len(clips)} clips")

    # Step 5: Process clips (FFmpeg)
    logger.info("=" * 60)
    logger.info("STEP 5: Processing clips (split layout + captions)")
    logger.info("=" * 60)

    clips_dir = TEMP_DIR / "clips"
    processed_paths = process_all_clips(local_video, clips, transcript, clips_dir)

    # Step 6: Generate thumbnails and metadata for each clip
    logger.info("=" * 60)
    logger.info("STEP 6: Generating thumbnails and metadata")
    logger.info("=" * 60)

    thumbs_dir = TEMP_DIR / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    successful_clips = 0

    for i, (clip, clip_path) in enumerate(zip(clips, processed_paths)):
        try:
            # Generate thumbnail
            thumb_path = thumbs_dir / f"thumb_{clip.clip_number:02d}.jpg"
            mid_time = (clip.end_time - clip.start_time) / 3  # 1/3 into clip
            generate_thumbnail(
                video_path=clip_path,
                timestamp=mid_time,
                title=clip.suggested_title,
                output_path=thumb_path,
                hook=clip.hook,
            )

            # Generate metadata
            transcript_snippet = transcript.get_text_in_range(
                clip.start_time, clip.end_time
            )
            meta = generate_metadata(
                clip_summary=clip.summary,
                hook=clip.hook,
                clip_type=clip.clip_type,
                suggested_title=clip.suggested_title,
                transcript_snippet=transcript_snippet,
            )

            # Step 7: Upload processed clip + thumbnail to Drive queue
            logger.info(f"Uploading clip #{clip.clip_number} to Drive queue...")
            clip_drive_id = upload_file(clip_path, DRIVE_QUEUE_FOLDER_ID)
            thumb_drive_id = upload_file(thumb_path, DRIVE_QUEUE_FOLDER_ID)

            # Save metadata as JSON and upload
            meta_path = TEMP_DIR / f"meta_{clip.clip_number:02d}.json"
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            meta_drive_id = upload_file(meta_path, DRIVE_QUEUE_FOLDER_ID)

            # Add to queue
            clip_id = f"{video_drive_id[:8]}_{clip.clip_number:02d}_{uuid.uuid4().hex[:6]}"
            add_clip_to_queue({
                "clip_id": clip_id,
                "source_video_id": video_drive_id,
                "source_video_name": video_name,
                "clip_number": clip.clip_number,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "duration": clip.duration,
                "clip_type": clip.clip_type,
                "viral_score": clip.viral_score,
                "info_score": clip.info_score,
                "drive_file_id": clip_drive_id,
                "thumbnail_drive_id": thumb_drive_id,
                "metadata_drive_id": meta_drive_id,
                "title": meta["title"],
                "description": meta["description"],
                "tags": meta["tags"],
                "hashtags": meta["hashtags"],
                "hook": clip.hook,
                "summary": clip.summary,
                "status": "pending",
            })

            successful_clips += 1
            logger.info(f"✓ Clip #{clip.clip_number} queued: {meta['title']}")

        except Exception as e:
            logger.error(f"✗ Failed to process clip #{clip.clip_number}: {e}")
            continue

    # Only mark as processed if at least one clip succeeded.
    # If all clips failed (e.g. API/upload errors), leave the video unprocessed
    # so the next run can retry rather than silently skipping it.
    if successful_clips > 0:
        mark_video_processed(video_drive_id, video_name, successful_clips)
    else:
        logger.warning(
            "No clips were successfully queued — NOT marking video as processed "
            "so it can be retried on the next run."
        )

    # Cleanup temp files
    logger.info("Cleaning up temporary files...")
    import shutil
    for d in [clips_dir, thumbs_dir]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    if local_video.exists():
        local_video.unlink(missing_ok=True)

    logger.info("=" * 60)
    logger.info(f"DONE! {successful_clips}/{len(clips)} clips processed and queued.")
    logger.info(f"Queue size: {get_queue_size()} pending clips")
    logger.info("=" * 60)

    return successful_clips


def main():
    parser = argparse.ArgumentParser(description="Process a podcast video into YouTube Shorts")
    parser.add_argument("--folder-id", help="Google Drive source folder ID")
    parser.add_argument("--video-id", help="Specific Google Drive video file ID to process")
    args = parser.parse_args()

    try:
        count = process_video(
            video_drive_id=args.video_id,
            source_folder_id=args.folder_id,
        )
        sys.exit(0 if count > 0 else 1)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
