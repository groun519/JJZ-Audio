from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import soundfile as sf

from jang_app.services.audio_preview import prepare_preview_audio


class AudioClipError(RuntimeError):
    """Raised when a selected audio range cannot be rendered."""


def render_audio_clip(
    source: Path,
    output_path: Path,
    start_ms: int,
    end_ms: int,
    progress: Callable[[int], None] | None = None,
) -> Path:
    if start_ms < 0 or end_ms <= start_ms:
        raise AudioClipError("Select a valid audio range.")
    preview_path = prepare_preview_audio(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(f"{output_path.suffix}.rendering")

    try:
        with sf.SoundFile(preview_path) as input_file:
            start_frame = min(input_file.frames, round(start_ms * input_file.samplerate / 1000))
            end_frame = min(input_file.frames, round(end_ms * input_file.samplerate / 1000))
            frame_count = end_frame - start_frame
            if frame_count <= 0:
                raise AudioClipError("The selected range contains no audio frames.")
            input_file.seek(start_frame)
            written = 0
            with sf.SoundFile(
                temporary,
                mode="w",
                samplerate=input_file.samplerate,
                channels=input_file.channels,
                format="WAV",
                subtype="PCM_16",
            ) as output_file:
                while written < frame_count:
                    block = input_file.read(min(65536, frame_count - written), dtype="float32", always_2d=True)
                    if not len(block):
                        break
                    output_file.write(block)
                    written += len(block)
                    if progress is not None:
                        progress(_percentage(written, frame_count))
            if written <= 0:
                raise AudioClipError("No audio was written for the selected range.")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    if progress is not None:
        progress(100)
    return output_path


def _percentage(current: int, total: int) -> int:
    if total <= 0:
        return 100
    return max(0, min(100, round(current * 100 / total)))
