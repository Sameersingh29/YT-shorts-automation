"""
Clip Selector — uses Gemini AI to identify the best moments from a transcript.
Picks a mix of viral/controversial and informative/valuable segments.

Strategy: splits the transcript into chunks and queries Gemini once per chunk
using Structured Output (response_schema + Pydantic) to guarantee valid JSON.
This eliminates ALL JSON truncation / parsing issues that occur with free-text
JSON generation on political/geopolitical content.
"""

import math
import re
import time
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types

from src.config import (
    GEMINI_API_KEY,
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
    CLIPS_PER_VIDEO,
    PODCAST_TOPICS,
    get_logger,
)

logger = get_logger(__name__)

# Number of chunks to split the transcript into.
CLIPS_PER_CHUNK = 2
NUM_CHUNKS = CLIPS_PER_VIDEO // CLIPS_PER_CHUNK   # e.g. 10 // 2 = 5

# Use gemini-2.0-flash for clip selection — it supports structured output
# with response_schema and doesn't burn thinking tokens on JSON output.
CLIP_SELECTOR_MODEL = "gemini-2.0-flash"


# ─── Pydantic schema for structured output ────────────────────────────────────
class ClipSchema(BaseModel):
    """Schema for a single clip candidate returned by Gemini."""
    clip_number: int = Field(description="Sequential clip number starting at 1")
    start_time: str = Field(description="Start time in HH:MM:SS format")
    end_time: str = Field(description="End time in HH:MM:SS format")
    duration_seconds: int = Field(description="Duration in seconds (30-60)")
    type: str = Field(description="'viral', 'informative', or 'mixed'")
    viral_score: int = Field(description="Virality score 1-10")
    info_score: int = Field(description="Informativeness score 1-10")
    hook: str = Field(description="First 5-8 attention-grabbing words of the clip")
    summary: str = Field(description="One-sentence description of the clip moment")
    key_words: list[str] = Field(description="3-5 key words to highlight in captions")
    suggested_title: str = Field(description="Catchy YouTube Shorts title with emoji, max 80 chars")


class ClipsResponse(BaseModel):
    """Top-level schema: list of clip candidates."""
    clips: list[ClipSchema]


# ─── Internal ClipCandidate dataclass (used by rest of pipeline) ──────────────
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
    """Convert 'HH:MM:SS.mmm', 'HH:MM:SS', or 'MM:SS' to seconds."""
    ts = ts.strip()
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        else:
            return float(parts[0])
    except (ValueError, TypeError):
        logger.warning(f"Could not parse timestamp: {ts!r}, defaulting to 0")
        return 0.0


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

SELECTION CRITERIA:
- VIRAL moments: Hot takes, surprising revelations, emotional peaks, quotable statements
- INFORMATIVE moments: Key insights, actionable advice, unique perspectives, life-changing ideas

PODCAST TOPICS: {topics}

TRANSCRIPT SEGMENT (minutes {chunk_start_min} to {chunk_end_min}):
{chunk_text}

Identify exactly {clips_wanted} clip(s) from this segment. Timestamps must fall within minutes {chunk_start_min}-{chunk_end_min}."""


def _call_gemini_structured(
    client: genai.Client,
    prompt: str,
    chunk_idx: int,
    clips_wanted: int = CLIPS_PER_CHUNK,
    attempt: int = 0,
) -> list[ClipSchema]:
    """
    Call Gemini with structured output (response_schema) to get guaranteed valid JSON.

    Returns a list of ClipSchema objects. Never raises — returns [] on any failure.
    """
    safety_off = [
        genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",       threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]

    try:
        response = client.models.generate_content(
            model=CLIP_SELECTOR_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.4,          # Lower temp = more deterministic JSON
                max_output_tokens=4096,
                safety_settings=safety_off,
                # Structured output: forces the model to emit valid JSON matching ClipsResponse
                response_mime_type="application/json",
                response_schema=ClipsResponse,
                # Disable thinking for 2.0-flash (ignored by 2.0, safe for 2.5)
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as exc:
        logger.error(f"Chunk {chunk_idx + 1}: Gemini API call failed (attempt {attempt + 1}): {exc}")
        return []

    # Log finish reason and safety ratings
    finish_reason = "UNKNOWN"
    safety_info = ""
    if response.candidates:
        cand = response.candidates[0]
        finish_reason = str(cand.finish_reason)
        if hasattr(cand, "safety_ratings") and cand.safety_ratings:
            blocked = [
                f"{r.category}={r.probability}"
                for r in cand.safety_ratings
                if str(r.probability) not in ("NEGLIGIBLE", "LOW", "HarmProbability.NEGLIGIBLE", "HarmProbability.LOW")
            ]
            if blocked:
                safety_info = f" | safety_flags: {blocked}"

    logger.info(
        f"Chunk {chunk_idx + 1}/{NUM_CHUNKS}: finish_reason={finish_reason}"
        f"{safety_info}"
    )

    # If blocked by safety filter, log and return empty
    if "SAFETY" in finish_reason:
        logger.warning(
            f"Chunk {chunk_idx + 1}: response blocked by safety filter. "
            f"Returning 0 clips for this chunk.{safety_info}"
        )
        return []

    # If output was cut off (MAX_TOKENS), retry once with fewer clips
    if "MAX_TOKENS" in finish_reason and clips_wanted > 1 and attempt == 0:
        logger.warning(
            f"Chunk {chunk_idx + 1}: MAX_TOKENS hit, retrying with 1 clip at a time..."
        )
        return []  # Caller will retry per-clip

    # Use response.parsed for clean Pydantic deserialization
    try:
        parsed: ClipsResponse = response.parsed
        if parsed and parsed.clips:
            logger.info(f"Chunk {chunk_idx + 1}: structured output → {len(parsed.clips)} clip(s)")
            return parsed.clips
        else:
            logger.warning(f"Chunk {chunk_idx + 1}: parsed response has no clips")
            return []
    except Exception as exc:
        logger.warning(f"Chunk {chunk_idx + 1}: response.parsed failed ({exc}), trying response.text fallback")

    # Fallback: manually parse response.text as JSON
    try:
        import json
        raw = (response.text or "").strip()
        # Strip fences
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if m:
            raw = m.group(1).strip()
        data = json.loads(raw)
        # Handle both {"clips": [...]} and bare [...] formats
        if isinstance(data, dict) and "clips" in data:
            clips_data = data["clips"]
        elif isinstance(data, list):
            clips_data = data
        else:
            clips_data = []
        result = [ClipSchema(**c) for c in clips_data[:clips_wanted]]
        logger.info(f"Chunk {chunk_idx + 1}: text fallback → {len(result)} clip(s)")
        return result
    except Exception as exc2:
        logger.error(f"Chunk {chunk_idx + 1}: all parsing attempts failed: {exc2}")
        return []


def _split_transcript(transcript_text: str, n_chunks: int) -> list[tuple[str, int, int]]:
    """
    Split transcript into n_chunks roughly equal parts by line count.
    Returns list of (chunk_text, start_min, end_min) tuples.
    """
    lines = transcript_text.splitlines(keepends=True)
    lines_per_chunk = math.ceil(len(lines) / n_chunks)

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


def _schema_to_candidate(clip: ClipSchema, clip_number: int, video_duration: float) -> Optional[ClipCandidate]:
    """Convert a ClipSchema (Pydantic) into a ClipCandidate. Returns None if invalid."""
    try:
        start = _parse_timestamp(clip.start_time)
        end = _parse_timestamp(clip.end_time)
        duration = end - start

        # Clamp duration to acceptable range
        if duration < MIN_CLIP_DURATION - 5 or duration > MAX_CLIP_DURATION + 10:
            logger.warning(
                f"Clip has duration {duration:.1f}s "
                f"(expected {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION}s), clamping..."
            )
            if duration < MIN_CLIP_DURATION:
                end = start + MIN_CLIP_DURATION
            elif duration > MAX_CLIP_DURATION:
                end = start + MAX_CLIP_DURATION
            duration = end - start

        # Clamp to video bounds
        if start < 0:
            start = 0.0
        if end > video_duration:
            end = video_duration
            duration = end - start

        if duration <= 0:
            logger.warning(f"Clip has non-positive duration after clamping, skipping.")
            return None

        return ClipCandidate(
            clip_number=clip_number,
            start_time=round(start, 3),
            end_time=round(end, 3),
            duration=round(duration, 1),
            clip_type=clip.type or "mixed",
            viral_score=max(1, min(10, int(clip.viral_score))),
            info_score=max(1, min(10, int(clip.info_score))),
            hook=clip.hook or "",
            summary=clip.summary or "",
            key_words=[w.lower() for w in (clip.key_words or [])],
            suggested_title=clip.suggested_title or "",
        )
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Skipping invalid clip data: {e} — data: {clip}")
        return None


def select_clips(transcript_text: str, video_duration: float) -> list[ClipCandidate]:
    """
    Use Gemini AI to select the best clip candidates from a transcript.

    Uses Structured Output (response_schema=ClipsResponse) to guarantee
    valid JSON — no more truncated JSON or parsing failures.

    Splits the transcript into NUM_CHUNKS segments and asks for CLIPS_PER_CHUNK
    clips from each, then combines and deduplicates.

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
        f"of ~{len(transcript_text) // max(len(chunks), 1)} chars each. "
        f"Requesting {CLIPS_PER_CHUNK} clips per chunk via structured output."
    )

    all_clip_schemas: list[ClipSchema] = []

    for i, (chunk_text, start_min, end_min) in enumerate(chunks):
        logger.info(f"Processing chunk {i + 1}/{len(chunks)}: "
                    f"minutes {start_min}-{end_min} ({len(chunk_text)} chars)")

        prompt = _build_chunk_prompt(chunk_text, start_min, end_min, CLIPS_PER_CHUNK)

        # First attempt: ask for CLIPS_PER_CHUNK clips
        clip_schemas = _call_gemini_structured(client, prompt, i, CLIPS_PER_CHUNK, attempt=0)

        if not clip_schemas:
            # Retry: ask for 1 clip at a time (avoids safety truncation on long outputs)
            logger.info(f"Chunk {i + 1}: retrying with 1 clip per request...")
            for attempt_num in range(CLIPS_PER_CHUNK):
                single_prompt = _build_chunk_prompt(chunk_text, start_min, end_min, 1)
                single_schemas = _call_gemini_structured(client, single_prompt, i, 1, attempt=1)
                if single_schemas:
                    clip_schemas.extend(single_schemas)
                    logger.info(f"Chunk {i + 1} retry {attempt_num + 1}: got {len(single_schemas)} clip(s)")
                else:
                    logger.warning(f"Chunk {i + 1} retry {attempt_num + 1}: still no clips")
                # Small delay between retries to avoid rate limiting
                time.sleep(1)

        logger.info(f"Chunk {i + 1}: final clip count = {len(clip_schemas)}")
        all_clip_schemas.extend(clip_schemas)

    logger.info(f"Total raw clips from all chunks: {len(all_clip_schemas)}")

    # Convert to ClipCandidate objects
    candidates: list[ClipCandidate] = []
    for schema in all_clip_schemas:
        c = _schema_to_candidate(schema, len(candidates) + 1, video_duration)
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
