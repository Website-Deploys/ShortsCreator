"""The Story Engine - the narrative understanding pipeline.

Where the Cognitive Engine understands *what exists* in a video, the Story
Engine understands *what the video is trying to say*. It consumes the Cognitive
Engine's output (primarily the transcript) and produces a structured, persisted
narrative understanding: narrative sections, the opening hook, topic shifts, the
narrative arc, setup-to-payoff links, emotional turning points, information
density, context dependencies, a story graph, and an engineering summary.

It is a fully independent, replaceable sibling of the Cognitive Engine: separate
entities, contracts, analyzers, pipeline, repository, and service. Each analyzer
is real where it has the inputs it needs and honestly reports "unavailable"
otherwise - it never fabricates a narrative, and every conclusion carries a
confidence score and supporting evidence.
"""

from olympus.story.pipeline import StoryPipeline, build_default_story_analyzers

__all__ = ["StoryPipeline", "build_default_story_analyzers"]
