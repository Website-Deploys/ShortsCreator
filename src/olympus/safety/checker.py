"""Orchestration and reporting for Copyright / Safety Checker V2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olympus.safety.contracts import (
    BASE_MANUAL_REVIEW_CHECKLIST,
    CHECKER_VERSION,
    COPYRIGHT_SAFETY_DISCLAIMER,
    CopyrightSafetyReport,
    RiskLevel,
    UploadReadiness,
)
from olympus.safety.copyright import (
    SafetyPolicy,
    check_asset_collection,
    check_captions_text,
    check_final_output,
    check_music,
    check_source_video,
    highest_risk,
    platform_readiness,
)

JsonDict = dict[str, Any]


class CopyrightSafetyChecker:
    """Build one honest component and final-output risk report."""

    def __init__(self, policy: SafetyPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> SafetyPolicy:
        """Return the active immutable-by-convention policy for validation tools."""

        return self._policy

    def check(
        self,
        *,
        project: JsonDict | None = None,
        clip_id: str | None = None,
        timeline: JsonDict | None = None,
        render_metadata: JsonDict | None = None,
        render_output: JsonDict | None = None,
        link_record: JsonDict | None = None,
        source: JsonDict | None = None,
        music_asset: JsonDict | None = None,
        sfx_assets: list[JsonDict] | None = None,
        visual_assets: list[JsonDict] | None = None,
        text_context: JsonDict | None = None,
        assessment_phase: str = "final_output",
    ) -> CopyrightSafetyReport:
        """Assess supplied truth without assuming fair use or platform approval."""

        project = _dict(project)
        timeline = _dict(timeline)
        render_metadata = _dict(render_metadata)
        render_output = _dict(render_output)
        link_record = _dict(link_record)
        project_id = _text(project.get("id") or timeline.get("project_id"))
        clip_id = clip_id or _text(
            render_output.get("clip_id") or timeline.get("clip_id") or timeline.get("plan_id")
        )
        if getattr(self._policy, "enabled", True) is False:
            return _disabled_report(project_id, clip_id, assessment_phase)

        source_input = _source_context(project, link_record, _dict(source))
        source_check = check_source_video(source_input, self._policy)
        component_metadata = {
            **_dict(timeline.get("metadata")),
            **render_metadata,
        }
        music_used, extracted_music = _music_context(component_metadata)
        music_check = check_music(
            _merge(extracted_music, _dict(music_asset)),
            used=music_used if music_asset is None else bool(music_used or music_asset),
            policy=self._policy,
        )
        extracted_sfx = _sfx_context(component_metadata)
        if sfx_assets is not None:
            extracted_sfx = sfx_assets
        sfx_used = bool(_number(render_metadata.get("sfx_mixed_count")) or extracted_sfx)
        sfx_check = check_asset_collection(
            extracted_sfx,
            used=sfx_used,
            kind="sfx",
            require_verified=self._policy.require_sfx_license_verified,
        )
        extracted_visuals = _visual_context(component_metadata)
        if visual_assets is not None:
            extracted_visuals = visual_assets
        visual_used = bool(extracted_visuals)
        visual_check = check_asset_collection(
            extracted_visuals,
            used=visual_used,
            kind="visual asset",
            require_verified=self._policy.require_visual_asset_license_verified,
        )
        captions = _text_context(timeline, component_metadata, _dict(text_context))
        captions_check = check_captions_text(captions, source_check)

        component_risks = [
            str(source_check["source_risk_level"]),
            str(music_check["risk_level"]),
            str(sfx_check["risk_level"]),
            str(visual_check["risk_level"]),
            str(captions_check["risk_level"]),
        ]
        output_context = _output_context(
            render_metadata,
            render_output,
            music_used=music_used,
            sfx_used=sfx_used,
            visual_used=visual_used,
        )
        final_output = check_final_output(output_context, component_risks=component_risks)
        overall_risk = highest_risk([*component_risks, str(final_output["risk_level"])])
        warnings = _unique(
            [
                *source_check["warnings"],
                *music_check["warnings"],
                *sfx_check["warnings"],
                *visual_check["warnings"],
                *captions_check["warnings"],
                *final_output["warnings"],
            ]
        )
        blocked_reasons = _blocked_reasons(
            source_check,
            music_check,
            sfx_check,
            visual_check,
            captions_check,
        )
        requires_review = bool(
            source_check["manual_review_required"]
            or overall_risk != RiskLevel.LOW.value
            or source_check["source_type"] == "link"
            or warnings
        )
        readiness = _upload_readiness(overall_risk)
        platform = platform_readiness(
            overall_risk=overall_risk,
            source_check=source_check,
            output=output_context,
        )
        review_reasons = _review_reasons(
            source_check,
            music_check,
            sfx_check,
            visual_check,
            captions_check,
            blocked_reasons,
        )
        report_id = _report_id(project_id, clip_id, assessment_phase, output_context)
        return CopyrightSafetyReport(
            report_id=report_id,
            project_id=project_id,
            clip_id=clip_id,
            created_at=datetime.now(UTC).isoformat(),
            checker_version=CHECKER_VERSION,
            overall={
                "risk_level": overall_risk,
                "upload_readiness": readiness,
                "confidence": _confidence(
                    source_check,
                    music_check,
                    sfx_check,
                    visual_check,
                    assessment_phase,
                ),
                "requires_manual_review": requires_review,
                "can_auto_clear": bool(
                    overall_risk == RiskLevel.LOW.value
                    and not requires_review
                    and not blocked_reasons
                ),
                "summary": _summary(overall_risk, requires_review),
                "disclaimer": COPYRIGHT_SAFETY_DISCLAIMER,
                "assessment_phase": assessment_phase,
            },
            source_video=source_check,
            music=music_check,
            sfx=sfx_check,
            visual_assets={
                "overlays_used": visual_used,
                **visual_check,
            },
            captions_text=captions_check,
            final_output=final_output,
            platform_readiness=platform,
            manual_review={
                "required": requires_review,
                "reasons": review_reasons,
                "checklist": list(BASE_MANUAL_REVIEW_CHECKLIST) if requires_review else [],
            },
            result={
                "passed": overall_risk != RiskLevel.BLOCKED.value,
                "warnings": warnings,
                "errors": blocked_reasons,
            },
        )

    def should_block(self, report: Mapping[str, Any]) -> bool:
        """Apply configured enforcement without changing the calibrated risk."""

        if getattr(self._policy, "warn_only", False):
            return False
        risk = _text(_dict(report.get("overall")).get("risk_level"))
        if risk == RiskLevel.BLOCKED.value:
            return bool(getattr(self._policy, "block_on_blocked", True))
        if risk == RiskLevel.HIGH.value:
            return bool(getattr(self._policy, "block_on_high_risk", False))
        return False


def write_copyright_safety_reports(payload: JsonDict, report_dir: Path) -> dict[str, str]:
    """Write the fixed JSON and Markdown report names used by the CLI."""

    report_dir.mkdir(parents=True, exist_ok=True)
    envelope = payload if "copyright_safety_v2" in payload else {"copyright_safety_v2": payload}
    json_path = report_dir / "copyright_safety_report.json"
    markdown_path = report_dir / "copyright_safety_summary.md"
    json_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(copyright_safety_markdown(envelope), encoding="utf-8")
    return {
        "copyright_safety_report.json": str(json_path.resolve()),
        "copyright_safety_summary.md": str(markdown_path.resolve()),
    }


def copyright_safety_markdown(payload: JsonDict) -> str:
    """Render a bounded human-readable safety summary."""

    report = _dict(payload.get("copyright_safety_v2")) or payload
    overall = _dict(report.get("overall"))
    source = _dict(report.get("source_video"))
    music = _dict(report.get("music"))
    sfx = _dict(report.get("sfx"))
    visual = _dict(report.get("visual_assets"))
    text = _dict(report.get("captions_text"))
    manual = _dict(report.get("manual_review"))
    result = _dict(report.get("result"))
    lines = [
        "# Olympus Copyright / Safety Checker V2",
        "",
        f"> {COPYRIGHT_SAFETY_DISCLAIMER}",
        "",
        f"- Report ID: `{report.get('report_id') or 'not_available'}`",
        f"- Project: `{report.get('project_id') or 'not_available'}`",
        f"- Clip: `{report.get('clip_id') or 'not_available'}`",
        f"- Risk level: `{overall.get('risk_level') or 'unknown'}`",
        f"- Upload readiness: `{overall.get('upload_readiness') or 'unknown'}`",
        f"- Manual review required: `{manual.get('required') is True}`",
        f"- Source rights confirmed: `{source.get('rights_confirmed') is True}`",
        f"- Music license verified: `{music.get('license_verified') is True}`",
        f"- SFX licenses verified: `{sfx.get('all_license_verified') is True}`",
        f"- Visual licenses verified: `{visual.get('all_license_verified') is True}`",
        f"- Lyric-like text warning: `{text.get('lyric_risk_detected') is True}`",
        "",
        "## Summary",
        "",
        str(overall.get("summary") or "No aggregate summary is available."),
        "",
        "## Warnings",
        "",
    ]
    warnings = [str(item) for item in _list(result.get("warnings")) if str(item)]
    lines.extend(f"- {item}" for item in warnings[:30])
    if not warnings:
        lines.append("- No technical warnings were recorded.")
    lines.extend(["", "## Manual Review", ""])
    checklist = [str(item) for item in _list(manual.get("checklist")) if str(item)]
    lines.extend(f"- [ ] {item}" for item in checklist)
    if not checklist:
        lines.append("- Manual review was not required by the available metadata.")
    lines.extend(
        [
            "",
            "This report does not determine fair use, legal ownership, Content ID results, or "
            "platform approval.",
            "",
        ]
    )
    return "\n".join(lines)


def _source_context(project: JsonDict, link_record: JsonDict, explicit: JsonDict) -> JsonDict:
    if explicit:
        return explicit
    rights = _dict(link_record.get("rights_confirmation"))
    link_source = _dict(link_record.get("link_source"))
    video_metadata = _dict(link_record.get("video_metadata"))
    source_type = _text(project.get("source_type")) or "upload"
    rights_confirmed = rights.get("confirmed") is True
    return {
        "source_type": source_type,
        "source_path": _text(project.get("storage_key")),
        "source_url": _text(project.get("source_url") or link_record.get("url")),
        "rights_confirmed": rights_confirmed,
        "rights_basis": _text(rights.get("basis"))
        or ("user_rights_confirmation" if rights_confirmed else None),
        "owner_claimed_by_user": rights.get("owner_claimed_by_user") is True,
        "public_domain_claimed": rights.get("public_domain_claimed") is True,
        "creative_commons_claimed": rights.get("creative_commons_claimed") is True,
        "license_url": _text(video_metadata.get("license_url")),
        "license_verified": video_metadata.get("license_verified") is True,
        "platform": _text(link_source.get("platform")),
        "availability": _text(video_metadata.get("availability")),
        "drm_protected": bool(
            video_metadata.get("has_drm") is True or link_source.get("has_drm") is True
        ),
        "private": video_metadata.get("availability") == "private",
        "login_required": video_metadata.get("availability") in {"needs_auth", "login_required"},
        "member_only": video_metadata.get("availability") in {
            "premium_only",
            "subscriber_only",
        },
    }


def _music_context(metadata: JsonDict) -> tuple[bool, JsonDict]:
    effects = _dict(metadata.get("render_effects_v2"))
    music = _dict(effects.get("music"))
    intelligence = _dict(
        music.get("music_intelligence_v2") or metadata.get("music_intelligence_v2")
    )
    selected = _dict(intelligence.get("selected_asset"))
    direct = {
        "asset_id": music.get("asset_id"),
        "title": music.get("title") or music.get("filename"),
        "folder_type": music.get("folder_type"),
        "license": music.get("license"),
        "source": music.get("source"),
        "source_url": music.get("source_url"),
        "safe_default": music.get("safe_default"),
        "license_verified": music.get("license_verified"),
        "usage_allowed": music.get("usage_allowed"),
    }
    used = metadata.get("music_mixed") is True or music.get("mixed") is True
    return used, _merge(direct, selected)


def _sfx_context(metadata: JsonDict) -> list[JsonDict]:
    sfx = _dict(_dict(metadata.get("render_effects_v2")).get("sfx"))
    return [
        _dict(item)
        for item in _list(sfx.get("events"))
        if _dict(item) and _dict(item).get("mixed") is not False
    ]


def _visual_context(metadata: JsonDict) -> list[JsonDict]:
    effects = _dict(metadata.get("render_effects_v2"))
    visual = effects.get("visual_assets") or effects.get("overlays")
    if isinstance(visual, dict):
        visual = visual.get("assets")
    return [_dict(item) for item in _list(visual) if _dict(item)]


def _text_context(timeline: JsonDict, metadata: JsonDict, explicit: JsonDict) -> JsonDict:
    if explicit:
        return explicit
    lines: list[str] = []
    for track in _list(timeline.get("tracks")):
        track_data = _dict(track)
        if _text(track_data.get("kind")) not in {"captions", "caption", "subtitle"}:
            continue
        for event in _list(track_data.get("events")):
            event_data = _dict(event)
            text = _text(event_data.get("text"))
            if text:
                lines.append(text[:500])
    caption_intelligence = _dict(metadata.get("caption_intelligence_v2"))
    source_audio_type = _text(
        _dict(_dict(metadata.get("music_intelligence_v2")).get("input_signals")).get(
            "source_audio_type"
        )
    )
    return {
        "generated_from_transcript": bool(lines or caption_intelligence),
        "lines": lines[:50],
        "copied_text_detected": caption_intelligence.get("copied_text_detected") is True,
        "lyric_risk_detected": caption_intelligence.get("lyric_risk_detected") is True,
        "excessive_quoted_text_detected": (
            caption_intelligence.get("excessive_quoted_text_detected") is True
        ),
        "caption_type": caption_intelligence.get("caption_type"),
        "source_audio_type": source_audio_type,
    }


def _output_context(
    metadata: JsonDict,
    render_output: JsonDict,
    *,
    music_used: bool,
    sfx_used: bool,
    visual_used: bool,
) -> JsonDict:
    rendered_file = _text(
        render_output.get("rendered_file")
        or render_output.get("output_key")
        or render_output.get("storage_key")
    )
    return {
        "rendered_file": rendered_file,
        "render_exists": render_output.get("render_exists"),
        "duration_seconds": render_output.get("duration")
        or render_output.get("duration_seconds")
        or _dict(metadata.get("duration_validation")).get("actual_container_duration"),
        "width": render_output.get("width"),
        "height": render_output.get("height"),
        "contains_music": music_used,
        "contains_sfx": sfx_used,
        "contains_external_assets": visual_used,
        "contains_source_audio": render_output.get("has_audio") is not False,
        "contains_source_video": bool(rendered_file),
    }


def _blocked_reasons(*components: JsonDict) -> list[str]:
    reasons: list[str] = []
    for component in components:
        risk = component.get("risk_level") or component.get("source_risk_level")
        if risk != RiskLevel.BLOCKED.value:
            continue
        reasons.extend(str(item) for item in _list(component.get("warnings")) if str(item))
    return _unique(reasons)


def _review_reasons(
    source: JsonDict,
    music: JsonDict,
    sfx: JsonDict,
    visual: JsonDict,
    text: JsonDict,
    blocked: list[str],
) -> list[str]:
    reasons = list(blocked)
    if source.get("manual_review_required") is True:
        reasons.append("Source ownership, permission, or license requires human confirmation.")
    for label, component in (
        ("Music", music),
        ("SFX", sfx),
        ("Visual assets", visual),
        ("Captions/text", text),
    ):
        if component.get("risk_level") not in {None, RiskLevel.LOW.value}:
            reasons.append(f"{label} risk is {component.get('risk_level')}.")
    return _unique(reasons)


def _confidence(
    source: JsonDict,
    music: JsonDict,
    sfx: JsonDict,
    visual: JsonDict,
    phase: str,
) -> float:
    score = 0.45
    if source.get("source_risk_level") != RiskLevel.UNKNOWN.value:
        score += 0.2
    if not music.get("used") or music.get("asset_id"):
        score += 0.1
    if not sfx.get("used") or sfx.get("assets"):
        score += 0.1
    if not visual.get("used") or visual.get("assets"):
        score += 0.05
    if phase == "final_output":
        score += 0.1
    return round(min(0.95, score), 3)


def _upload_readiness(risk: str) -> str:
    if risk == RiskLevel.LOW.value:
        return UploadReadiness.READY_WITH_LOW_RISK.value
    if risk in {RiskLevel.MEDIUM.value, RiskLevel.UNKNOWN.value}:
        return UploadReadiness.NEEDS_MANUAL_REVIEW.value
    if risk == RiskLevel.HIGH.value:
        return UploadReadiness.NOT_READY.value
    return UploadReadiness.BLOCKED.value


def _summary(risk: str, requires_review: bool) -> str:
    if risk == RiskLevel.LOW.value:
        return (
            "Available provenance and license metadata indicate low technical risk; platform "
            "approval is not guaranteed."
        )
    if risk == RiskLevel.MEDIUM.value:
        return "The output needs manual review because permissions or license scope are unclear."
    if risk == RiskLevel.HIGH.value:
        return "High-risk provenance or license issues should be resolved before publishing."
    if risk == RiskLevel.BLOCKED.value:
        return "A blocked source or asset condition prevents automatic clearance."
    suffix = " Manual review is required." if requires_review else ""
    return "Important provenance or license metadata is unavailable." + suffix


def _report_id(
    project_id: str | None,
    clip_id: str | None,
    phase: str,
    output: JsonDict,
) -> str:
    seed = "|".join(
        [
            project_id or "project_unknown",
            clip_id or "clip_unknown",
            phase,
            _text(output.get("rendered_file")) or "not_rendered",
        ]
    )
    return "safety_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _disabled_report(
    project_id: str | None,
    clip_id: str | None,
    phase: str,
) -> CopyrightSafetyReport:
    warning = "Copyright / Safety Checker V2 is disabled by configuration."
    return CopyrightSafetyReport(
        report_id=_report_id(project_id, clip_id, phase, {}),
        project_id=project_id,
        clip_id=clip_id,
        created_at=datetime.now(UTC).isoformat(),
        checker_version=CHECKER_VERSION,
        overall={
            "risk_level": RiskLevel.UNKNOWN.value,
            "upload_readiness": UploadReadiness.UNKNOWN.value,
            "confidence": 0.0,
            "requires_manual_review": True,
            "can_auto_clear": False,
            "summary": warning,
            "disclaimer": COPYRIGHT_SAFETY_DISCLAIMER,
            "assessment_phase": phase,
        },
        source_video={
            "source_type": "unknown",
            "source_path": None,
            "source_url": None,
            "rights_confirmed": False,
            "rights_basis": None,
            "owner_claimed_by_user": False,
            "public_domain_claimed": False,
            "creative_commons_claimed": False,
            "license_url": None,
            "platform": "unknown",
            "source_risk_level": RiskLevel.UNKNOWN.value,
            "warnings": [warning],
            "manual_review_required": True,
        },
        music={"used": False, "risk_level": RiskLevel.UNKNOWN.value, "warnings": [warning]},
        sfx={"used": False, "risk_level": RiskLevel.UNKNOWN.value, "warnings": [warning]},
        visual_assets={
            "overlays_used": False,
            "used": False,
            "risk_level": RiskLevel.UNKNOWN.value,
            "warnings": [warning],
        },
        captions_text={
            "generated_from_transcript": False,
            "copied_text_detected": False,
            "lyric_risk_detected": False,
            "excessive_quoted_text_detected": False,
            "risk_level": RiskLevel.UNKNOWN.value,
            "warnings": [warning],
        },
        final_output={
            "rendered_file": None,
            "risk_level": RiskLevel.UNKNOWN.value,
            "warnings": [warning],
        },
        platform_readiness={
            platform: {
                "platform": platform,
                "status": UploadReadiness.UNKNOWN.value,
                "warnings": [warning],
                "blocked_reasons": [],
                "manual_review_required": True,
            }
            for platform in ("youtube_shorts", "instagram_reels", "tiktok")
        },
        manual_review={
            "required": True,
            "reasons": [warning],
            "checklist": list(BASE_MANUAL_REVIEW_CHECKLIST),
        },
        result={"passed": True, "warnings": [warning], "errors": []},
    )


def _merge(base: JsonDict, override: JsonDict) -> JsonDict:
    return {**{key: value for key, value in base.items() if value is not None}, **override}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
