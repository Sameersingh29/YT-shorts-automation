"""
Video Processor — FFmpeg pipeline to create 9:16 Shorts from 16:9 source.
Split layout with centered video + blurred background + ASS captions.
"""

import subprocess
from pathlib import Path

from src.config import (
    OUTPUT_WIDTH,
    OUTPUT_HEIGHT,
    VIDEO_HEIGHT,
    TEMP_DIR,
    FONTS_DIR,
    get_logger,
)
from src.transcriber import Transcript, WordTimestamp
from src.caption_generator import generate_ass_captions

logger = get_logger(__name__)


def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds using FFprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr}")

    import json
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def process_clip(
    source_video: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    words: list[WordTimestamp],
    extra_keywords: list[str] = None,
    clip_number: int = 0,
) -> Path:
    """
    Process a single clip from source video into a 9:16 Short.

    Pipeline:
        1. Cut segment from source video
        2. Create blurred background (zoomed + gaussian blur)
        3. Overlay original video centered vertically
        4. Burn in Hormozi-style ASS captions

    Args:
        source_video: Path to the full source video.
        output_path: Where to save the processed clip.
        start_time: Clip start time in seconds.
        end_time: Clip end time in seconds.
        words: Word-level timestamps for this clip's segment.
        extra_keywords: Additional keywords to highlight.
        clip_number: Clip number for logging.

    Returns:
        Path to the processed clip MP4.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = end_time - start_time

    logger.info(
        f"Processing clip #{clip_number}: "
        f"{start_time:.1f}s → {end_time:.1f}s ({duration:.1f}s)"
    )

    # Step 1: Generate ASS captions
    ass_path = TEMP_DIR / f"clip_{clip_number}_captions.ass"
    generate_ass_captions(
        words=words,
        output_path=ass_path,
        clip_start_offset=start_time,
        extra_keywords=extra_keywords,
    )

    # Step 2: Build FFmpeg filter complex
    # The filter creates:
    #   - A blurred, zoomed background filling 1080x1920
    #   - The original 16:9 video scaled to 1080x608, centered vertically
    #   - ASS subtitles burned on top

    # Escape special characters in path for FFmpeg filter
    ass_path_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

    # Check if custom font directory has fonts
    fontsdir_arg = ""
    if FONTS_DIR.exists() and any(FONTS_DIR.glob("*.ttf")):
        fonts_escaped = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
        fontsdir_arg = f":fontsdir='{fonts_escaped}'"

    filter_complex = (
        # Split input into two streams
        f"[0:v]split=2[main_in][bg_in];"
        # Background: scale to fill 1080x1920 (zoom + crop), then blur heavily
        f"[bg_in]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
        f"boxblur=25:10[bg];"
        # Main video: scale to 1080 width, maintain 16:9 aspect
        f"[main_in]scale={OUTPUT_WIDTH}:{VIDEO_HEIGHT}[main];"
        # Overlay main video centered on blurred background
        f"[bg][main]overlay=(W-w)/2:(H-h)/2[composed];"
        # Burn in ASS subtitles
        f"[composed]ass='{ass_path_escaped}'{fontsdir_arg}[out]"
    )

    # Step 3: Run FFmpeg
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", str(source_video),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",               # Include audio if present
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-shortest",
        "-movflags", "+faststart",     # Web-optimized MP4
        str(output_path),
    ]

    logger.info(f"Running FFmpeg for clip #{clip_number}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        logger.error(f"FFmpeg failed for clip #{clip_number}: {result.stderr[-1000:]}")
        raise RuntimeError(f"FFmpeg processing failed: {result.stderr[-500:]}")

    file_size_mb = output_path.stat().st_size / 1e6
    logger.info(
        f"Clip #{clip_number} processed successfully: "
        f"{output_path.name} ({file_size_mb:.1f} MB)"
    )

    # Cleanup temp ASS file
    try:
        ass_path.unlink()
    except OSError:
        pass

    return output_path


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """
    Extract a single frame from a video at a given timestamp.

    Args:
        video_path: Path to the video file.
        timestamp: Time in seconds to extract the frame.
        output_path: Where to save the frame image (JPG/PNG).

    Returns:
        Path to the extracted frame.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),   # -i BEFORE -ss: accurate seek (slower but no corrupt frames)
        "-ss", str(timestamp),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    # Validate the output — ffmpeg can exit 0 with a corrupt/incomplete frame
    if not output_path.exists() or output_path.stat().st_size < 512:
        raise RuntimeError(
            f"Frame extraction produced invalid file "
            f"({output_path.stat().st_size if output_path.exists() else 0} bytes)"
        )

    logger.info(f"Extracted frame at {timestamp:.1f}s → {output_path.name}")
    return output_path


def process_all_clips(
    source_video: Path,
    clips: list,
    transcript: Transcript,
    output_dir: Path,
) -> list[tuple]:
    """
    Process all selected clips from a source video.

    Args:
        source_video: Path to the full source video.
        clips: List of ClipCandidate objects.
        transcript: Full Transcript with word timestamps.
        output_dir: Directory to save processed clips.

    Returns:
        List of (ClipCandidate, Path) tuples for successfully processed clips.
        Clips that fail are excluded — so iterate over the returned pairs directly
        rather than zipping with the original clips list (which would misalign indices).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    processed = []  # list of (clip, output_path) tuples

    for clip in clips:
        # Get word timestamps for this clip's time range
        words = transcript.get_words_in_range(clip.start_time, clip.end_time)

        if not words:
            logger.warning(
                f"No word timestamps found for clip #{clip.clip_number} "
                f"({clip.start_time:.1f}s - {clip.end_time:.1f}s), skipping."
            )
            continue

        output_path = output_dir / f"clip_{clip.clip_number:02d}.mp4"

        try:
            result = process_clip(
                source_video=source_video,
                output_path=output_path,
                start_time=clip.start_time,
                end_time=clip.end_time,
                words=words,
                extra_keywords=clip.key_words,
                clip_number=clip.clip_number,
            )
            processed.append((clip, result))
        except Exception as e:
            logger.error(f"Failed to process clip #{clip.clip_number}: {e}")
            continue

    logger.info(f"Processed {len(processed)}/{len(clips)} clips successfully")
    return processed
