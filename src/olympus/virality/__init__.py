"""The Virality Engine - the viral-potential assessment pipeline.

Where the Cognitive Engine understands *what exists* and the Story Engine
understands *what the video is saying*, the Virality Engine answers, for every
part of the video: "how likely is this to perform well as a short-form video,
and why?" It is **not** an editing, clip-generation, recommendation, or rendering
engine.

It is a fully independent, replaceable sibling of the other engines - its own
entities, contracts, analyzers, pipeline, repository, service, and API - and it
consumes only their outputs, never modifying them. Each analyzer is real where it
has the evidence it needs and honestly reports "unavailable" otherwise; every
score carries a confidence, supporting evidence, and limitations.
"""

from olympus.virality.pipeline import ViralityPipeline, build_default_virality_analyzers

__all__ = ["ViralityPipeline", "build_default_virality_analyzers"]
