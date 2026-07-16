"""Generate or validate Olympus Upload Metadata V2 without publishing anything."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from olympus.metadata import generate_upload_metadata, validate_upload_metadata
from olympus.platform.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--metadata-file", type=Path)
    modes.add_argument("--project-id")
    modes.add_argument("--manifest", type=Path)
    modes.add_argument("--sample-transcript")
    parser.add_argument("--niche", default="motivational")
    parser.add_argument("--hook-category", default="curiosity_gap")
    parser.add_argument(
        "--safety-risk",
        choices=("low", "medium", "high", "blocked", "unknown"),
        default="low",
    )
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _keywords(text: str) -> list[str]:
    stop = {
        "about",
        "because",
        "from",
        "matters",
        "that",
        "this",
        "when",
        "why",
        "with",
        "your",
    }
    words: list[str] = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text):
        normalized = word.casefold()
        if len(normalized) < 3 or normalized in stop or normalized in words:
            continue
        words.append(normalized)
    return words[:6]


def _sample_unified(
    text: str,
    *,
    niche: str,
    hook_category: str,
    safety_risk: str,
) -> dict[str, Any]:
    readiness = "ready_with_low_risk" if safety_risk == "low" else "needs_manual_review"
    if safety_risk == "blocked":
        readiness = "not_ready"
    return {
        "story": {
            "story_shape": "problem_solution",
            "payoff": text,
            "ending_reason": "key_takeaway",
        },
        "virality": {
            "hook_line": text,
            "hook_category": hook_category,
            "overall_score": 0.76,
        },
        "trend_research": {
            "niche": niche,
            "research_status": "fallback",
            "provider_status": "fallback",
            "provider_used": "evergreen",
            "cache_status": "fallback",
            "live_research_succeeded": False,
            "source_count": 0,
            "matched_patterns": [{"label": "clear_takeaway"}],
            "confidence": 0.55,
        },
        "caption_intelligence": {"highlighted_words": _keywords(text)},
        "music_intelligence": {"role": "supportive_background"},
        "motion_graphics": {"motion_style": "subtle_punch_in"},
        "copyright_safety": {
            "risk_level": safety_risk,
            "upload_readiness": readiness,
            "manual_review_required": safety_risk != "low",
        },
    }


def _generate_sample(args: argparse.Namespace) -> dict[str, Any]:
    text = _text(args.sample_transcript)
    if not text:
        hook_category = str(args.hook_category).replace("_", " ")
        text = f"A focused {args.niche} clip with a {hook_category} opening."
    return dict(
        generate_upload_metadata(
            project_id="validation_project",
            clip_id="validation_clip",
            render_id=None,
            unified_clip_intelligence=_sample_unified(
                text,
                niche=str(args.niche),
                hook_category=str(args.hook_category),
                safety_risk=str(args.safety_risk),
            ),
            settings=get_settings().upload_metadata,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return raw


def _metadata_from_file(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if "upload_metadata_v2" in raw:
        return [_dict(raw.get("upload_metadata_v2"))]
    if "youtube_shorts" in raw:
        return [raw]
    clips = _list(raw.get("clips"))
    found = [
        _dict(_dict(item).get("upload_metadata_v2"))
        for item in clips
        if _dict(_dict(item).get("upload_metadata_v2"))
    ]
    if found:
        return found
    raise ValueError("No upload_metadata_v2 payload was found in the metadata file.")


def _metadata_from_manifest(raw: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    manifest = _dict(raw.get("manifest")) or dict(raw)
    project_id = _text(manifest.get("project_id")) or "manifest_project"
    render_id = _text(manifest.get("render_id")) or None
    outputs: list[dict[str, Any]] = []
    generated = False
    for render_value in _list(manifest.get("renders")):
        render = _dict(render_value)
        metadata = _dict(render.get("metadata"))
        existing = _dict(metadata.get("upload_metadata_v2"))
        if existing:
            outputs.append(existing)
            continue
        clip_id = _text(render.get("clip_id")) or "unknown_clip"
        unified = _dict(metadata.get("unified_clip_intelligence"))
        outputs.append(
            dict(
                generate_upload_metadata(
                    project_id=project_id,
                    clip_id=clip_id,
                    render_id=render_id,
                    unified_clip_intelligence=unified,
                    render_metadata=metadata,
                    settings=get_settings().upload_metadata,
                )
            )
        )
        generated = True
    if not outputs:
        raise ValueError("The render manifest contains no rendered clips.")
    return outputs, generated


def _report(mode: str, metadata: list[dict[str, Any]], *, generated: bool) -> dict[str, Any]:
    validations = [
        validate_upload_metadata(
            item,
            source_text=" ".join(
                _text(_dict(item.get("input_signals")).get(field))
                for field in ("transcript_excerpt_used", "hook_line", "clip_title_source")
            ),
            settings=get_settings().upload_metadata.model_dump(),
        )
        for item in metadata
    ]
    best_titles = [
        _text(_dict(item.get("universal")).get("best_title")) for item in metadata
    ]
    hashtag_counts = {
        "youtube_shorts": sum(
            len(_list(_dict(item.get("youtube_shorts")).get("hashtags"))) for item in metadata
        ),
        "instagram_reels": sum(
            len(_list(_dict(item.get("instagram_reels")).get("hashtags"))) for item in metadata
        ),
        "tiktok": sum(
            len(_list(_dict(item.get("tiktok")).get("hashtags"))) for item in metadata
        ),
    }
    warnings = [
        _text(warning)
        for validation in validations
        for warning in _list(validation.get("warnings"))
        if _text(warning)
    ]
    safety_statuses = [
        _text(_dict(item.get("input_signals")).get("safety_risk_level")) or "unknown"
        for item in metadata
    ]
    passed = bool(validations) and all(
        validation.get("passed") is True for validation in validations
    )
    return {
        "upload_metadata_validation_report": {
            "mode": mode,
            "generated": generated,
            "clip_count": len(metadata),
            "platforms": ["youtube_shorts", "instagram_reels", "tiktok"],
            "best_title": best_titles[0] if len(best_titles) == 1 else best_titles,
            "hashtag_count": hashtag_counts,
            "validation": validations[0] if len(validations) == 1 else validations,
            "safety_status": safety_statuses[0]
            if len(safety_statuses) == 1
            else safety_statuses,
            "warnings": list(dict.fromkeys(warnings)),
            "pass_fail": "pass" if passed else "fail",
        },
        "upload_metadata_v2": metadata[0] if len(metadata) == 1 else metadata,
    }


def main() -> int:
    args = _parse_args()
    try:
        generated = False
        if args.simulate or args.sample_transcript:
            metadata = [_generate_sample(args)]
            mode = "simulate" if args.simulate else "sample_transcript"
            generated = True
        elif args.metadata_file:
            metadata = _metadata_from_file(args.metadata_file.resolve())
            mode = "metadata_file"
        else:
            settings = get_settings()
            if args.manifest:
                manifest_path = args.manifest.resolve()
                mode = "manifest"
            else:
                storage_root = (args.storage_root or Path(settings.storage.local_root)).resolve()
                manifest_path = storage_root / "render" / str(args.project_id) / "index.json"
                mode = "project"
            metadata, generated = _metadata_from_manifest(_read_json(manifest_path))
        payload = _report(mode, metadata, generated=generated)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "upload_metadata_validation_report": {
                "mode": "error",
                "generated": False,
                "platforms": [],
                "best_title": None,
                "hashtag_count": {},
                "validation": None,
                "safety_status": "unknown",
                "warnings": [],
                "errors": [str(exc)],
                "pass_fail": "fail",
            }
        }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(f"{text}\n", encoding="utf-8")
    report = _dict(payload.get("upload_metadata_validation_report"))
    return 0 if report.get("pass_fail") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
