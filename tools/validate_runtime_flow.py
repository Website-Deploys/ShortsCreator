"""Run a real local Olympus upload -> render smoke through the HTTP API.

This is a developer diagnostic, not part of the app runtime. It uploads a local
video, creates a project with automatic clip count, polls the background engine
chain, downloads every rendered MP4, and optionally validates them with
ffprobe when available on PATH.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

JsonObject = dict[str, Any]


def _json_object(raw: str | bytes) -> JsonObject:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object response.")
    return cast(JsonObject, value)


def _json_request(
    base: str,
    method: str,
    path: str,
    payload: JsonObject | None = None,
) -> JsonObject:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        urllib.parse.urljoin(base, path),
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return _json_object(response.read())


def _get_json_or_none(base: str, path: str) -> JsonObject | None:
    try:
        return _json_request(base, "GET", path)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _upload(base: str, video: Path) -> JsonObject:
    boundary = f"----olympus-{uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{video.name}"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + video.read_bytes() + tail
    request = urllib.request.Request(
        urllib.parse.urljoin(base, "/api/v1/uploads"),
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return _json_object(response.read())


def _create_project(base: str, upload: JsonObject, content_category: str) -> JsonObject:
    return _json_request(
        base,
        "POST",
        "/api/v1/projects",
        {
            "storage_key": upload["storage_key"],
            "source_filename": upload["filename"],
            "size_bytes": upload["size_bytes"],
            "video_format": upload["video_format"],
            "content_type": upload.get("content_type"),
            "duration_seconds": None,
            "width": None,
            "height": None,
            "upload_duration_ms": None,
            "desired_clip_count": None,
            "content_category": content_category,
            "editing_intensity": "auto",
            "music_enabled": True,
            "sfx_enabled": True,
            "captions_enabled": True,
        },
    )


def _download(base: str, path: str, destination: Path) -> None:
    with urllib.request.urlopen(urllib.parse.urljoin(base, path), timeout=120) as response:
        destination.write_bytes(response.read())


def _probe(path: Path) -> JsonObject:
    if shutil.which("ffprobe") is None:
        return {"unavailable": "ffprobe unavailable"}
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,duration,channels,sample_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return _json_object(completed.stdout)


def _validate_probe(path: Path, probe: JsonObject, *, require_audio: bool) -> None:
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError(f"{path} has no video stream")
    if video.get("width") != 1080 or video.get("height") != 1920:
        raise RuntimeError(f"{path} is not 1080x1920: {video}")
    if require_audio and audio is None:
        raise RuntimeError(f"{path} has no audio stream")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--content-category", default="educational")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--download-dir", type=Path, default=Path("work"))
    parser.add_argument("--require-audio", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()
    upload = _upload(args.base, args.video)
    project = _create_project(args.base, upload, args.content_category)
    project_id = project["id"]
    print(f"PROJECT {project_id}")

    manifest: JsonObject | None = None
    while time.monotonic() - started < args.timeout_seconds:
        info = _json_request(args.base, "GET", "/api/v1/system/info")
        analysis = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/analysis")
        planning = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/planning")
        editing = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/editing")
        rendering = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/rendering")
        manifest = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/rendering/manifest")
        print(
            "STATUS",
            {
                "system": info["adapters"],
                "analysis": (analysis or {}).get("status"),
                "planning": (planning or {}).get("status"),
                "editing": (editing or {}).get("status"),
                "rendering": (rendering or {}).get("status"),
                "renders": len(((manifest or {}).get("manifest") or {}).get("renders") or []),
            },
        )
        if manifest and manifest["manifest"].get("renders"):
            break
        if rendering and rendering.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(f"rendering stopped: {rendering}")
        time.sleep(5)

    if not manifest or not manifest["manifest"].get("renders"):
        raise TimeoutError("No rendered MP4 manifest appeared before timeout.")

    renders = manifest["manifest"]["renders"]
    args.download_dir.mkdir(parents=True, exist_ok=True)
    plans = _get_json_or_none(args.base, f"/api/v1/projects/{project_id}/planning/plans") or {}
    print("PLAN_COUNT", plans.get("plan_count"))
    print("RENDER_COUNT", len(renders))
    for item in renders:
        out = args.download_dir / f"validated_{project_id}_{item['clip_id']}.mp4"
        download_path = f"/api/v1/projects/{project_id}/rendering/clips/{item['clip_id']}/download"
        _download(args.base, download_path, out)
        probe = _probe(out)
        _validate_probe(out, probe, require_audio=args.require_audio)
        print("DOWNLOADED", out)
        print("FFPROBE", json.dumps(probe, indent=2))


if __name__ == "__main__":
    main()
