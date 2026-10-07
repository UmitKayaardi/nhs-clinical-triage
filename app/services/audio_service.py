"""
Audio transcription service.

Wraps the local `whisper` library (model: base.en, matching the PoC) to
convert a patient's recorded audio into text. The model is loaded once
as a module-level singleton, since loading it per-request would add
several seconds of latency to every call.
"""

import logging
import os

import whisper

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TranscriptionError(Exception):
    """Raised when audio cannot be transcribed or contains no speech."""


class _WhisperModelSingleton:
    """
    Lazily loads and caches the Whisper model.
    Kept as a small class (rather than a bare module global) so the model
    can be explicitly reloaded or swapped in tests without reimporting
    the module.
    """

    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            logger.info("Loading Whisper model '%s'...", settings.WHISPER_MODEL_NAME)
            cls._model = whisper.load_model(settings.WHISPER_MODEL_NAME, device="cpu")
            logger.info("Whisper model loaded.")
        return cls._model


def transcribe_audio(file_path: str) -> str:
    """
    Transcribes a patient audio recording into plain text.

    Args:
        file_path: Path to a local audio file (wav, mp3, m4a, etc.).

    Returns:
        The transcribed text, stripped of leading/trailing whitespace.

    Raises:
        TranscriptionError: if the file is missing, unreadable, or
            contains no discernible speech (silent/empty audio).
    """
    if not file_path or not os.path.exists(file_path):
        raise TranscriptionError(f"Audio file not found: {file_path}")

    if os.path.getsize(file_path) == 0:
        raise TranscriptionError("Audio file is empty (0 bytes).")

    model = _WhisperModelSingleton.get()

    try:
        # fp16=False avoids a warning/failure on CPU-only machines, which
        # is the expected deployment target for a "base.en" model.
        result = model.transcribe(file_path, fp16=False)
    except Exception as exc:  # whisper can raise a variety of decoding errors
        logger.exception("Whisper transcription failed for %s", file_path)
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    text = (result.get("text") or "").strip()

    if not text:
        # This is the "silent audio" case: Whisper ran successfully but
        # detected no speech segments worth transcribing.
        raise TranscriptionError(
            "No speech detected in the recording. Please ask the patient to "
            "describe their symptoms again."
        )

    return text
