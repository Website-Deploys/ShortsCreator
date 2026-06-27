"""The Clip Planner - the editing-blueprint planning pipeline.

Where the Cognitive, Story, and Virality engines understand a video, the Clip
Planner decides *what should be edited*: it produces ranked, fully-specified
editing blueprints - one per proposed Short - consuming only the three upstream
engines' outputs. It is **not** an editing, rendering, or clip-generation engine;
it never touches video.

It is a fully independent, replaceable sibling of the other engines - its own
entities, contracts, stages, pipeline, repository, service, and API. Each stage
is real where it has the evidence it needs and honestly returns zero clips (with
an explanation) rather than forcing low-quality plans; every plan and decision
carries confidence and supporting evidence.
"""

from olympus.planning.pipeline import ClipPlanningPipeline, build_default_planning_analyzers

__all__ = ["ClipPlanningPipeline", "build_default_planning_analyzers"]
