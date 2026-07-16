"""Run faster-whisper against one local audio artifact.

Examples:
    python tools/diagnose_transcription.py --audio-path work/olympus_speech.wav
    python tools/diagnose_transcription.py --audio-key analysis/<project>/audio.wav
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from olympus.ai.transcription.faster_whisper import FasterWhisperTranscriptionProvider
from olympus.data.storage import build_storage
from olympus.platform.config import get_settings


def _latest_extracted_audio(local_root: str) -> str | None:
    root = Path(local_root).resolve()
    matches = sorted(
        root.glob("analysis/*/audio.wav"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        return None
    return matches[0].relative_to(root).as_posix()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    storage = build_storage(settings)

    if args.audio_key:
        audio_key = args.audio_key
    elif args.audio_path:
        audio_path = Path(args.audio_path).resolve()
        audio_key = args.storage_key
        await storage.put(
            audio_key,
            audio_path.read_bytes(),
            content_type="audio/wav",
        )
    else:
        found = _latest_extracted_audio(settings.storage.local_root)
        if found is None:
            print("No extracted storage_data/analysis/*/audio.wav was found.")
            return 2
        audio_key = found

    provider = FasterWhisperTranscriptionProvider(
        storage,
        model=settings.ai.whisper_model,
        device=settings.ai.whisper_device,
        compute_type=settings.ai.whisper_compute_type,
        beam_size=settings.ai.whisper_beam_size,
        language=settings.ai.whisper_language,
        download_root=settings.ai.whisper_download_root,
        timeout_seconds=settings.ai.whisper_timeout_seconds,
    )

    started = time.perf_counter()
    result = await provider.transcribe(audio_key)
    duration = time.perf_counter() - started

    print(f"language={result.language}")
    print(f"segments={len(result.segments)}")
    print(f"duration_seconds={duration:.2f}")
    if result.segments:
        print(f"first_segment={result.segments[0].text}")
    if not result.segments or not result.text.strip():
        print("No transcript segments returned.")
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-key", help="Existing storage key to transcribe.")
    parser.add_argument("--audio-path", help="Local WAV file to copy into storage first.")
    parser.add_argument(
        "--storage-key",
        default="analysis/diagnostic/audio.wav",
        help="Storage key used with --audio-path.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
