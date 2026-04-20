"""
Agent voice I/O for Smith.

STT uses `faster-whisper` locally.
TTS uses `edge-tts` neural voices.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

import edge_tts
import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger("smith.voice")

SAMPLE_RATE = 16_000
STT_MODEL_NAME = "medium"
STT_COMPUTE_TYPE = "int8"
DEFAULT_TTS_VOICE = "en-US-GuyNeural"
MAX_TTS_CHARS = 500

_stt_model = None


def _get_stt():
    """Lazily initialize the Whisper model."""
    global _stt_model

    if _stt_model is None:
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper STT model (%s)...", STT_MODEL_NAME)
        _stt_model = WhisperModel(
            STT_MODEL_NAME,
            compute_type=STT_COMPUTE_TYPE,
        )

    return _stt_model


def _get_tts():
    """Compatibility hook kept for callers that pre-warm TTS."""
    return None


class AgentVoiceRecognitionModule:
    """Capture audio from the microphone and transcribe it."""

    def listen(self, duration: float = 5.0) -> np.ndarray:
        """Record for a fixed duration and return mono float32 audio."""
        try:
            recording = sd.rec(
                int(duration * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            return recording.flatten()
        except sd.PortAudioError as exc:
            raise RuntimeError(f"Microphone error: {exc}") from exc

    def listen_vad(
        self,
        max_duration: float = 20.0,
        silence_threshold: float = 0.006,
        min_speech_duration: float = 0.4,
        post_speech_silence: float = 1.8,
        pre_speech_buffer: float = 0.5,
    ) -> np.ndarray:
        """
        Record with simple RMS-based voice activity detection.

        This waits for speech to start, keeps a short pre-speech buffer so the
        first syllable is not clipped, and stops after a natural trailing pause.
        """
        chunk_size = 512
        buffer_chunks = int(pre_speech_buffer * SAMPLE_RATE / chunk_size)
        max_chunks = int(max_duration * SAMPLE_RATE / chunk_size)
        min_speech_chunks = int(min_speech_duration * SAMPLE_RATE / chunk_size)
        max_silent_chunks = int(post_speech_silence * SAMPLE_RATE / chunk_size)

        pre_buffer: list[np.ndarray] = []
        chunks: list[np.ndarray] = []

        speech_started = False
        speech_chunks = 0
        silent_chunks = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=chunk_size,
            ) as stream:
                for _ in range(max_chunks):
                    data, _ = stream.read(chunk_size)
                    chunk = data.flatten()
                    rms = float(np.sqrt(np.mean(chunk**2)))

                    pre_buffer.append(chunk)
                    if len(pre_buffer) > buffer_chunks:
                        pre_buffer.pop(0)

                    if rms >= silence_threshold:
                        if not speech_started:
                            speech_started = True
                            chunks.extend(pre_buffer)

                        chunks.append(chunk)
                        speech_chunks += 1
                        silent_chunks = 0
                        continue

                    if speech_started:
                        chunks.append(chunk)
                        silent_chunks += 1

                        if (
                            speech_chunks >= min_speech_chunks
                            and silent_chunks >= max_silent_chunks
                        ):
                            break

        except sd.PortAudioError as exc:
            raise RuntimeError(f"Microphone error: {exc}") from exc

        if not chunks:
            return np.array([], dtype=np.float32)

        return np.concatenate(chunks).astype(np.float32, copy=False)

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe mono float32 audio and return plain text."""
        if audio is None or len(audio) == 0:
            return ""

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                temp_path = tmp.name

            sf.write(temp_path, audio, SAMPLE_RATE)

            model = _get_stt()
            segments, _ = model.transcribe(
                temp_path,
                vad_filter=True,
                language="en",
            )

            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text
        except Exception as exc:
            logger.error("STT transcription failed: %s", exc)
            return ""
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def listen_and_transcribe(self, max_duration: float = 15.0) -> str:
        """Record audio with VAD and immediately transcribe it."""
        audio = self.listen_vad(max_duration=max_duration)
        return self.transcribe(audio)


class AgentTTSModule:
    """Generate and play spoken audio for Smith responses."""

    def __init__(self, voice: str = DEFAULT_TTS_VOICE):
        self.voice = voice

    async def _generate_audio(self, text: str, filepath: str) -> None:
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate="+10%",
            pitch="+2Hz",
        )
        await communicate.save(filepath)

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return

        safe_text = " ".join(text.replace('"', " ").replace("'", " ").split())
        safe_text = safe_text[:MAX_TTS_CHARS]

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                temp_path = tmp.name

            asyncio.run(self._generate_audio(safe_text, temp_path))

            data, samplerate = sf.read(temp_path)
            sd.play(data, samplerate)
            sd.wait()
        except Exception as exc:
            logger.error("TTS failed: %s", exc)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
