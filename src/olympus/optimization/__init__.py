"""The Optimization & AI Enhancement Engine - the post-render polish pipeline.

Where the Rendering Engine produces a finished MP4, the Optimization Engine makes
that Short as polished and engaging as possible **without changing the story**:
it analyses and enhances audio, recommends copyright-free music, optimizes
captions and typography, refines visuals, proposes thumbnail candidates,
evaluates quality, generates export variants, and assembles downloadable publish
packages per platform.

It is a fully independent, replaceable sibling of the other engines - its own
entities, contracts, stages, pipeline, repository, service, and API - and it
consumes only their outputs plus the Rendering Engine's manifest. It never
re-renders, re-encodes, scrapes or downloads copyrighted media, or changes the
story decided upstream. When the rendered media or an enhancement model is
absent, it reports ``UNAVAILABLE``/``UNKNOWN`` honestly rather than fabricating a
result.
"""

from olympus.optimization.pipeline import (
    OptimizationPipeline,
    build_default_optimization_analyzers,
)

__all__ = ["OptimizationPipeline", "build_default_optimization_analyzers"]
