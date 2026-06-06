"""
Clip Selector — uses Gemini AI to identify the best moments from a transcript.
Picks a mix of viral/controversial and informative/valuable segments.

Strategy: splits the transcript into chunks and queries Gemini once per chunk
for 2 clips each. This avoids safety-filter mid-response truncation that happens
when sending very large political/geopolitical transcripts in one shot.
"""

import json
import re
import math
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

# Number of chunks to split the transcript into.
# CLIPS_PER_VIDEO / CLIPS_PER_CHUNK must be a whole number.
CLIPS_PER_CHUNK = 2
NUM_CHUNKS = CLIPS_PER_VIDEO // CLIPS_PER_CHUNK   # e.g. 10 // 2 = 5

# Use a non-thinking model for clip selection — thinking models (gemini-2.5-*)
# consume thinking tokens against max_output_tokens, causing JSON truncation.
# NOTE: Do NOT change this to gemini-2.5-flash — it will break JSON output.
CLIP_SELECTOR_MODEL = "gemini-2.0-flash"


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


def _build_chunk_prompt(chunk_text: str, chunk_start_min: int, chunk_end_min: int,
                        clips_wanted: int) -> str:
    """Build a clip selection prompt for a single transcript chunk."""
    topics = ", ".join(PODCAST_TOPICS)
    return f"""You are an expert YouTube Shorts content strategist specializing in viral podcast clips.

TASK: Analyze this podcast transcript segment (minutes {chunk_start_min}-{chunk_end_min}) and identify exactly {clips_wanted} segments that would make great YouTube Shorts.

CLIP REQUIREMENTS:
- Each clip must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds long
- Clips must NOT overlap with each other
- Each clip must be a self-contained moment (makes sense without context)
- Start each clip at a natural beginning of a thought/statement
- End each clip at a natural conclusion or powerful punchline

SELECTION CRITERIA (pick the BEST from this segment):
- VIRAL moments: Hot takes, surprising revelations, emotional peaks, quotable statements
- INFORMATIVE moments: Key insights, actionable advice, unique perspectives, life-changing ideas

PODCAST TOPICS: {topics}

TRANSCRIPT SEGMENT (minutes {chunk_start_min} to {chunk_end_min}):
{chunk_text}

RESPOND WITH ONLY a JSON array of exactly {clips_wanted} objects. No markdown, no explanation, just the JSON:
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

Timestamps must fall within minutes {chunk_start_min}-{chunk_end_min} of the video."""


def _call_gemini(client: genai.Client, prompt: str, chunk_idx: int, clips_wanted: int = CLIPS_PER_CHUNK) -> str:
    """Call Gemini for one chunk. Returns raw response text.

    If the model returns MAX_TOKENS with a suspiciously short response
    (safety-truncation pattern on political/geopolitical content), automatically
    retries asking for 1 clip at a time to get completable responses.
    """
    safety_off = [
        genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",       threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]

    response = client.models.generate_content(
        model=CLIP_SELECTOR_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=16384,  # Increased to avoid legitimate truncation
            safety_settings=safety_off,
            # Disable thinking tokens — they consume max_output_tokens budget,
            # causing the JSON array to be cut off mid-response. Only applies
            # to thinking models (gemini-2.5-*); ignored for 2.0-flash.
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )

    # Log finish_reason for diagnostics
    finish_reason = "UNKNOWN"
    if response.candidates:
        finish_reason = str(response.candidates[0].finish_reason)

    # Safely extract response text — .text can raise ValueError on blocked/truncated
    # responses, so we pull from candidate parts directly as a fallback.
    response_text = ""
    try:
        response_text = response.text or ""
    except (ValueError, AttributeError):
        try:
            # Try extracting partial text from the candidate's content parts directly
            candidate = response.candidates[0] if response.candidates else None
            if candidate and candidate.content and candidate.content.parts:
                response_text = "".join(
                    p.text for p in candidate.content.parts if hasattr(p, "text") and p.text
                )
        except Exception:
            response_text = ""

    logger.info(f"Chunk {chunk_idx + 1}/{NUM_CHUNKS}: finish_reason={finish_reason}, "
                f"response_len={len(response_text)}")

    # Detect safety-truncation: MAX_TOKENS with a suspiciously short response
    # means the server cut the response mid-JSON due to content policy, not a real
    # token limit. Threshold raised to 1200 to catch all truncated-JSON cases.
    # Retry by asking for 1 clip at a time to get completable responses.
    if "MAX_TOKENS" in finish_reason and len(response_text) < 1200 and clips_wanted > 1:
        logger.warning(
            f"Chunk {chunk_idx + 1}: short MAX_TOKENS response detected "
            f"(likely safety truncation, {len(response_text)} chars). Retrying 1 clip at a time..."
        )
        return _RETRY_SINGLE

    return response_text


# Sentinel returned by _call_gemini to request per-clip retries
_RETRY_SINGLE = "__RETRY_SINGLE__"


def _parse_clips_from_response(raw_text: str, chunk_idx: int) -> list[dict]:
    """Parse JSON clip array from a Gemini response. Returns list of raw dicts."""
    raw_text = raw_text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
    if fence_match:
        raw_text = fence_match.group(1).strip()

    # Find the JSON array
    json_match = re.search(r'\[', raw_text)
    if not json_match:
        logger.warning(f"Chunk {chunk_idx + 1}: no JSON array in response. "
                       f"Preview: {raw_text[:300]!r}")
        return []

    json_str = raw_text[json_match.start():]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Chunk {chunk_idx + 1}: full JSON parse failed ({e}), "
                       f"attempting partial recovery...")
        # Recover as many complete objects as possible
        last_brace = json_str.rfind('},')
        if last_brace == -1:
            last_brace = json_str.rfind('}')
        if last_brace != -1:
            partial = json_str[:last_brace + 1].rstrip(',') + ']'
            try:
                recovered = json.loads(partial)
                logger.info(f"Chunk {chunk_idx + 1}: partial recovery got {len(recovered)} clip(s)")
                return recovered
            except json.JSONDecodeError as e2:
                logger.error(f"Chunk {chunk_idx + 1}: partial recovery failed: {e2}")
        else:
            logger.error(f"Chunk {chunk_idx + 1}: JSON unrecoverable. "
                         f"Raw: {raw_text[:400]!r}")
        return []


def _split_transcript(transcript_text: str, n_chunks: int) -> list[tuple[str, int, int]]:
    """
    Split transcript into n_chunks roughly equal parts by line count.
    Returns list of (chunk_text, start_min, end_min) tuples.
    Tries to split at line boundaries so timestamps stay intact.
    """
    lines = transcript_text.splitlines(keepends=True)
    lines_per_chunk = math.ceil(len(lines) / n_chunks)

    # Extract the video time range from the first/last timestamp lines
    def _first_minute(text: str) -> int:
        m = re.search(r'\[(\d+):\d+\]', text)
        return int(m.group(1)) if m else 0

    def _last_minute(text: str) -> int:
        matches = list(re.finditer(r'\[(\d+):\d+\]', text))
        return int(matches[-1].group(1)) if matches else 0

    chunks = []
    for i in range(n_chunks):
        chunk_lines = lines[i * lines_per_chunk: (i + 1) * lines_per_chunk]
        chunk_text = "".join(chunk_lines)
        if not chunk_text.strip():
            continue
        start_min = _first_minute(chunk_text)
        end_min = _last_minute(chunk_text)
        chunks.append((chunk_text, start_min, end_min))

    return chunks


def _dict_to_candidate(clip: dict, clip_number: int, video_duration: float) -> ClipCandidate | None:
    """Convert a raw clip dict from Gemini JSON into a ClipCandidate. Returns None if invalid."""
    try:
        start = _parse_timestamp(str(clip["start_time"]))
        end = _parse_timestamp(str(clip["end_time"]))
        duration = end - start

        # Clamp duration
        if duration < MIN_CLIP_DURATION - 5 or duration > MAX_CLIP_DURATION + 10:
            logger.warning(
                f"Clip has duration {duration:.1f}s "
                f"(expected {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION}s), adjusting..."
            )
            if duration < MIN_CLIP_DURATION:
                end = start + MIN_CLIP_DURATION
            elif duration > MAX_CLIP_DURATION:
                end = start + MAX_CLIP_DURATION
            duration = end - start

        # Clamp to video bounds
        if start < 0:
            start = 0
        if end > video_duration:
            end = video_duration
            duration = end - start

        return ClipCandidate(
            clip_number=clip_number,
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
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"Skipping invalid clip data: {e} — data: {clip}")
        return None


def select_clips(transcript_text: str, video_duration: float) -> list[ClipCandidate]:
    """
    Use Gemini AI to select the best clip candidates from a transcript.

    Splits the transcript into NUM_CHUNKS segments and asks for CLIPS_PER_CHUNK
    clips from each, then combines and deduplicates. This avoids safety-filter
    truncation that occurs when sending very large transcripts in one request.

    Args:
        transcript_text: Full transcript text with timestamps.
        video_duration: Total video duration in seconds.

    Returns:
        List of ClipCandidate objects sorted by quality score.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY env var is not set.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    chunks = _split_transcript(transcript_text, NUM_CHUNKS)
    logger.info(
        f"Split transcript ({len(transcript_text)} chars) into {len(chunks)} chunks "
        f"of ~{len(transcript_text) // len(chunks) if chunks else 0} chars each. "
        f"Requesting {CLIPS_PER_CHUNK} clips per chunk."
    )

    all_raw_clips: list[dict] = []

    for i, (chunk_text, start_min, end_min) in enumerate(chunks):
        logger.info(f"Processing chunk {i + 1}/{len(chunks)}: "
                    f"minutes {start_min}-{end_min} ({len(chunk_text)} chars)")
        prompt = _build_chunk_prompt(chunk_text, start_min, end_min, CLIPS_PER_CHUNK)
        try:
            raw_text = _call_gemini(client, prompt, i)

            if raw_text == _RETRY_SINGLE:
                # Safety-truncation detected: retry asking for 1 clip at a time
                logger.info(f"Chunk {i + 1}: retrying with 1 clip per request...")
                for attempt in range(CLIPS_PER_CHUNK):
                    single_prompt = _build_chunk_prompt(
                        chunk_text, start_min, end_min, clips_wanted=1
                    )
                    single_text = _call_gemini(client, single_prompt, i, clips_wanted=1)
                    if single_text and single_text != _RETRY_SINGLE:
                        clip_dicts = _parse_clips_from_response(single_text, i)
                        logger.info(f"Chunk {i + 1} retry {attempt + 1}: got {len(clip_dicts)} clip(s)")
                        all_raw_clips.extend(clip_dicts)
                    else:
                        logger.warning(f"Chunk {i + 1} retry {attempt + 1}: still truncated, skipping")
            else:
                clip_dicts = _parse_clips_from_response(raw_text, i)
                logger.info(f"Chunk {i + 1}: got {len(clip_dicts)} clip(s)")
                all_raw_clips.extend(clip_dicts)
        except Exception as e:
            logger.error(f"Chunk {i + 1} failed entirely: {e}")
            continue

    logger.info(f"Total raw clips from all chunks: {len(all_raw_clips)}")

    # Convert to ClipCandidate objects
    candidates: list[ClipCandidate] = []
    for raw in all_raw_clips:
        c = _dict_to_candidate(raw, len(candidates) + 1, video_duration)
        if c is not None:
            candidates.append(c)

    # Remove overlapping clips (keep higher-scored ones)
    candidates = _remove_overlaps(candidates)

    logger.info(f"Selected {len(candidates)} clip candidates after dedup")
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
