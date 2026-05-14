"""
Transcriber — extracts audio from video and transcribes with word-level timestamps.
Uses faster-whisper (CTranslate2) for accurate, fast transcription on CPU.
"""

import subprocess
from pathlib import Path
from dataclasses import dataclass, field

from src.config import (
    TEMP_DIR,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    get_logger,
)

logger = get_logger(__name__)


@dataclass
class WordTimestamp:
    """A single word with its timing information."""
    word: str
    start: float  # seconds
    end: float    # seconds


@dataclass
class TranscriptSegment:
    """A segment of the transcript (typically a sentence or phrase)."""
    text: str
    start: float
    end: float
    words: list[WordTimestamp] = field(default_factory=list)


@dataclass
class Transcript:
    """Full transcript with segments and metadata."""
    segments: list[TranscriptSegment]
    language: str
    duration: float  # total audio duration in seconds

    @property
    def full_text(self) -> str:
        """Return the complete transcript as a single string."""
        return " ".join(seg.text.strip() for seg in self.segments)

    @property
    def all_words(self) -> list[WordTimestamp]:
        """Return all words across all segments."""
        words = []
        for seg in self.segments:
            words.extend(seg.words)
        return words

    def get_words_in_range(self, start: float, end: float) -> list[WordTimestamp]:
        """Get all words that fall within a time range."""
        return [
            w for w in self.all_words
            if w.start >= start - 0.1 and w.end <= end + 0.1
        ]

    def get_text_in_range(self, start: float, end: float) -> str:
        """Get transcript text for a specific time range."""
        words = self.get_words_in_range(start, end)
        return " ".join(w.word.strip() for w in words)


def extract_audio(video_path: Path, output_path: Path = None) -> Path:
    """
    Extract audio from a video file as mono 16kHz WAV (optimal for Whisper).

    Args:
        video_path: Path to the source video file.
        output_path: Optional output path. Defaults to temp directory.

    Returns:
        Path to the extracted audio file.
    """
    if output_path is None:
        output_path = TEMP_DIR / f"{video_path.stem}_audio.wav"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                    # No video
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16kHz sample rate (Whisper optimal)
        "-ac", "1",               # Mono
        str(output_path),
    ]

    logger.info(f"Extracting audio from {video_path.name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"FFmpeg audio extraction failed: {result.stderr}")
        raise RuntimeError(f"Failed to extract audio: {result.stderr}")

    logger.info(f"Audio extracted → {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")
    return output_path


def transcribe(video_path: Path) -> Transcript:
    """
    Transcribe a video file with word-level timestamps.

    Pipeline:
        1. Extract audio from video (FFmpeg)
        2. Transcribe with faster-whisper (word-level timestamps)
        3. Return structured Transcript object

    Args:
        video_path: Path to the video file.

    Returns:
        Transcript object with segments and word timestamps.
    """
    from faster_whisper import WhisperModel

    # Step 1: Extract audio
    audio_path = extract_audio(video_path)

    # Step 2: Load Whisper model
    logger.info(f"Loading Whisper model '{WHISPER_MODEL}' on {WHISPER_DEVICE}...")
    model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )

    # Step 3: Transcribe with word timestamps
    logger.info("Transcribing audio (this may take a while for long videos)...")
    raw_segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,          # Voice Activity Detection to skip silence
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )

    # Step 4: Build structured transcript
    segments = []
    for raw_seg in raw_segments:
        words = []
        if raw_seg.words:
            for w in raw_seg.words:
                words.append(WordTimestamp(
                    word=w.word,
                    start=round(w.start, 3),
                    end=round(w.end, 3),
                ))

        segments.append(TranscriptSegment(
            text=raw_seg.text.strip(),
            start=round(raw_seg.start, 3),
            end=round(raw_seg.end, 3),
            words=words,
        ))

    transcript = Transcript(
        segments=segments,
        language=info.language,
        duration=info.duration,
    )

    total_words = len(transcript.all_words)
    logger.info(
        f"Transcription complete: {len(segments)} segments, "
        f"{total_words} words, language={info.language}, "
        f"duration={info.duration:.1f}s"
    )

    # Cleanup temp audio
    try:
        audio_path.unlink()
    except OSError:
        pass

    return transcript
