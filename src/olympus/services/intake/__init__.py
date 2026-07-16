"""Video intake: accept and validate uploads, store them, start the pipeline.

In this milestone the intake service handles direct video uploads (validation +
streaming storage). Pipeline kickoff and persistence arrive with the project
state machine in a later milestone.
"""

from olympus.services.intake.link import (
    DownloadedFile,
    LinkDownloadRecord,
    LinkDownloadStatus,
    LinkIngestionMode,
    VideoLinkIntakeService,
)
from olympus.services.intake.service import (
    ALLOWED_VIDEO_EXTENSIONS,
    IntakeService,
    UploadRecord,
)

__all__ = [
    "ALLOWED_VIDEO_EXTENSIONS",
    "DownloadedFile",
    "IntakeService",
    "LinkDownloadRecord",
    "LinkDownloadStatus",
    "LinkIngestionMode",
    "UploadRecord",
    "VideoLinkIntakeService",
]
