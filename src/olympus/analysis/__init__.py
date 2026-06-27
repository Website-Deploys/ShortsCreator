"""The Cognitive Engine - the video understanding pipeline.

This package turns an uploaded video into a structured *understanding* (not
clips). It contains the isolated stage analyzers and the orchestrating pipeline.
Each analyzer is real where its tooling/model is configured and honestly reports
"unavailable" otherwise - it never fabricates analysis.
"""

from olympus.analysis.pipeline import AnalysisPipeline, build_default_analyzers

__all__ = ["AnalysisPipeline", "build_default_analyzers"]
