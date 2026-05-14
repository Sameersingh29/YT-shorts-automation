"""
Metadata Generator — uses Gemini AI to create viral titles, descriptions, and hashtags.
"""

import json
import re

import google.generativeai as genai

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    PODCAST_TOPICS,
    get_logger,
)

logger = get_logger(__name__)


def generate_metadata(
    clip_summary: str,
    hook: str,
    clip_type: str,
    suggested_title: str = "",
    transcript_snippet: str = "",
) -> dict:
    """
    Generate optimized metadata for a YouTube Short using Gemini.

    Args:
        clip_summary: Brief description of the clip content.
        hook: The attention-grabbing opening line.
        clip_type: "viral", "informative", or "mixed".
        suggested_title: AI-suggested title from clip selection.
        transcript_snippet: The actual transcript text of the clip.

    Returns:
        Dict with keys: title, description, tags, hashtags.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY env var is not set.")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    topics = ", ".join(PODCAST_TOPICS)

    prompt = f"""You are a YouTube Shorts SEO expert. Generate optimized metadata for this podcast clip.

CLIP INFO:
- Summary: {clip_summary}
- Hook/Opening: {hook}
- Type: {clip_type}
- Suggested Title: {suggested_title}
- Transcript: {transcript_snippet[:500]}

PODCAST TOPICS: {topics}

Generate metadata in this EXACT JSON format (no markdown, just JSON):
{{
  "title": "Catchy title with 1-2 relevant emojis. Max 80 characters. Must create curiosity.",
  "description": "Engaging description with:\n- Hook in first line\n- 2-3 lines of value/context\n- Call to action (like, follow, comment)\n- Max 300 characters before hashtags",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
  "hashtags": ["#Shorts", "#tag1", "#tag2", "#tag3", "#tag4"]
}}

RULES:
1. Title: Use curiosity gaps, power words, numbers. Must be scroll-stopping.
2. Description: First line is the hook. Include CTA.
3. Tags: 10 relevant tags for YouTube algorithm. Mix broad + niche.
4. Hashtags: Always include #Shorts first. Max 5 total. Most relevant ones.
5. All content must be appropriate for YouTube.

Return ONLY the JSON object."""

    logger.info("Generating metadata with Gemini...")

    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.8,
            max_output_tokens=1024,
        ),
    )

    raw = response.text.strip()

    # Extract JSON
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        logger.warning(f"Failed to parse metadata JSON, using fallback. Raw: {raw[:300]}")
        return _fallback_metadata(suggested_title, clip_summary, hook)

    try:
        metadata = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.warning("JSON parse error for metadata, using fallback.")
        return _fallback_metadata(suggested_title, clip_summary, hook)

    # Validate and clean
    metadata["title"] = metadata.get("title", suggested_title)[:100]
    metadata["description"] = metadata.get("description", clip_summary)[:5000]
    metadata["tags"] = metadata.get("tags", [])[:15]
    metadata["hashtags"] = metadata.get("hashtags", ["#Shorts"])[:5]

    # Ensure #Shorts is always first hashtag
    if "#Shorts" not in metadata["hashtags"]:
        metadata["hashtags"].insert(0, "#Shorts")

    # Append hashtags to description
    hashtag_str = " ".join(metadata["hashtags"])
    if hashtag_str not in metadata["description"]:
        metadata["description"] += f"\n\n{hashtag_str}"

    logger.info(f"Generated metadata — Title: {metadata['title']}")
    return metadata


def _fallback_metadata(title: str, summary: str, hook: str) -> dict:
    """Generate simple fallback metadata when AI fails."""
    return {
        "title": title[:100] if title else f"🔥 {summary[:80]}",
        "description": (
            f"{hook}\n\n{summary}\n\n"
            f"👊 Like & Subscribe for more!\n\n"
            f"#Shorts #Motivation #Mindset #Success #Podcast"
        ),
        "tags": [
            "shorts", "motivation", "podcast", "money",
            "mindset", "success", "discipline", "stoicism",
            "entrepreneurship", "self improvement",
        ],
        "hashtags": ["#Shorts", "#Motivation", "#Mindset", "#Success", "#Podcast"],
    }
