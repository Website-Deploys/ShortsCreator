"""Non-invasive advisory decision routing for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from olympus.boba.constitution import get_boba_constitution
from olympus.boba.contracts import BobaDecisionV1
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError


class BobaDecisionBus:
    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store
        self.constitution = get_boba_constitution()

    def validate_decision(self, decision: BobaDecisionV1 | dict[str, Any]) -> BobaDecisionV1:
        try:
            parsed = (
                decision
                if isinstance(decision, BobaDecisionV1)
                else BobaDecisionV1.model_validate(decision)
            )
        except PydanticValidationError as exc:
            raise ValidationError(
                "BOBA decision failed schema validation.",
                details={"errors": exc.errors(include_url=False)},
            ) from exc
        if parsed.confidence <= 0:
            raise ValidationError("BOBA decisions require non-zero confidence.")
        if not parsed.reasoning.evidence:
            raise ValidationError("BOBA decisions require evidence.")
        parameters = parsed.output_directive.parameters
        forbidden = {
            "override_safety",
            "ignore_safety",
            "bypass_copyright",
            "direct_render",
            "direct_publish",
        }
        if forbidden & parameters.keys() or any(parameters.get(name) for name in forbidden):
            raise ValidationError("BOBA directives cannot override safety or execute publishing.")
        if parsed.output_directive.target_system == "safety" and parameters.get("status") == "safe":
            raise ValidationError("BOBA cannot declare content copyright-safe.")
        return parsed

    def register_decision(
        self, project_id: str, decision: BobaDecisionV1 | dict[str, Any]
    ) -> dict[str, Any]:
        parsed = self.validate_decision(decision)
        if parsed.project_id != project_id:
            raise ValidationError("BOBA decision project id does not match the route project.")
        self.store.append_decision(parsed)
        return self.route_directive(parsed)

    def route_directive(self, decision: BobaDecisionV1) -> dict[str, Any]:
        return {
            "decision_id": decision.decision_id,
            "target_system": decision.output_directive.target_system,
            "delivery": "advisory",
            "consumed": False,
            "reason": (
                "BOBA Core Brain V1 records directives for inspection; existing Olympus "
                "engines remain authoritative and do not consume them automatically."
            ),
            "directive": decision.output_directive.model_dump(mode="json"),
        }
    def attach_advisory_metadata(
        self, project_id: str, decision: BobaDecisionV1
    ) -> dict[str, Any]:
        self.validate_decision(decision)
        if project_id != decision.project_id:
            raise ValidationError("BOBA metadata project mismatch.")
        return {
            "brain_version": "1",
            "mode": "advise",
            "decisions_present": True,
            "decision_id": decision.decision_id,
            "decision_type": decision.decision_type,
            "summary": decision.reasoning.explanation_for_user,
            "confidence": decision.confidence,
            "target_system": decision.output_directive.target_system,
            "applied": False,
            "warnings": [
                "BOBA directive is advisory and has not been applied by the target engine."
            ],
        }

    def list_project_decisions(self, project_id: str) -> list[BobaDecisionV1]:
        return self.store.list_decisions(project_id)

    def summarize_decisions(self, project_id: str) -> dict[str, Any]:
        decisions = self.list_project_decisions(project_id)
        return {
            "project_id": project_id,
            "count": len(decisions),
            "by_type": {
                kind: sum(item.decision_type == kind for item in decisions)
                for kind in sorted({item.decision_type for item in decisions})
            },
            "targets": sorted({item.output_directive.target_system for item in decisions}),
            "applied": False,
            "mode": "advisory",
        }
