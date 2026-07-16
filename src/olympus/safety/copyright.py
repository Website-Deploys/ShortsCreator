"""Pure component checks used by Copyright / Safety Checker V2.

The checks enforce local provenance and license rules. They do not determine
fair use, predict Content ID, or provide legal approval.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from olympus.safety.contracts import RISK_PRIORITY, RiskLevel, UploadReadiness

JsonDict = dict[str, Any]

_STREAMING_HOST_TOKENS = (
    "youtube.com",
    "youtu.be",
    "spotify.com",
    "soundcloud.com",
    "tiktok.com",
    "instagram.com",
)
_RESTRICTED_AVAILABILITY = {
    "private",
    "premium_only",
    "subscriber_only",
    "members_only",
    "needs_auth",
    "login_required",
}
_GENERATED_SOURCE_PREFIXES = (
    "generated://olympus/",
    "project_generated",
    "generated_validation_asset",
    "generated_project_safe",
)


class SafetyPolicy(Protocol):
    """Configuration fields consumed by pure checker functions."""

    require_rights_confirmation_for_links: bool
    require_music_license_verified: bool
    require_sfx_license_verified: bool
    require_visual_asset_license_verified: bool
    warn_on_unknown_source: bool
    warn_on_generated_validation_music: bool
    require_manual_review_for_third_party_links: bool
    max_report_text_excerpt_chars: int


def check_source_video(source: JsonDict, policy: SafetyPolicy) -> JsonDict:
    """Assess source provenance without equating downloadability with permission."""

    source_type = _text(source.get("source_type")) or "unknown"
    source_url = _text(source.get("source_url"))
    platform = _text(source.get("platform")) or _platform(source_url)
    rights_confirmed = source.get("rights_confirmed") is True
    owner_claimed = source.get("owner_claimed_by_user") is True
    public_domain = source.get("public_domain_claimed") is True
    creative_commons = source.get("creative_commons_claimed") is True
    license_verified = source.get("license_verified") is True
    availability = (_text(source.get("availability")) or "").lower()
    restricted = bool(
        source.get("drm_protected") is True
        or source.get("private") is True
        or source.get("login_required") is True
        or source.get("member_only") is True
        or availability in _RESTRICTED_AVAILABILITY
    )
    warnings: list[str] = []
    manual_review = False

    if restricted:
        risk = RiskLevel.BLOCKED
        warnings.append("The source is DRM-protected, private, login-only, or restricted.")
        manual_review = True
    elif source_type in {"generated", "test", "synthetic"}:
        risk = RiskLevel.LOW
    elif source_type == "link" or platform != "unknown":
        if not rights_confirmed and policy.require_rights_confirmation_for_links:
            risk = RiskLevel.BLOCKED
            warnings.append("Required source-rights confirmation is missing for this link.")
            manual_review = True
        elif license_verified or public_domain or creative_commons:
            risk = RiskLevel.LOW
            manual_review = policy.require_manual_review_for_third_party_links
            if manual_review:
                warnings.append("Third-party license metadata still requires human verification.")
        else:
            risk = RiskLevel.MEDIUM
            manual_review = True
            warnings.append(
                "Rights were user-confirmed, but the third-party source license was not "
                "independently verified."
            )
    elif source_type in {"upload", "local_upload", "local"}:
        if rights_confirmed or owner_claimed:
            risk = RiskLevel.LOW
        else:
            risk = RiskLevel.UNKNOWN
            manual_review = True
            warnings.append("The uploaded source has no persisted ownership or permission basis.")
    else:
        risk = RiskLevel.UNKNOWN
        manual_review = True
        if policy.warn_on_unknown_source:
            warnings.append(
                "Source provenance is unavailable and cannot be verified automatically."
            )

    return {
        "source_type": source_type,
        "source_path": _text(source.get("source_path")),
        "source_url": source_url,
        "rights_confirmed": rights_confirmed,
        "rights_basis": _text(source.get("rights_basis")),
        "owner_claimed_by_user": owner_claimed,
        "public_domain_claimed": public_domain,
        "creative_commons_claimed": creative_commons,
        "license_url": _text(source.get("license_url")),
        "platform": platform,
        "source_risk_level": risk.value,
        "warnings": _unique(warnings),
        "manual_review_required": manual_review,
    }


def check_music(asset: JsonDict, *, used: bool, policy: SafetyPolicy) -> JsonDict:
    """Assess the actual selected music asset from manifest metadata."""

    normalized = normalize_asset(asset)
    warnings: list[str] = []
    if not used:
        risk = RiskLevel.LOW
    elif not normalized:
        risk = RiskLevel.UNKNOWN
        warnings.append("Music is present, but its asset and license metadata are missing.")
    elif _streaming_source(normalized):
        risk = RiskLevel.BLOCKED
        warnings.append("Streaming-platform music sources are not allowed for automatic use.")
    elif not normalized.get("license"):
        risk = RiskLevel.BLOCKED
        warnings.append("The mixed music asset has no license metadata.")
    elif policy.require_music_license_verified and normalized.get("license_verified") is not True:
        risk = RiskLevel.BLOCKED
        warnings.append("The mixed music license is not verified.")
    elif normalized.get("folder_type") in {"quarantine", "rejected"}:
        risk = RiskLevel.BLOCKED
        warnings.append("The music asset is stored in a blocked library folder.")
    elif normalized.get("path") and normalized.get("path_exists") is not True:
        risk = RiskLevel.BLOCKED
        warnings.append("The selected music asset file does not exist.")
    elif normalized.get("attribution_required") is True and not normalized.get("attribution_text"):
        risk = RiskLevel.HIGH
        warnings.append("Music attribution is required but attribution text is missing.")
    elif normalized.get("folder_type") not in {"curated", "generated", "user"}:
        risk = RiskLevel.HIGH
        warnings.append("The music asset is outside an approved library folder.")
    elif not normalized.get("source") and not normalized.get("source_url"):
        risk = RiskLevel.HIGH
        warnings.append("The music source record is missing.")
    elif normalized.get("safe_default") is not True:
        risk = RiskLevel.HIGH
        warnings.append("The music asset is not marked as a safe automatic default.")
    elif normalized.get("auto_select_allowed") is not True:
        risk = RiskLevel.HIGH
        warnings.append("The music asset is not approved for automatic selection.")
    elif normalized.get("quality_status") != "passed":
        risk = RiskLevel.HIGH
        warnings.append("The music asset has not passed library quality validation.")
    elif normalized.get("manual_review_required") is True:
        risk = RiskLevel.HIGH
        warnings.append("The music library marks this asset for manual review.")
    else:
        risk = RiskLevel.LOW
        if _generated_asset(normalized) and policy.warn_on_generated_validation_music:
            warnings.append(
                "Generated music has project-safe provenance but is validation-quality, not "
                "curated production music."
            )

    return {
        "used": used,
        "asset_id": normalized.get("asset_id") if normalized else None,
        "title": normalized.get("title") if normalized else None,
        "folder_type": normalized.get("folder_type") if normalized else None,
        "license": normalized.get("license") if normalized else None,
        "license_verified": normalized.get("license_verified") is True if normalized else False,
        "source": normalized.get("source") if normalized else None,
        "source_url": normalized.get("source_url") if normalized else None,
        "attribution_required": (
            normalized.get("attribution_required") is True if normalized else False
        ),
        "attribution_text": normalized.get("attribution_text") if normalized else None,
        "safe_default": normalized.get("safe_default") is True if normalized else False,
        "risk_level": risk.value,
        "warnings": _unique(warnings),
    }


def check_asset_collection(
    assets: Iterable[JsonDict],
    *,
    used: bool,
    kind: str,
    require_verified: bool,
) -> JsonDict:
    """Assess SFX or visual assets and retain only bounded provenance fields."""

    normalized_assets = [normalize_asset(item) for item in assets]
    normalized_assets = [item for item in normalized_assets if item]
    warnings: list[str] = []
    checked: list[JsonDict] = []
    risks: list[str] = []
    for asset in normalized_assets:
        asset_warnings: list[str] = []
        if _streaming_source(asset):
            risk = RiskLevel.BLOCKED
            asset_warnings.append("Streaming-platform asset source is not allowed.")
        elif not asset.get("license"):
            risk = RiskLevel.BLOCKED
            asset_warnings.append("License metadata is missing.")
        elif require_verified and asset.get("license_verified") is not True:
            risk = RiskLevel.BLOCKED
            asset_warnings.append("License metadata is not verified.")
        elif asset.get("path") and asset.get("path_exists") is not True:
            risk = RiskLevel.BLOCKED
            asset_warnings.append("The asset file does not exist.")
        elif asset.get("attribution_required") is True and not asset.get("attribution_text"):
            risk = RiskLevel.HIGH
            asset_warnings.append("Required attribution text is missing.")
        elif not asset.get("source") and not asset.get("source_url"):
            risk = RiskLevel.HIGH
            asset_warnings.append("Source provenance is missing.")
        elif asset.get("usage_allowed") is not True:
            risk = RiskLevel.HIGH
            asset_warnings.append("The asset is not marked as allowed for use.")
        elif asset.get("safe_default") is not True:
            risk = RiskLevel.HIGH
            asset_warnings.append("The asset is not marked as a safe default.")
        elif kind == "visual asset" and asset.get("folder_type") not in {
            "curated",
            "generated",
            "user",
        }:
            risk = RiskLevel.HIGH
            asset_warnings.append("The visual asset is outside an approved folder.")
        elif asset.get("quality_status") in {"failed", "rejected"}:
            risk = RiskLevel.HIGH
            asset_warnings.append("The asset failed quality validation.")
        else:
            risk = RiskLevel.LOW
        risks.append(risk.value)
        warnings.extend(
            f"{kind} {asset.get('asset_id') or 'asset'}: {item}"
            for item in asset_warnings
        )
        checked.append(
            {
                "asset_id": asset.get("asset_id"),
                "type": asset.get("type") or kind,
                "license": asset.get("license"),
                "license_verified": asset.get("license_verified") is True,
                "source": asset.get("source"),
                "source_url": asset.get("source_url"),
                "generated_project_safe": _generated_asset(asset),
                "safe_default": asset.get("safe_default") is True,
                "risk_level": risk.value,
                "warnings": asset_warnings,
            }
        )

    if not used:
        overall_risk = RiskLevel.LOW.value
    elif not checked:
        overall_risk = RiskLevel.UNKNOWN.value
        warnings.append(f"{kind.upper()} are present, but provenance metadata is unavailable.")
    else:
        overall_risk = highest_risk(risks)
    return {
        "used": used,
        "assets": checked,
        "all_license_verified": bool(
            not used or (checked and all(item.get("license_verified") is True for item in checked))
        ),
        "risk_level": overall_risk,
        "warnings": _unique(warnings),
    }


def check_captions_text(text_context: JsonDict, source_check: JsonDict) -> JsonDict:
    """Apply conservative text-risk heuristics without retaining transcript text."""

    lines = [
        line
        for item in _list(text_context.get("lines"))
        if (line := _text(item)) is not None
    ]
    copied = text_context.get("copied_text_detected") is True
    lyric_risk = bool(
        text_context.get("lyric_risk_detected") is True
        or text_context.get("caption_type") == "lyrics"
        or text_context.get("source_audio_type") in {"music", "singing", "song"}
        or _repeated_lyric_like_lines(lines)
    )
    excessive_quotes = bool(
        text_context.get("excessive_quoted_text_detected") is True
        or any(len(line) >= 80 and line.count('"') >= 2 for line in lines)
    )
    warnings: list[str] = []
    if copied:
        risk = RiskLevel.HIGH
        warnings.append("Text metadata indicates copied third-party wording or script content.")
    elif lyric_risk:
        risk = RiskLevel.MEDIUM
        warnings.append("Caption text may be lyric-like; manual review is required.")
    elif excessive_quotes:
        risk = RiskLevel.MEDIUM
        warnings.append("Caption or publishing text contains unusually long quoted material.")
    elif source_check.get("source_risk_level") == RiskLevel.BLOCKED.value:
        risk = RiskLevel.HIGH
        warnings.append("Transcript-derived captions inherit unresolved source-rights risk.")
    else:
        risk = RiskLevel.LOW
    return {
        "generated_from_transcript": text_context.get("generated_from_transcript") is True,
        "copied_text_detected": copied,
        "lyric_risk_detected": lyric_risk,
        "excessive_quoted_text_detected": excessive_quotes,
        "risk_level": risk.value,
        "warnings": _unique(warnings),
    }


def check_final_output(
    output: JsonDict,
    *,
    component_risks: Iterable[str],
) -> JsonDict:
    """Aggregate the ingredients that actually appear in the rendered output."""

    rendered_file = _text(output.get("rendered_file"))
    risks = list(component_risks)
    risk = highest_risk(risks)
    warnings: list[str] = []
    if not rendered_file:
        warnings.append("No rendered output was supplied; this is a pre-render assessment.")
    if output.get("render_exists") is False:
        risk = RiskLevel.UNKNOWN.value
        warnings.append("The reported rendered file does not exist.")
    return {
        "rendered_file": rendered_file,
        "duration_seconds": _number(output.get("duration_seconds")),
        "contains_music": output.get("contains_music") is True,
        "contains_sfx": output.get("contains_sfx") is True,
        "contains_external_assets": output.get("contains_external_assets") is True,
        "contains_source_audio": output.get("contains_source_audio") is not False,
        "contains_source_video": output.get("contains_source_video") is not False,
        "risk_level": risk,
        "warnings": _unique(warnings),
    }


def platform_readiness(
    *,
    overall_risk: str,
    source_check: JsonDict,
    output: JsonDict,
) -> JsonDict:
    """Return technical readiness warnings without predicting platform decisions."""

    platforms: JsonDict = {}
    shared_warnings = [
        "Platform copyright and music rules can change and require final human review.",
        "This assessment cannot predict Content ID or platform moderation decisions.",
    ]
    blocked_reasons = []
    if overall_risk == RiskLevel.BLOCKED.value:
        blocked_reasons.append("A blocked source or asset component is present.")
    third_party = source_check.get("source_type") == "link"
    for platform in ("youtube_shorts", "instagram_reels", "tiktok"):
        warnings = list(shared_warnings)
        if third_party:
            warnings.append("Third-party source rights require manual review before publishing.")
        if platform == "youtube_shorts" and output.get("rendered_file"):
            width = _number(output.get("width"))
            height = _number(output.get("height"))
            duration = _number(output.get("duration_seconds"))
            if width is not None and height is not None and width >= height:
                warnings.append("The output is not vertical short-form video.")
            if duration is not None and duration > 180:
                warnings.append(
                    "The output exceeds the checker's conservative short-form duration."
                )
        status = _readiness_for_risk(overall_risk)
        platforms[platform] = {
            "platform": platform,
            "status": status,
            "warnings": _unique(warnings),
            "blocked_reasons": list(blocked_reasons),
            "manual_review_required": bool(
                third_party or status != UploadReadiness.READY_WITH_LOW_RISK.value
            ),
        }
    platforms["warnings"] = list(shared_warnings)
    platforms["blocked_reasons"] = blocked_reasons
    return platforms


def highest_risk(risks: Iterable[str]) -> str:
    """Return the highest calibrated risk, keeping unknown below explicit medium."""

    normalized = [risk if risk in RISK_PRIORITY else RiskLevel.UNKNOWN.value for risk in risks]
    if not normalized:
        return RiskLevel.UNKNOWN.value
    return max(normalized, key=lambda item: RISK_PRIORITY[item])


def normalize_asset(asset: JsonDict) -> JsonDict:
    """Flatten common render/library license shapes into bounded provenance fields."""

    if not asset:
        return {}
    license_data = _dict(asset.get("license"))
    source_url = _text(asset.get("source_url") or license_data.get("source_url"))
    source = _text(asset.get("source") or license_data.get("source"))
    generated = _generated_source(source, source_url)
    license_name = _text(
        license_data.get("license")
        or asset.get("license_name")
        or (asset.get("license") if isinstance(asset.get("license"), str) else None)
    )
    explicit_verified = asset.get("license_verified") is True or license_data.get(
        "license_verified"
    ) is True
    usage_allowed = asset.get("usage_allowed") is True or license_data.get("usage_allowed") is True
    path = _text(asset.get("path") or asset.get("absolute_path"))
    folder_type = _text(asset.get("folder_type"))
    if not folder_type and generated:
        folder_type = "generated"
    return {
        "asset_id": _text(asset.get("asset_id") or asset.get("id")),
        "title": _text(asset.get("title") or asset.get("filename")),
        "type": _text(asset.get("type")),
        "folder_type": folder_type,
        "path": path,
        "path_exists": Path(path).is_file() if path else None,
        "license": license_name,
        "license_verified": bool(
            explicit_verified or (generated and usage_allowed and bool(license_name))
        ),
        "source": source,
        "source_url": source_url,
        "attribution_required": bool(
            asset.get("attribution_required") is True
            or license_data.get("attribution_required") is True
        ),
        "attribution_text": _text(
            asset.get("attribution_text")
            or asset.get("attribution")
            or license_data.get("attribution_text")
            or license_data.get("attribution")
        ),
        "safe_default": bool(
            asset.get("safe_default") is True
            or license_data.get("safe_default") is True
            or (generated and usage_allowed)
        ),
        "auto_select_allowed": asset.get("auto_select_allowed") is True,
        "manual_review_required": asset.get("manual_review_required") is True,
        "usage_allowed": usage_allowed,
        "quality_status": _text(asset.get("quality_status") or asset.get("quality")),
        "generated_project_safe": generated,
    }


def _readiness_for_risk(risk: str) -> str:
    if risk == RiskLevel.LOW.value:
        return UploadReadiness.READY_WITH_LOW_RISK.value
    if risk in {RiskLevel.MEDIUM.value, RiskLevel.UNKNOWN.value}:
        return UploadReadiness.NEEDS_MANUAL_REVIEW.value
    if risk == RiskLevel.HIGH.value:
        return UploadReadiness.NOT_READY.value
    return UploadReadiness.BLOCKED.value


def _platform(url: str | None) -> str:
    if not url:
        return "unknown"
    host = (urlparse(url).hostname or "").lower()
    if "youtube" in host or host == "youtu.be":
        return "youtube"
    if "tiktok" in host:
        return "tiktok"
    if "instagram" in host:
        return "instagram"
    return host or "unknown"


def _streaming_source(asset: JsonDict) -> bool:
    value = f"{asset.get('source') or ''} {asset.get('source_url') or ''}".lower()
    return any(token in value for token in _STREAMING_HOST_TOKENS)


def _generated_asset(asset: JsonDict) -> bool:
    return bool(
        asset.get("generated_project_safe") is True
        or _generated_source(_text(asset.get("source")), _text(asset.get("source_url")))
    )


def _generated_source(source: str | None, source_url: str | None) -> bool:
    value = f"{source or ''} {source_url or ''}".lower()
    return any(token in value for token in _GENERATED_SOURCE_PREFIXES)


def _repeated_lyric_like_lines(lines: list[str]) -> bool:
    normalized = [" ".join(line.lower().split()) for line in lines if len(line.split()) >= 3]
    counts = Counter(normalized)
    return any(count >= 3 for count in counts.values())


def _unique(values: Iterable[str]) -> list[str]:
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
