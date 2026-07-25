"""Local, evidence-bounded research intelligence for BOBA Research Brain V1."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaResearchSourceTypeV1 = Literal[
    "txt",
    "md",
    "csv",
    "json",
    "manual",
    "pasted_text",
    "test_synthetic",
]
BobaResearchInsightTypeV1 = Literal[
    "topic",
    "audience_pain",
    "audience_desire",
    "controversy",
    "tension",
    "story_angle",
    "hook_angle",
    "format_idea",
    "caution",
    "verification_needed",
]
BobaResearchFormatStyleV1 = Literal[
    "story",
    "explainer",
    "list",
    "comparison",
    "myth_vs_fact",
    "mistake_to_avoid",
    "reaction",
    "tutorial",
    "transformation",
    "interview_clip",
    "commentary",
    "unknown",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None
ResearchImportResult: TypeAlias = tuple[
    "BobaResearchImportSourceV1",
    list["BobaResearchSourceV1"],
    list[str],
]

_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NUMBER_CLAIM = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|percent|million|billion)\b|\$\s*\d+)",
    re.IGNORECASE,
)
_MAX_IMPORT_BYTES = 1_000_000
_MAX_PROCESS_CHARS = 40_000
_MAX_SNIPPET_CHARS = 300
_MAX_SUMMARY_CHARS = 700
_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "between",
    "could",
    "from",
    "have",
    "into",
    "just",
    "local",
    "material",
    "more",
    "notes",
    "only",
    "other",
    "people",
    "research",
    "source",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "using",
    "very",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}
_PAIN_TERMS = {
    "challenge",
    "confused",
    "difficult",
    "expensive",
    "fail",
    "failure",
    "frustrated",
    "hard",
    "obstacle",
    "overwhelmed",
    "pain",
    "problem",
    "slow",
    "struggle",
    "waste",
}
_DESIRE_TERMS = {
    "achieve",
    "confidence",
    "easier",
    "goal",
    "growth",
    "hope",
    "improve",
    "need",
    "save",
    "success",
    "transform",
    "want",
}
_CONTROVERSY_TERMS = {
    "controversial",
    "critics",
    "debate",
    "disagree",
    "misconception",
    "myth",
    "unpopular",
    "versus",
    "wrong",
}
_TENSION_TERMS = {
    "although",
    "but",
    "conflict",
    "despite",
    "however",
    "risk",
    "struggle",
    "tradeoff",
    "versus",
}
_HOOK_TERMS = {
    "how",
    "mistake",
    "mystery",
    "never",
    "reason",
    "reveal",
    "secret",
    "surprising",
    "truth",
    "unexpected",
    "why",
}
_VERIFY_TERMS = {
    "always",
    "best",
    "everyone",
    "guaranteed",
    "most people",
    "never",
    "proves",
    "research says",
    "scientists say",
    "studies show",
}
_COPYRIGHT_TERMS = {
    "copied",
    "copyright",
    "full article",
    "licensed excerpt",
    "quoted article",
    "third-party text",
}
_SENSITIVE_TERMS = {
    "diagnosis",
    "financial",
    "health",
    "legal",
    "medical",
    "politics",
    "self-harm",
    "trauma",
}


def _text(value: Any, *, maximum: int = _MAX_SUMMARY_CHARS) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _compact_values(value: Any, *, maximum: int = 24) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,;|]", value)
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        values = []
    return list(
        dict.fromkeys(
            item
            for raw in values
            if (item := _text(raw, maximum=80))
        )
    )[:maximum]


def _tokens(*values: Any) -> list[str]:
    return [
        token
        for value in values
        for token in _TOKEN.findall(_text(value, maximum=_MAX_PROCESS_CHARS).casefold())
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _sentences(value: Any) -> list[str]:
    content = _text(value, maximum=_MAX_PROCESS_CHARS)
    return [
        sentence
        for part in _SENTENCE.split(content)
        if (sentence := _text(part, maximum=_MAX_SNIPPET_CHARS))
    ]


def _topic_terms(content: str, supplied: Any = None) -> list[str]:
    supplied_terms = _compact_values(supplied, maximum=12)
    counts = Counter(_tokens(content))
    inferred = [
        token
        for token, _count in counts.most_common(20)
        if len(token) >= 4
    ]
    return list(dict.fromkeys([*supplied_terms, *inferred]))[:12]


def _safe_local_file(
    path: str | Path,
    *,
    suffixes: set[str],
) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ValidationError("Research Brain import paths must be local files.")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError("Research Brain import file was not found.")
    if source.suffix.casefold() not in suffixes:
        expected = ", ".join(sorted(suffixes))
        raise ValidationError(f"Research Brain expected one of: {expected}.")
    if source.stat().st_size > _MAX_IMPORT_BYTES:
        raise ValidationError("Research Brain import exceeds the 1 MB safety limit.")
    return source


class BobaResearchImportSourceV1(BobaContract):
    import_id: str = Field(min_length=1, max_length=128)
    source_type: BobaResearchSourceTypeV1
    source_label: str = Field(min_length=1, max_length=160)
    source_path: str = Field(default="", max_length=260)
    imported_at: str = Field(default_factory=now_iso)
    item_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaResearchEvidenceSnippetV1(BobaContract):
    snippet_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    snippet: str = Field(min_length=1, max_length=_MAX_SNIPPET_CHARS)
    topic_tags: list[str] = Field(default_factory=list, max_length=16)
    start_hint: str = Field(default="", max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    usage_warning: str = Field(min_length=1, max_length=500)


class BobaResearchSourceV1(BobaContract):
    research_source_id: str = Field(min_length=1, max_length=128)
    source_type: BobaResearchSourceTypeV1
    source_label: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    author_or_source_name: str = Field(default="", max_length=200)
    published_at: str = Field(default="", max_length=80)
    topic_tags: list[str] = Field(default_factory=list, max_length=24)
    rights_usage_notes: str = Field(default="", max_length=600)
    user_notes: str = Field(default="", max_length=600)
    content_summary: str = Field(min_length=1, max_length=_MAX_SUMMARY_CHARS)
    evidence_snippets: list[BobaResearchEvidenceSnippetV1] = Field(
        default_factory=list,
        max_length=5,
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaResearchInsightV1(BobaContract):
    insight_id: str = Field(min_length=1, max_length=128)
    insight_type: BobaResearchInsightTypeV1
    summary: str = Field(min_length=1, max_length=500)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[BobaResearchEvidenceSnippetV1] = Field(
        default_factory=list,
        max_length=8,
    )
    content_opportunity: str = Field(min_length=1, max_length=600)
    risk: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    human_verification_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaResearchShortsIdeaV1(BobaContract):
    idea_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=160)
    hook_direction: str = Field(min_length=1, max_length=500)
    target_viewer: str = Field(min_length=1, max_length=300)
    format_style: BobaResearchFormatStyleV1
    why_it_might_work: str = Field(min_length=1, max_length=600)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    evidence: list[BobaResearchEvidenceSnippetV1] = Field(
        default_factory=list,
        max_length=8,
    )
    risk: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    human_review_required: bool = True


class BobaResearchSafetyReviewV1(BobaContract):
    weak_evidence_warnings: list[str] = Field(default_factory=list, max_length=64)
    unverifiable_claim_warnings: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    copyrighted_content_warnings: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    sensitive_topic_warnings: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    rights_usage_warnings: list[str] = Field(default_factory=list, max_length=64)
    human_verification_notes: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    blockers: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaContentScoutResearchHandoffV1(BobaContract):
    recommended_topics: list[str] = Field(default_factory=list, max_length=32)
    recommended_keywords: list[str] = Field(default_factory=list, max_length=64)
    suggested_content_categories: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    avoid_topics: list[str] = Field(default_factory=list, max_length=32)
    rights_review_reminders: list[str] = Field(default_factory=list, max_length=32)
    suggested_review_questions: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    scout_item_notes: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaResearchSummaryV1(BobaContract):
    total_sources: int = Field(default=0, ge=0)
    total_insights: int = Field(default=0, ge=0)
    total_shorts_ideas: int = Field(default=0, ge=0)
    strongest_topics: list[str] = Field(default_factory=list, max_length=32)
    repeated_themes: list[str] = Field(default_factory=list, max_length=32)
    strongest_audience_problems: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    strongest_hook_angles: list[str] = Field(default_factory=list, max_length=32)
    weak_or_risky_claims: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaResearchSignalUsageV1(BobaContract):
    content_scout_used: bool = False
    creator_learning_used: bool = False
    approval_rejection_learning_used: bool = False
    performance_feedback_used: bool = False
    memory_used: bool = False
    local_import_used: bool = False
    manual_input_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaResearchBrainSetV1(BobaContract):
    schema_version: Literal["boba_research_brain_v1"] = "boba_research_brain_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    imported_sources: list[BobaResearchImportSourceV1] = Field(
        default_factory=list,
        max_length=100,
    )
    research_sources: list[BobaResearchSourceV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    research_insights: list[BobaResearchInsightV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    shorts_ideas: list[BobaResearchShortsIdeaV1] = Field(
        default_factory=list,
        max_length=500,
    )
    safety_review: BobaResearchSafetyReviewV1
    content_scout_handoff: BobaContentScoutResearchHandoffV1
    research_summary: BobaResearchSummaryV1
    signal_usage: BobaResearchSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def normalize_research_source(
    raw: Mapping[str, Any],
    *,
    source_type: BobaResearchSourceTypeV1 = "manual",
    source_label: str = "manual",
    item_index: int = 0,
) -> BobaResearchSourceV1:
    content = _text(
        raw.get("text")
        or raw.get("content")
        or raw.get("summary")
        or raw.get("description"),
        maximum=_MAX_PROCESS_CHARS,
    )
    if not content:
        raise ValidationError(
            "Research source requires non-empty text, content, or summary.",
            details={"item_index": item_index},
        )
    effective_label = _text(
        raw.get("source_label") or raw.get("source") or source_label,
        maximum=160,
    ) or source_label
    title = _text(raw.get("title"), maximum=300) or (
        f"{effective_label} research note {item_index + 1}"
    )
    supplied_id = _text(
        raw.get("research_source_id") or raw.get("source_id"),
        maximum=128,
    )
    research_source_id = (
        supplied_id
        if _SAFE_ID.fullmatch(supplied_id)
        else _stable_id(
            "research_source",
            source_type,
            effective_label,
            str(item_index),
            title,
            content[:300],
        )
    )
    topic_tags = _topic_terms(
        content,
        raw.get("topic_tags") or raw.get("tags") or raw.get("categories"),
    )
    sentences = _sentences(content)
    snippets = [
        BobaResearchEvidenceSnippetV1(
            snippet_id=_stable_id(
                "research_snippet",
                research_source_id,
                str(index),
                sentence,
            ),
            source_id=research_source_id,
            snippet=sentence,
            topic_tags=topic_tags[:8],
            start_hint=f"sentence {index + 1}",
            confidence=_clamp(0.52 + min(0.2, len(sentence.split()) * 0.01)),
            usage_warning=(
                "Bounded local excerpt for human verification; do not republish it "
                "without checking rights and source context."
            ),
        )
        for index, sentence in enumerate(sentences[:3])
    ]
    if not snippets:
        raise ValidationError(
            "Research source did not contain usable bounded evidence.",
            details={"item_index": item_index},
        )
    rights_notes = _text(
        raw.get("rights_usage_notes")
        or raw.get("rights_notes")
        or raw.get("permission_notes"),
        maximum=600,
    )
    warnings = [
        "Full source content was not stored; only a compact summary and bounded snippets remain."
    ]
    if not rights_notes:
        warnings.append("Rights and usage notes were not provided.")
    summary_topics = ", ".join(topic_tags[:6]) or "uncategorized themes"
    content_summary = _text(
        f"Local material focuses on {summary_topics}. It contains approximately "
        f"{len(content.split())} words and was reduced to bounded evidence for "
        "advisory analysis.",
        maximum=_MAX_SUMMARY_CHARS,
    )
    return BobaResearchSourceV1(
        research_source_id=research_source_id,
        source_type=source_type,
        source_label=effective_label,
        title=title,
        author_or_source_name=_text(
            raw.get("author_or_source_name")
            or raw.get("author")
            or raw.get("creator"),
            maximum=200,
        ),
        published_at=_text(
            raw.get("published_at") or raw.get("date"),
            maximum=80,
        ),
        topic_tags=topic_tags,
        rights_usage_notes=rights_notes,
        user_notes=_text(raw.get("user_notes") or raw.get("notes"), maximum=600),
        content_summary=content_summary,
        evidence_snippets=snippets,
        warnings=warnings,
        limitations=[
            "Research Brain did not fetch, validate, or independently verify this source.",
            "Evidence snippets may omit surrounding context.",
        ],
    )


def _import_values(
    values: Sequence[Any],
    *,
    source_type: BobaResearchSourceTypeV1,
    source_label: str,
    source_path: str,
) -> ResearchImportResult:
    accepted: list[BobaResearchSourceV1] = []
    rejected: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            rejected.append(f"Row {index + 1} was not an object.")
            continue
        try:
            accepted.append(
                normalize_research_source(
                    value,
                    source_type=source_type,
                    source_label=source_label,
                    item_index=index,
                )
            )
        except (ValidationError, ValueError) as exc:
            rejected.append(f"Row {index + 1}: {_text(exc, maximum=500)}")
    warnings = (
        [
            f"{len(rejected)} invalid research source(s) were rejected without "
            "stopping the remaining import.",
            *rejected[:12],
        ]
        if rejected
        else []
    )
    imported = BobaResearchImportSourceV1(
        import_id=_stable_id(
            "research_import",
            source_type,
            source_label,
            source_path,
            str(len(values)),
        ),
        source_type=source_type,
        source_label=source_label,
        source_path=source_path,
        item_count=len(values),
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        warnings=warnings,
        limitations=[
            "Only compact summaries and bounded evidence snippets were retained."
        ],
    )
    return imported, accepted, rejected


def _import_text_file(
    path: str | Path,
    *,
    source_type: Literal["txt", "md"],
    source_label: str = "",
) -> ResearchImportResult:
    source = _safe_local_file(path, suffixes={f".{source_type}"})
    try:
        content = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValidationError("Research text import could not be read as UTF-8.") from exc
    return _import_values(
        [{"title": source.stem, "text": content}],
        source_type=source_type,
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_research_from_txt(
    path: str | Path,
    *,
    source_label: str = "",
) -> ResearchImportResult:
    return _import_text_file(path, source_type="txt", source_label=source_label)


def import_research_from_md(
    path: str | Path,
    *,
    source_label: str = "",
) -> ResearchImportResult:
    return _import_text_file(path, source_type="md", source_label=source_label)


def import_research_from_csv(
    path: str | Path,
    *,
    source_label: str = "",
) -> ResearchImportResult:
    source = _safe_local_file(path, suffixes={".csv"})
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            values = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError("Research CSV import could not be parsed.") from exc
    return _import_values(
        values,
        source_type="csv",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_research_from_json(
    path: str | Path,
    *,
    source_label: str = "",
) -> ResearchImportResult:
    source = _safe_local_file(path, suffixes={".json"})
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Research JSON import could not be parsed.") from exc
    if isinstance(raw, dict):
        values = next(
            (
                raw[key]
                for key in ("sources", "research_sources", "items")
                if isinstance(raw.get(key), list)
            ),
            None,
        )
    else:
        values = raw
    if not isinstance(values, list):
        raise ValidationError(
            "Research JSON must be a list or contain sources/research_sources/items."
        )
    return _import_values(
        values,
        source_type="json",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def _source_text(source: BobaResearchSourceV1) -> str:
    return " ".join(
        [
            source.title,
            source.content_summary,
            *source.topic_tags,
            source.rights_usage_notes,
            source.user_notes,
            *(snippet.snippet for snippet in source.evidence_snippets),
        ]
    )


def _insight(
    source: BobaResearchSourceV1,
    *,
    insight_type: BobaResearchInsightTypeV1,
    summary: str,
    content_opportunity: str,
    risk: str,
    confidence: float,
    verification: bool,
) -> BobaResearchInsightV1:
    return BobaResearchInsightV1(
        insight_id=_stable_id(
            "research_insight",
            source.research_source_id,
            insight_type,
            summary,
        ),
        insight_type=insight_type,
        summary=_text(summary, maximum=500),
        source_ids=[source.research_source_id],
        evidence=source.evidence_snippets[:2],
        content_opportunity=_text(content_opportunity, maximum=600),
        risk=_text(risk, maximum=600),
        confidence=_clamp(confidence),
        human_verification_required=verification,
        warnings=[
            "Insight is inferred from bounded local snippets, not independent research."
        ],
    )


def _format_for_text(text: str) -> BobaResearchFormatStyleV1:
    lowered = text.casefold()
    if "myth" in lowered and "fact" in lowered:
        return "myth_vs_fact"
    if "mistake" in lowered:
        return "mistake_to_avoid"
    if "before" in lowered and "after" in lowered:
        return "transformation"
    if any(term in lowered for term in ("tutorial", "how to", "steps")):
        return "tutorial"
    if any(term in lowered for term in ("versus", " vs ", "comparison")):
        return "comparison"
    if any(term in lowered for term in ("podcast", "interview")):
        return "interview_clip"
    if "reaction" in lowered:
        return "reaction"
    if any(term in lowered for term in ("story", "journey", "comeback")):
        return "story"
    if any(term in lowered for term in ("list", "three ways", "five ways")):
        return "list"
    if any(term in lowered for term in ("opinion", "commentary", "debate")):
        return "commentary"
    return "explainer"


def extract_research_insights(
    sources: Sequence[BobaResearchSourceV1],
) -> list[BobaResearchInsightV1]:
    insights: list[BobaResearchInsightV1] = []
    for source in sources:
        text = _source_text(source)
        lowered = text.casefold()
        tokens = set(_tokens(text))
        topic = source.topic_tags[0] if source.topic_tags else "the supplied topic"
        insights.append(
            _insight(
                source,
                insight_type="topic",
                summary=f"The local material repeatedly emphasizes {topic}.",
                content_opportunity=(
                    f"Review whether {topic} can anchor a source-supported Shorts topic."
                ),
                risk="Frequency in one source does not establish broader relevance.",
                confidence=0.66 if source.topic_tags else 0.42,
                verification=False,
            )
        )
        if tokens & _PAIN_TERMS:
            term = sorted(tokens & _PAIN_TERMS)[0]
            insights.append(
                _insight(
                    source,
                    insight_type="audience_pain",
                    summary=f"The material describes an audience problem around {term}.",
                    content_opportunity=(
                        "A possible Short could state the source-supported problem "
                        "before presenting any bounded lesson."
                    ),
                    risk="The affected audience and severity require human verification.",
                    confidence=0.7,
                    verification=True,
                )
            )
        if tokens & _DESIRE_TERMS:
            term = sorted(tokens & _DESIRE_TERMS)[0]
            insights.append(
                _insight(
                    source,
                    insight_type="audience_desire",
                    summary=f"The material points to a viewer desire for {term}.",
                    content_opportunity=(
                        "A possible Short may frame the desired outcome without "
                        "promising that the result is guaranteed."
                    ),
                    risk="Desire language is inferred from local wording only.",
                    confidence=0.66,
                    verification=True,
                )
            )
        if tokens & _CONTROVERSY_TERMS:
            insights.append(
                _insight(
                    source,
                    insight_type="controversy",
                    summary=f"The material presents a disputed angle around {topic}.",
                    content_opportunity=(
                        "A balanced commentary or myth-versus-fact review may be possible."
                    ),
                    risk=(
                        "Competing viewpoints and factual claims must be verified "
                        "before publication."
                    ),
                    confidence=0.58,
                    verification=True,
                )
            )
        if tokens & _TENSION_TERMS:
            insights.append(
                _insight(
                    source,
                    insight_type="tension",
                    summary=f"The material contains tension or a tradeoff around {topic}.",
                    content_opportunity=(
                        "A possible Short may open on the source-supported tradeoff "
                        "and resolve only what the evidence supports."
                    ),
                    risk="The source may omit context from the opposing side.",
                    confidence=0.62,
                    verification=True,
                )
            )
        if tokens & _HOOK_TERMS:
            hook_term = sorted(tokens & _HOOK_TERMS)[0]
            insights.append(
                _insight(
                    source,
                    insight_type="hook_angle",
                    summary=f"A possible {hook_term}-led hook appears around {topic}.",
                    content_opportunity=(
                        f"Test a source-supported {hook_term} opening without "
                        "inventing a payoff."
                    ),
                    risk="Hook wording must not overstate the bounded evidence.",
                    confidence=0.68,
                    verification=True,
                )
            )
        format_style = _format_for_text(lowered)
        insights.append(
            _insight(
                source,
                insight_type="format_idea",
                summary=(
                    f"The supplied material may fit a "
                    f"{format_style.replace('_', ' ')} format."
                ),
                content_opportunity=(
                    f"Review a possible {format_style.replace('_', ' ')} treatment "
                    "using only source-supported points."
                ),
                risk="Format fit is advisory and does not predict performance.",
                confidence=0.6,
                verification=False,
            )
        )
        unverifiable = _NUMBER_CLAIM.search(text) is not None or any(
            term in lowered for term in _VERIFY_TERMS
        )
        if unverifiable:
            insights.append(
                _insight(
                    source,
                    insight_type="verification_needed",
                    summary=(
                        f"A factual or absolute claim in {source.title} needs "
                        "independent human verification."
                    ),
                    content_opportunity=(
                        "Use the claim only as a research question until an "
                        "authoritative source is confirmed."
                    ),
                    risk="Publishing an unverified claim may mislead viewers.",
                    confidence=0.82,
                    verification=True,
                )
            )
        rights_text = f"{source.rights_usage_notes} {source.user_notes}".casefold()
        if any(term in rights_text for term in _COPYRIGHT_TERMS):
            insights.append(
                _insight(
                    source,
                    insight_type="caution",
                    summary=f"{source.title} includes a copied-content or copyright caution.",
                    content_opportunity=(
                        "Use only independently written summaries or facts after "
                        "rights and attribution review."
                    ),
                    risk="Do not republish copied wording or assume usage permission.",
                    confidence=0.9,
                    verification=True,
                )
            )
    unique: dict[tuple[str, str], BobaResearchInsightV1] = {}
    for insight in insights:
        key = (insight.insight_type, insight.summary.casefold())
        unique.setdefault(key, insight)
    return list(unique.values())[:2_000]


def _preferred_format(creator_learning: Mapping[str, Any]) -> str:
    profile = _dict(creator_learning.get("learning_profile"))
    values = [
        *_list(profile.get("preferred_clip_types")),
        *_list(profile.get("story_angle_preferences")),
    ]
    text = " ".join(_text(value, maximum=100) for value in values).casefold()
    for style in (
        "tutorial",
        "story",
        "comparison",
        "reaction",
        "transformation",
        "commentary",
        "list",
    ):
        if style in text:
            return style
    return ""


def generate_research_shorts_ideas(
    insights: Sequence[BobaResearchInsightV1],
    *,
    creator_learning: ArtifactValue = None,
    content_scout: ArtifactValue = None,
) -> list[BobaResearchShortsIdeaV1]:
    creator = _dict(creator_learning)
    scout = _dict(content_scout)
    preferred = _preferred_format(creator)
    scout_topics = {
        value.casefold()
        for value in _compact_values(
            _dict(scout.get("scout_summary")).get("strongest_topics"),
            maximum=20,
        )
    }
    ideas: list[BobaResearchShortsIdeaV1] = []
    seen: set[tuple[str, str]] = set()
    for insight in insights:
        if insight.insight_type in {"caution", "verification_needed"}:
            continue
        evidence = insight.evidence[:2]
        if not evidence or not insight.source_ids:
            continue
        topic = (
            evidence[0].topic_tags[0]
            if evidence[0].topic_tags
            else "the supplied topic"
        )
        inferred_format = _format_for_text(
            f"{insight.summary} {insight.content_opportunity}"
        )
        format_style = (
            preferred
            if preferred
            and inferred_format in {"explainer", "commentary"}
            else inferred_format
        )
        if format_style not in {
            "story",
            "explainer",
            "list",
            "comparison",
            "myth_vs_fact",
            "mistake_to_avoid",
            "reaction",
            "tutorial",
            "transformation",
            "interview_clip",
            "commentary",
            "unknown",
        }:
            format_style = "unknown"
        key = (topic.casefold(), str(format_style))
        if key in seen:
            continue
        seen.add(key)
        scout_alignment = topic.casefold() in scout_topics
        ideas.append(
            BobaResearchShortsIdeaV1(
                idea_id=_stable_id(
                    "research_idea",
                    insight.insight_id,
                    topic,
                    str(format_style),
                ),
                title=_text(
                    f"Possible idea: {insight.summary}",
                    maximum=300,
                ),
                topic=topic,
                hook_direction=_text(
                    "Open with the source-supported problem, question, or tension "
                    "and avoid implying evidence that is not present.",
                    maximum=500,
                ),
                target_viewer=(
                    f"Viewers interested in {topic} who recognize the described problem."
                ),
                format_style=format_style,
                why_it_might_work=_text(
                    "The bounded local evidence contains a clear topic or tension"
                    + (
                        " that also appears in saved Content Scout metadata."
                        if scout_alignment
                        else "."
                    )
                    + " This is a possible editorial angle, not an audience prediction.",
                    maximum=600,
                ),
                source_ids=insight.source_ids,
                evidence=evidence,
                risk=(
                    "Human review must verify facts, context, rights, and whether "
                    "the proposed framing accurately represents the source."
                ),
                confidence=_clamp(
                    insight.confidence
                    + (0.04 if preferred else 0.0)
                    + (0.03 if scout_alignment else 0.0)
                    - 0.08
                ),
                human_review_required=True,
            )
        )
        if len(ideas) >= 12:
            break
    return ideas


def _safety_review(
    sources: Sequence[BobaResearchSourceV1],
    insights: Sequence[BobaResearchInsightV1],
) -> BobaResearchSafetyReviewV1:
    weak: list[str] = []
    copyright_warnings: list[str] = []
    sensitive: list[str] = []
    rights: list[str] = []
    blockers: list[str] = []
    for source in sources:
        text = _source_text(source).casefold()
        if len(source.evidence_snippets) < 2:
            weak.append(
                f"{source.title}: only one bounded evidence snippet was available."
            )
        rights_text = source.rights_usage_notes.casefold()
        if not rights_text:
            rights.append(f"{source.title}: rights and usage status is unknown.")
        rights_context = f"{rights_text} {source.user_notes.casefold()}"
        if any(term in rights_context for term in _COPYRIGHT_TERMS):
            copyright_warnings.append(
                f"{source.title}: copied or copyrighted wording may be present; "
                "do not republish source text."
            )
        if any(term in text for term in _SENSITIVE_TERMS):
            sensitive.append(
                f"{source.title}: sensitive-topic claims require qualified human review."
            )
        if any(term in rights_text for term in ("blocked", "prohibited", "do not use")):
            blockers.append(
                f"{source.title}: usage notes prohibit or block downstream use."
            )
    unverifiable = [
        insight.summary
        for insight in insights
        if insight.insight_type == "verification_needed"
    ]
    return BobaResearchSafetyReviewV1(
        weak_evidence_warnings=weak,
        unverifiable_claim_warnings=unverifiable[:64],
        copyrighted_content_warnings=copyright_warnings,
        sensitive_topic_warnings=sensitive,
        rights_usage_warnings=rights,
        human_verification_notes=[
            "Verify factual claims against authoritative sources before publication.",
            "Review source context, quotation, attribution, and usage rights.",
            "Treat all hook and format ideas as advisory possibilities.",
        ],
        blockers=blockers,
        warnings=[
            "Research Brain cannot confirm factual accuracy or copyright safety.",
            "No real-time trend verification was performed.",
        ],
    )


def _summary(
    sources: Sequence[BobaResearchSourceV1],
    insights: Sequence[BobaResearchInsightV1],
    ideas: Sequence[BobaResearchShortsIdeaV1],
    safety: BobaResearchSafetyReviewV1,
) -> BobaResearchSummaryV1:
    topics = Counter(
        topic.casefold()
        for source in sources
        for topic in source.topic_tags
        if topic
    )
    return BobaResearchSummaryV1(
        total_sources=len(sources),
        total_insights=len(insights),
        total_shorts_ideas=len(ideas),
        strongest_topics=[topic for topic, _count in topics.most_common(10)],
        repeated_themes=[
            f"{topic} appears across {count} source signal(s)."
            for topic, count in topics.most_common(12)
            if count >= 2
        ],
        strongest_audience_problems=[
            insight.summary
            for insight in insights
            if insight.insight_type == "audience_pain"
        ][:10],
        strongest_hook_angles=[
            insight.summary
            for insight in insights
            if insight.insight_type == "hook_angle"
        ][:10],
        weak_or_risky_claims=[
            *safety.unverifiable_claim_warnings,
            *safety.weak_evidence_warnings,
            *safety.copyrighted_content_warnings,
        ][:20],
        human_review_notes=[
            "Use source IDs and bounded snippets to trace each recommendation.",
            "Do not treat repeated wording as verified demand or trend evidence.",
            "Do not publish copied wording without rights and attribution review.",
        ],
    )


def _handoff(
    sources: Sequence[BobaResearchSourceV1],
    summary: BobaResearchSummaryV1,
    safety: BobaResearchSafetyReviewV1,
) -> BobaContentScoutResearchHandoffV1:
    keywords = list(
        dict.fromkeys(
            topic
            for source in sources
            for topic in source.topic_tags
        )
    )[:40]
    categories = list(
        dict.fromkeys(
            _format_for_text(_source_text(source)).replace("_", " ")
            for source in sources
        )
    )[:16]
    avoid_topics = list(
        dict.fromkeys(
            topic
            for source in sources
            if any(
                warning.startswith(f"{source.title}:")
                for warning in (
                    *safety.sensitive_topic_warnings,
                    *safety.blockers,
                )
            )
            for topic in source.topic_tags[:3]
        )
    )[:20]
    return BobaContentScoutResearchHandoffV1(
        recommended_topics=summary.strongest_topics[:16],
        recommended_keywords=keywords,
        suggested_content_categories=categories,
        avoid_topics=avoid_topics,
        rights_review_reminders=[
            "Content Scout must keep unknown rights in permission review.",
            "Do not ingest or process a source until a human confirms usage rights.",
            "Research evidence does not establish copyright safety.",
        ],
        suggested_review_questions=[
            "Which source supports the proposed topic or hook?",
            "Has the factual claim been independently verified?",
            "Can the idea be expressed without copying protected wording?",
            "Are rights and permission sufficient for any future source ingestion?",
        ],
        scout_item_notes=[
            "Use these topics and keywords as advisory metadata only.",
            "Preserve source IDs when a future Scout item references this research.",
            "Do not apply this handoff automatically.",
        ],
        apply_automatically=False,
    )


class BobaResearchBrainV1:
    """Convert explicit local material into bounded advisory research."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        manual_sources: Sequence[Mapping[str, Any]] = (),
        pasted_text_entries: Sequence[str | Mapping[str, Any]] = (),
        import_paths: Sequence[str | Path] = (),
        manual_source_type: BobaResearchSourceTypeV1 = "manual",
        source_label: str = "manual",
        content_scout: ArtifactValue = None,
        creator_learning: ArtifactValue = None,
        approval_rejection_learning: ArtifactValue = None,
        performance_feedback: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaResearchBrainSetV1:
        imported_sources: list[BobaResearchImportSourceV1] = []
        sources: list[BobaResearchSourceV1] = []
        rejected_warnings: list[str] = []
        if manual_sources:
            imported, accepted, rejected = _import_values(
                list(manual_sources),
                source_type=manual_source_type,
                source_label=source_label,
                source_path="",
            )
            imported_sources.append(imported)
            sources.extend(accepted)
            rejected_warnings.extend(rejected)
        if pasted_text_entries:
            pasted_values = [
                value
                if isinstance(value, Mapping)
                else {"text": value, "title": f"Pasted research note {index + 1}"}
                for index, value in enumerate(pasted_text_entries)
            ]
            imported, accepted, rejected = _import_values(
                pasted_values,
                source_type="pasted_text",
                source_label="pasted_text",
                source_path="",
            )
            imported_sources.append(imported)
            sources.extend(accepted)
            rejected_warnings.extend(rejected)
        importers = {
            ".txt": import_research_from_txt,
            ".md": import_research_from_md,
            ".csv": import_research_from_csv,
            ".json": import_research_from_json,
        }
        for path in import_paths:
            importer = importers.get(Path(path).suffix.casefold())
            if importer is None:
                raise ValidationError(
                    "Research Brain supports only local TXT, MD, CSV, and JSON imports."
                )
            imported, accepted, rejected = importer(path)
            imported_sources.append(imported)
            sources.extend(accepted)
            rejected_warnings.extend(rejected)

        insights = extract_research_insights(sources)
        ideas = generate_research_shorts_ideas(
            insights,
            creator_learning=creator_learning,
            content_scout=content_scout,
        )
        safety = _safety_review(sources, insights)
        summary = _summary(sources, insights, ideas, safety)
        handoff = _handoff(sources, summary, safety)
        artifacts = {
            "content_scout": _dict(content_scout),
            "creator_learning": _dict(creator_learning),
            "approval_rejection_learning": _dict(approval_rejection_learning),
            "performance_feedback": _dict(performance_feedback),
            "memory": _dict(boba_memory),
        }
        unavailable = [
            name for name, artifact in artifacts.items() if not artifact
        ]
        warnings = [
            "Research Brain V1 used local/user-provided material only.",
            "No URL was fetched, no website was scraped, and no external API was called.",
            "Only compact summaries and bounded evidence snippets were retained.",
        ]
        if rejected_warnings:
            warnings.append(
                f"{len(rejected_warnings)} invalid research source(s) were rejected."
            )
        if dry_run:
            warnings.append("Dry run: the Research Brain artifact was not persisted.")
        return BobaResearchBrainSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            imported_sources=imported_sources,
            research_sources=sources,
            research_insights=insights,
            shorts_ideas=ideas,
            safety_review=safety,
            content_scout_handoff=handoff,
            research_summary=summary,
            signal_usage=BobaResearchSignalUsageV1(
                content_scout_used=bool(artifacts["content_scout"]),
                creator_learning_used=bool(artifacts["creator_learning"]),
                approval_rejection_learning_used=bool(
                    artifacts["approval_rejection_learning"]
                ),
                performance_feedback_used=bool(
                    artifacts["performance_feedback"]
                ),
                memory_used=bool(artifacts["memory"]),
                local_import_used=any(
                    item.source_type in {"txt", "md", "csv", "json"}
                    for item in imported_sources
                ),
                manual_input_used=any(
                    item.source_type
                    in {"manual", "pasted_text", "test_synthetic"}
                    for item in imported_sources
                ),
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                fallback_used=bool(unavailable),
                unavailable_signals=unavailable,
                warnings=(
                    [
                        "Missing optional BOBA artifacts limited advisory personalization."
                    ]
                    if unavailable
                    else []
                ),
            ),
            warnings=warnings,
            limitations=[
                "Research Brain does not verify facts, trends, audience demand, or rights.",
                "Evidence snippets may omit surrounding source context.",
                "Shorts ideas are possible editorial directions, not performance predictions.",
                "Content Scout handoff is advisory and is never applied automatically.",
                "Trend Watcher, Candidate Video Scorer, and deeper rights review "
                "are future handoffs.",
            ],
        )
