"""Explicit and validation-driven learning for BOBA Memory V1."""

from __future__ import annotations

from typing import Any

from olympus.boba.memory_contracts import BobaMemoryRecordV1
from olympus.boba.memory_summarizer import memory_strings, memory_summary, safe_excerpt
from olympus.boba.store import BobaMemoryStore
from olympus.personalization.contracts import ClipFeedbackV2
from olympus.platform.errors import ValidationError


class BobaMemoryLearner:
    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store

    def learn_from_feedback(
        self, feedback_value: ClipFeedbackV2 | dict[str, Any]
    ) -> BobaMemoryRecordV1:
        if isinstance(feedback_value, dict) and any(
            feedback_value.get(key) for key in ("passive", "passive_viewing", "implicit")
        ):
            raise ValidationError("BOBA Memory does not learn from passive or implicit behavior.")
        feedback = (
            feedback_value
            if isinstance(feedback_value, ClipFeedbackV2)
            else ClipFeedbackV2.model_validate(feedback_value)
        )
        labels = [name for name, enabled in feedback.labels.model_dump().items() if enabled]
        signature = ":".join(
            [feedback.rating.overall, *(labels or ["unlabeled"])]
        )[:120]
        existing = next(
            (
                record
                for record in self.store.list_records(
                    "creator", {"creator_profile_id": feedback.profile_id}
                )
                if record.metadata.get("feedback_signature") == signature
            ),
            None,
        )
        occurrences = int(existing.metadata.get("occurrences", 0)) + 1 if existing else 1
        record_type = (
            "failed_pattern"
            if feedback.rating.overall == "dislike" or feedback.labels.avoid_in_future
            else "learned_pattern"
            if feedback.rating.overall == "like" or feedback.labels.make_more_like_this
            else "user_feedback"
        )
        traits = [
            item
            for values in feedback.extracted_safe_learning.model_dump().values()
            for item in values
        ]
        record = BobaMemoryRecordV1(
            memory_id=(
                existing.memory_id
                if existing
                else f"feedback_pattern_{feedback.profile_id}_{feedback.feedback_id}"[:128]
            ),
            scope="creator",
            record_type=record_type,
            source="explicit_user_feedback",
            project_id=feedback.project_id,
            clip_id=feedback.clip_id,
            creator_profile_id=feedback.profile_id,
            confidence=min(0.9, 0.2 + occurrences * 0.1),
            importance=min(0.9, 0.5 + occurrences * 0.05),
            decay_rate=0.05,
            tags=memory_strings(["explicit_feedback", *labels, *traits], limit=32, max_chars=80),
            summary=memory_summary(
                [f"Explicit {feedback.rating.overall} feedback", f"Observed {occurrences} time(s)"]
            ),
            evidence=[safe_excerpt(feedback.notes)] if feedback.notes else [],
            applies_to=[
                "planning",
                "ranking",
                "editorial_policy",
                "captions",
                "music",
                "motion",
                "upload_metadata",
            ],
            metadata={"feedback_signature": signature, "occurrences": occurrences},
        )
        return self.store.save_record(record)

    def learn_from_project_outcome(self, project_id: str) -> BobaMemoryRecordV1:
        project = self.store.load_project_memory(project_id)
        if project is None:
            raise ValidationError("Project memory must exist before learning from its outcome.")
        return self.store.save_record(
            BobaMemoryRecordV1(
                scope="project",
                record_type="experiment_result",
                source="project_memory_summary",
                project_id=project_id,
                confidence=0.35,
                importance=0.45,
                tags=["outcome_placeholder", "no_analytics"],
                summary=(
                    f"Project selected {len(project.selected_clip_ids)} clips; "
                    "no audience analytics were available."
                ),
                applies_to=["planning", "frontend"],
                warnings=[
                    "This record is a project outcome placeholder, not performance learning."
                ],
            )
        )

    def learn_from_validation_report(self, report: dict[str, Any]) -> list[BobaMemoryRecordV1]:
        project_id = str(report.get("project_id") or "")
        if not project_id:
            raise ValidationError("Validation learning requires project_id.")
        warning_values = report.get("warnings")
        error_values = report.get("errors")
        report_warnings: list[Any] = warning_values if isinstance(warning_values, list) else []
        report_errors: list[Any] = error_values if isinstance(error_values, list) else []
        warnings = memory_strings(
            [*report_warnings, *report_errors], limit=24, max_chars=300
        )
        if not warnings and report.get("passed") is True:
            return [
                self.create_learning_note_from_success(
                    project_id, "Validation passed for the checked signals."
                )
            ]
        return [
            self.create_learning_note_from_failure(project_id, warning) for warning in warnings
        ]

    def create_learning_note_from_failure(
        self, project_id: str, failure: str
    ) -> BobaMemoryRecordV1:
        return self.store.save_record(
            BobaMemoryRecordV1(
                scope="project",
                record_type="failed_pattern",
                source="validation_report",
                project_id=project_id,
                confidence=0.8,
                importance=0.85,
                tags=memory_strings(["validation_failure", failure], limit=8, max_chars=80),
                summary=safe_excerpt(failure, max_chars=600),
                applies_to=["planning", "editorial_policy", "safety", "frontend"],
            )
        )

    def create_learning_note_from_success(
        self, project_id: str, success: str
    ) -> BobaMemoryRecordV1:
        return self.store.save_record(
            BobaMemoryRecordV1(
                scope="project",
                record_type="learned_pattern",
                source="validation_report",
                project_id=project_id,
                confidence=0.45,
                importance=0.4,
                tags=["validation_success", "no_performance_claim"],
                summary=safe_excerpt(success, max_chars=600),
                applies_to=["planning", "frontend"],
                warnings=["Validation success does not prove audience performance."],
            )
        )


def learn_from_feedback(
    store: BobaMemoryStore, feedback: ClipFeedbackV2 | dict[str, Any]
) -> BobaMemoryRecordV1:
    return BobaMemoryLearner(store).learn_from_feedback(feedback)


def learn_from_project_outcome(store: BobaMemoryStore, project_id: str) -> BobaMemoryRecordV1:
    return BobaMemoryLearner(store).learn_from_project_outcome(project_id)


def learn_from_validation_report(
    store: BobaMemoryStore, report: dict[str, Any]
) -> list[BobaMemoryRecordV1]:
    return BobaMemoryLearner(store).learn_from_validation_report(report)


def create_learning_note_from_failure(
    store: BobaMemoryStore, project_id: str, failure: str
) -> BobaMemoryRecordV1:
    return BobaMemoryLearner(store).create_learning_note_from_failure(project_id, failure)


def create_learning_note_from_success(
    store: BobaMemoryStore, project_id: str, success: str
) -> BobaMemoryRecordV1:
    return BobaMemoryLearner(store).create_learning_note_from_success(project_id, success)
