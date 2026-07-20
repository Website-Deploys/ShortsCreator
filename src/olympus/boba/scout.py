"""Metadata-only candidate scouting for BOBA Scout V1."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory_contracts import BobaMemoryRecordV1
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

BobaCandidateSourceType = Literal[
    "manual_link",
    "manual_metadata",
    "json_import",
    "csv_import",
    "official_api_metadata",
]
BobaRightsStatus = Literal[
    "unknown",
    "user_owned",
    "permission_confirmed",
    "licensed",
    "not_allowed",
]
BobaCandidateStatus = Literal[
    "idea_only",
    "approved_for_review",
    "approved_for_processing",
    "rejected",
    "archived",
]
BobaScoutRecommendedAction = Literal[
    "idea_only",
    "review_rights_first",
    "approve_for_review",
    "process_now",
    "do_not_process",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CURIOSITY_TERMS = {
    "why",
    "how",
    "secret",
    "truth",
    "mistake",
    "unexpected",
    "nobody",
    "never",
    "what happens",
    "the reason",
}
_EMOTION_TERMS = {
    "breakthrough",
    "failure",
    "fear",
    "hope",
    "loss",
    "love",
    "motivation",
    "motivational",
    "pain",
    "success",
    "surprising",
    "transformation",
}
_NOVELTY_TERMS = {"first", "myth", "new", "surprising", "unexpected", "unusual"}
_MAX_IMPORT_BYTES = 2_000_000
_SCOUT_MEMORY_PROJECT_ID = "boba_scout"


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
    return text[:60]


def _metadata_score(metadata: Mapping[str, JsonValue], *names: str) -> float | None:
    for name in names:
        if name in metadata:
            return _clamp(_number(metadata[name]))
    return None


class BobaCandidateV1(BobaContract):
    candidate_id: str = Field(
        default_factory=lambda: f"candidate_{uuid4().hex[:20]}",
        min_length=1,
        max_length=128,
    )
    source_type: BobaCandidateSourceType = "manual_metadata"
    title: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=2_048)
    creator: str = Field(default="", max_length=200)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=172_800.0)
    published_at: str | None = Field(default=None, max_length=80)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    rights_status: BobaRightsStatus = "unknown"
    permission_confirmed: bool = False
    status: BobaCandidateStatus = "idea_only"
    created_at: str = Field(default_factory=now_iso)

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("candidate_id may contain only letters, numbers, '_' and '-'")
        return value

    @field_validator("url")
    @classmethod
    def validate_metadata_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("candidate URL must be an absolute HTTP or HTTPS URL")
        return value

    @model_validator(mode="after")
    def enforce_rights_gate(self) -> BobaCandidateV1:
        if self.source_type == "manual_link" and not self.url:
            raise ValueError("manual_link candidates require a URL")
        if self.status == "approved_for_processing" and not self.processing_permitted:
            raise ValueError(
                "approved_for_processing requires confirmed permission and an allowed rights status"
            )
        if self.rights_status == "not_allowed" and self.status not in {
            "idea_only",
            "rejected",
            "archived",
        }:
            raise ValueError("not_allowed candidates cannot be approved")
        return self

    @property
    def processing_permitted(self) -> bool:
        return self.permission_confirmed and self.rights_status in {
            "user_owned",
            "permission_confirmed",
            "licensed",
        }


class BobaScoutScoreV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    overall_score: float = Field(ge=0.0, le=1.0)
    hook_potential: float = Field(ge=0.0, le=1.0)
    emotional_potential: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    clarity_score: float = Field(ge=0.0, le=1.0)
    clipping_potential: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    recommended_action: BobaScoutRecommendedAction


def candidate_traits(candidate: BobaCandidateV1) -> set[str]:
    metadata = candidate.metadata
    traits: set[str] = set()
    topic = metadata.get("topic") or metadata.get("category") or metadata.get("niche")
    emotion = metadata.get("emotion") or metadata.get("target_emotion")
    if topic and (value := _slug(topic)):
        traits.add(f"topic:{value}")
    if emotion and (value := _slug(emotion)):
        traits.add(f"emotion:{value}")
    title = candidate.title.casefold()
    if any(term in title for term in _CURIOSITY_TERMS) or "?" in candidate.title:
        traits.add("hook:curiosity")
    if any(term in title for term in _EMOTION_TERMS):
        traits.add("emotion:high")
    explicit_emotion = _metadata_score(metadata, "emotional_potential", "emotion_score")
    if explicit_emotion is not None:
        traits.add("emotion:high" if explicit_emotion >= 0.6 else "emotion:low")
    duration = candidate.duration_seconds
    if duration is not None:
        if duration <= 300:
            traits.add("duration:short")
        elif duration <= 1_800:
            traits.add("duration:medium")
        else:
            traits.add("duration:long")
    return traits


class BobaScout:
    """Persist and score metadata without downloading or inspecting media."""

    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store

    def create_candidate(
        self, candidate: BobaCandidateV1 | Mapping[str, object]
    ) -> BobaCandidateV1:
        validated = (
            candidate
            if isinstance(candidate, BobaCandidateV1)
            else BobaCandidateV1.model_validate(candidate)
        )
        self.store.save_scout_candidate(validated)
        return validated

    def list_candidates(self) -> list[BobaCandidateV1]:
        return self.store.list_scout_candidates()

    def import_candidates(self, path: str | Path) -> list[BobaCandidateV1]:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValidationError("BOBA candidate import file was not found.")
        if source.stat().st_size > _MAX_IMPORT_BYTES:
            raise ValidationError("BOBA candidate import exceeds the 2 MB limit.")
        suffix = source.suffix.casefold()
        if suffix == ".json":
            raw = json.loads(source.read_text(encoding="utf-8-sig"))
            values = raw.get("candidates", []) if isinstance(raw, dict) else raw
            source_type: BobaCandidateSourceType = "json_import"
        elif suffix == ".csv":
            with source.open("r", encoding="utf-8-sig", newline="") as handle:
                values = list(csv.DictReader(handle))
            source_type = "csv_import"
        else:
            raise ValidationError("BOBA candidate import supports only JSON and CSV.")
        if not isinstance(values, list):
            raise ValidationError("BOBA candidate import must contain a candidate list.")
        candidates: list[BobaCandidateV1] = []
        for value in values:
            if not isinstance(value, Mapping):
                raise ValidationError("Every imported BOBA candidate must be an object.")
            payload = dict(value)
            payload["source_type"] = source_type
            if source_type == "csv_import":
                payload["duration_seconds"] = _number(payload.get("duration_seconds")) or None
                payload["permission_confirmed"] = str(
                    payload.get("permission_confirmed", "")
                ).casefold() in {"1", "true", "yes"}
            candidates.append(self.create_candidate(payload))
        return candidates

    def score_candidate(
        self,
        candidate_id: str,
        *,
        creator_profile_id: str | None = None,
    ) -> BobaScoutScoreV1:
        candidate = self.store.load_scout_candidate(candidate_id)
        if candidate is None:
            raise NotFoundError(
                "BOBA candidate was not found.", details={"candidate_id": candidate_id}
            )
        title = candidate.title.casefold()
        title_words = candidate.title.split()
        curiosity_hits = sum(term in title for term in _CURIOSITY_TERMS)
        hook = 0.38 + min(0.36, curiosity_hits * 0.09)
        if "?" in candidate.title:
            hook += 0.1
        if 4 <= len(title_words) <= 14:
            hook += 0.1

        emotional = _metadata_score(
            candidate.metadata, "emotional_potential", "emotion_score", "emotional_stakes"
        )
        if emotional is None:
            emotional = 0.3 + min(
                0.5, sum(term in title for term in _EMOTION_TERMS) * 0.1
            )

        novelty = _metadata_score(candidate.metadata, "novelty_score", "novelty")
        if novelty is None:
            novelty = 0.38 + min(
                0.42, sum(term in title for term in _NOVELTY_TERMS) * 0.1
            )

        has_topic = bool(
            candidate.metadata.get("topic")
            or candidate.metadata.get("category")
            or candidate.metadata.get("niche")
        )
        clarity = 0.48 + (0.25 if has_topic else 0.0)
        if 4 <= len(title_words) <= 16:
            clarity += 0.15

        clipping = _metadata_score(
            candidate.metadata, "clipping_potential", "clip_density"
        )
        if clipping is None:
            duration = candidate.duration_seconds
            if duration is None:
                clipping = 0.45
            elif 90 <= duration <= 3_600:
                clipping = 0.78
            elif 30 <= duration < 90 or 3_600 < duration <= 7_200:
                clipping = 0.58
            else:
                clipping = 0.32

        if candidate.rights_status == "not_allowed":
            risk = 1.0
        elif candidate.processing_permitted:
            risk = 0.1
        elif candidate.rights_status == "unknown":
            risk = 0.78
        else:
            risk = 0.55

        hook = _clamp(hook)
        emotional = _clamp(emotional)
        novelty = _clamp(novelty)
        clarity = _clamp(clarity)
        clipping = _clamp(clipping)
        traits = candidate_traits(candidate)
        memory_delta, memory_reasons = self._memory_adjustment(
            traits, creator_profile_id=creator_profile_id
        )
        overall = _clamp(
            hook * 0.26
            + emotional * 0.2
            + novelty * 0.17
            + clarity * 0.15
            + clipping * 0.22
            - risk * 0.25
            + memory_delta
        )
        reasons = [
            f"Hook potential {hook:.2f} from title structure and curiosity cues.",
            f"Clipping potential {clipping:.2f} from metadata and duration suitability.",
            f"Topic clarity {clarity:.2f}; no video content was inspected.",
            *memory_reasons,
        ]
        warnings: list[str] = []
        if candidate.rights_status == "unknown":
            warnings.append("Rights are unknown; review permission before processing.")
        elif not candidate.permission_confirmed:
            warnings.append("User permission confirmation is still required before processing.")
        if candidate.rights_status == "not_allowed":
            warnings.append("Candidate is marked not allowed and must not be processed.")
        warnings.append("Scout used metadata only and did not download or inspect media.")

        if candidate.rights_status == "not_allowed":
            action: BobaScoutRecommendedAction = "do_not_process"
        elif not candidate.processing_permitted:
            action = "review_rights_first"
        elif overall >= 0.62:
            action = "process_now"
        elif overall >= 0.45:
            action = "approve_for_review"
        else:
            action = "idea_only"
        score = BobaScoutScoreV1(
            candidate_id=candidate.candidate_id,
            overall_score=overall,
            hook_potential=hook,
            emotional_potential=emotional,
            novelty_score=novelty,
            clarity_score=clarity,
            clipping_potential=clipping,
            risk_score=_clamp(risk),
            reasons=reasons,
            warnings=warnings,
            recommended_action=action,
        )
        self.store.save_scout_score(score)
        return score

    def _memory_adjustment(
        self,
        traits: set[str],
        *,
        creator_profile_id: str | None,
    ) -> tuple[float, list[str]]:
        records = self.store.list_records(
            "project", {"project_id": _SCOUT_MEMORY_PROJECT_ID}
        )
        if creator_profile_id:
            records.extend(
                self.store.list_records(
                    "creator", {"creator_profile_id": creator_profile_id}
                )
            )
        delta = 0.0
        matched: list[str] = []
        for record in records:
            adjustments = record.metadata.get("scout_adjustments")
            if not isinstance(adjustments, dict):
                continue
            for trait in sorted(traits):
                value = adjustments.get(trait)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    delta += float(value) * record.confidence
                    matched.append(trait)
        bounded = max(-0.15, min(0.15, delta))
        reasons = (
            [
                "Applied a bounded adjustment from explicit approval memory for: "
                + ", ".join(sorted(set(matched))[:4])
                + "."
            ]
            if matched
            else []
        )
        return bounded, reasons


def approval_memory_scope(
    creator_profile_id: str | None,
) -> tuple[Literal["project", "creator"], str]:
    if creator_profile_id:
        return "creator", creator_profile_id
    return "project", _SCOUT_MEMORY_PROJECT_ID


def approval_adjustments(
    candidate: BobaCandidateV1,
    *,
    decision: str,
) -> dict[str, float]:
    amount = {
        "approved": 0.05,
        "rejected": -0.09,
        "needs_changes": -0.03,
        "saved_for_later": 0.0,
    }.get(decision, 0.0)
    return dict.fromkeys(candidate_traits(candidate), amount)


def approval_memory_record(
    candidate: BobaCandidateV1,
    *,
    event_id: str,
    decision: str,
    reason: str,
    creator_profile_id: str | None,
) -> BobaMemoryRecordV1:
    scope, identifier = approval_memory_scope(creator_profile_id)
    adjustments = approval_adjustments(candidate, decision=decision)
    return BobaMemoryRecordV1(
        memory_id=f"approval_memory_{event_id}"[:128],
        scope=scope,
        record_type=(
            "learned_pattern"
            if decision == "approved"
            else "failed_pattern"
            if decision == "rejected"
            else "user_feedback"
        ),
        source="explicit_boba_approval",
        project_id=identifier if scope == "project" else None,
        creator_profile_id=identifier if scope == "creator" else None,
        confidence=0.55,
        importance=0.6,
        decay_rate=0.08,
        tags=["explicit_approval", decision, *sorted(candidate_traits(candidate))][:32],
        summary=f"Explicit {decision} decision recorded for bounded scout traits.",
        evidence=[reason] if reason else [],
        applies_to=["ranking", "planning", "frontend"],
        metadata={
            "approval_event_id": event_id,
            "target_type": "candidate",
            "scout_adjustments": adjustments,
        },
        warnings=["This lesson came only from explicit user input."],
    )
