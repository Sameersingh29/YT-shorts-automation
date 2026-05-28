"""
Clip Selector — uses Gemini AI to identify the best moments from a transcript.
Picks a mix of viral/controversial and informative/valuable segments.
"""

import json
import re
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
    CLIPS_PER_VIDEO,
    PODCAST_TOPICS,
    get_logger,
)

logger = get_logger(__name__)


@dataclass
class ClipCandidate:
    """A candidate clip identified by AI."""
    clip_number: int
    start_time: float      # seconds
    end_time: float        # seconds
    duration: float        # seconds
    clip_type: str         # "viral", "informative", or "mixed"
    viral_score: int       # 1-10
    info_score: int        # 1-10
    hook: str              # First few attention-grabbing words
    summary: str           # Brief description
    key_words: list[str]   # Words to highlight in captions
    suggested_title: str   # AI-generated title for this Short


def _parse_timestamp(ts: str) -> float:
    """Convert 'HH:MM:SS.mmm' or 'MM:SS.mmm' to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def _build_prompt(transcript_text: str, video_duration: float) -> str:
    """Build the clip selection prompt for Gemini."""
    topics = ", ".join(PODCAST_TOPICS)
    duration_min = int(video_duration // 60)

    return f"""You are an expert YouTube Shorts content strategist specializing in viral podcast clips.

TASK: Analyze this podcast transcript ({duration_min} minutes long) and identify exactly {CLIPS_PER_VIDEO} segments that would make the BEST YouTube Shorts clips.

CLIP REQUIREMENTS:
- Each clip must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds long
- Clips must NOT overlap with each other
- Each clip must be a self-contained moment (makes sense without context)
- Start each clip at a natural beginning of a thought/statement
- End each clip at a natural conclusion or powerful punchline

SELECTION CRITERIA (pick a MIX of both):
1. VIRAL moments (5 clips): Hot takes, controversial opinions, surprising revelations, emotional peaks, funny moments, quotable statements, "did he really just say that?" moments
2. INFORMATIVE moments (5 clips): Key insights, actionable advice, powerful lessons, unique perspectives, motivational statements, life-changing ideas

PODCAST TOPICS: {topics}

TRANSCRIPT:
{transcript_text}

RESPOND WITH ONLY a JSON array of exactly {CLIPS_PER_VIDEO} objects. No markdown, no explanation, just the JSON:
[
  {{
    "clip_number": 1,
    "start_time": "HH:MM:SS.000",
    "end_time": "HH:MM:SS.000",
    "duration_seconds": 35,
    "type": "viral",
    "viral_score": 9,
    "info_score": 5,
    "hook": "First 5-8 words that grab attention",
    "summary": "Brief 1-line description of the moment",
    "key_words": ["word1", "word2", "word3"],
    "suggested_title": "Catchy YouTube Shorts title with emoji (max 80 chars)"
  }}
]

Sort by overall quality score (viral_score + info_score) in DESCENDING order.
Ensure timestamps are accurate and within the video duration of {duration_min} minutes."""


def select_clips(transcript_text: str, video_duration: float) -> list[ClipCandidate]:
    """
    Use Gemini AI to select the best clip candidates from a transcript.

    Args:
        transcript_text: Full transcript text with timestamps.
        video_duration: Total video duration in seconds.

    Returns:
        List of ClipCandidate objects sorted by quality score.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY env var is not set.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = _build_prompt(transcript_text, video_duration)

    logger.info(f"Sending transcript to Gemini for clip selection ({len(transcript_text)} chars)...")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )

    # Parse JSON from response
    raw_text = response.text.strip()

    # Strip markdown code fences if present (```json ... ``` or ``` ... ```)
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
    if fence_match:
        raw_text = fence_match.group(1).strip()

    # Try to extract JSON array from the response
    json_match = re.search(r'\[', raw_text)
    if not json_match:
        logger.error(f"Failed to parse JSON from Gemini response: {raw_text[:500]}")
        raise ValueError("Gemini response did not contain a valid JSON array.")

    # Extract from first '[' to end; handle truncated responses by trimming to last complete object
    json_str = raw_text[json_match.start():]
    try:
        clips_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Full JSON parse failed ({e}), attempting partial recovery...")
        # Find the last complete object ending with '}' before any truncation
        last_brace = json_str.rfind('},')
        if last_brace == -1:
            last_brace = json_str.rfind('}')
        if last_brace != -1:
            partial = json_str[:last_brace + 1].rstrip(',') + ']'
            try:
                clips_data = json.loads(partial)
                logger.info(f"Partial recovery succeeded: recovered {len(clips_data)} clips")
            except json.JSONDecodeError as e2:
                logger.error(f"Partial JSON recovery also failed: {e2}\nRaw: {raw_text[:500]}")
                raise ValueError("Gemini response did not contain a valid JSON array.") from e2
        else:
            logger.error(f"JSON parse error: {e}\nRaw: {raw_text[:500]}")
            raise ValueError("Gemini response did not contain a valid JSON array.") from e

    # Convert to ClipCandidate objects
    candidates = []
    for clip in clips_data:
        try:
            start = _parse_timestamp(str(clip["start_time"]))
            end = _parse_timestamp(str(clip["end_time"]))
            duration = end - start

            # Validate duration
            if duration < MIN_CLIP_DURATION - 5 or duration > MAX_CLIP_DURATION + 10:
                logger.warning(
                    f"Clip {clip.get('clip_number')} has duration {duration:.1f}s "
                    f"(expected {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION}s), adjusting..."
                )
                if duration < MIN_CLIP_DURATION:
                    end = start + MIN_CLIP_DURATION
                elif duration > MAX_CLIP_DURATION:
                    end = start + MAX_CLIP_DURATION
                duration = end - start

            # Validate within video bounds
            if start < 0:
                start = 0
            if end > video_duration:
                end = video_duration
                duration = end - start

            candidates.append(ClipCandidate(
                clip_number=clip.get("clip_number", len(candidates) + 1),
                start_time=round(start, 3),
                end_time=round(end, 3),
                duration=round(duration, 1),
                clip_type=clip.get("type", "mixed"),
                viral_score=int(clip.get("viral_score", 5)),
                info_score=int(clip.get("info_score", 5)),
                hook=clip.get("hook", ""),
                summary=clip.get("summary", ""),
                key_words=[w.lower() for w in clip.get("key_words", [])],
                suggested_title=clip.get("suggested_title", ""),
            ))

        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping invalid clip data: {e}")
            continue

    # Remove overlapping clips
    candidates = _remove_overlaps(candidates)

    logger.info(f"Selected {len(candidates)} clip candidates")
    for c in candidates:
        logger.info(
            f"  Clip {c.clip_number}: {c.start_time:.1f}s-{c.end_time:.1f}s "
            f"({c.duration:.1f}s) [{c.clip_type}] "
            f"V:{c.viral_score}/I:{c.info_score} — {c.suggested_title}"
        )

    return candidates


def _remove_overlaps(candidates: list[ClipCandidate]) -> list[ClipCandidate]:
    """Remove overlapping clips, keeping the higher-scored ones."""
    if not candidates:
        return candidates

    # Sort by total score descending
    sorted_clips = sorted(
        candidates,
        key=lambda c: c.viral_score + c.info_score,
        reverse=True,
    )

    selected = []
    for clip in sorted_clips:
        overlap = False
        for existing in selected:
            # Check if clips overlap
            if clip.start_time < existing.end_time and clip.end_time > existing.start_time:
                overlap = True
                break
        if not overlap:
            selected.append(clip)

    # Re-number and sort by time
    selected.sort(key=lambda c: c.start_time)
    for i, clip in enumerate(selected, 1):
        clip.clip_number = i

    return selected
