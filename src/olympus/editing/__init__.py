"""The Editing Engine - the non-destructive edit-timeline pipeline.

Where the Clip Planner decides *what* to edit, the Editing Engine decides *how*:
it transforms each approved blueprint into a real, professional, non-destructive
edit timeline (the kind an NLE builds internally) - clip boundaries, cuts,
zooms, crops, captions, silence, markers, transitions, B-roll needs, and more,
all timestamped with reasons, confidence, and evidence.

It is a fully independent, replaceable sibling of the other engines - its own
entities, contracts, stages, pipeline, repository, service, and API - and it
consumes only their outputs. It never renders, encodes, exports, burns captions,
selects music, or generates a Short; it only produces the edit decision list a
future Editing/Render engine can execute exactly.
"""

from olympus.editing.motion import build_motion_intelligence, validate_motion_effects
from olympus.editing.pipeline import EditingPipeline, build_default_editing_analyzers

__all__ = [
    "EditingPipeline",
    "build_default_editing_analyzers",
    "build_motion_intelligence",
    "validate_motion_effects",
]
