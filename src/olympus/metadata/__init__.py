"""Upload-ready, signal-grounded metadata for rendered Olympus clips."""

from olympus.metadata.contracts import UPLOAD_METADATA_V2_VERSION, UploadMetadataV2
from olympus.metadata.generator import (
    compact_upload_metadata,
    generate_upload_metadata,
    unavailable_upload_metadata,
)
from olympus.metadata.validation import validate_upload_metadata

__all__ = [
    "UPLOAD_METADATA_V2_VERSION",
    "UploadMetadataV2",
    "compact_upload_metadata",
    "generate_upload_metadata",
    "unavailable_upload_metadata",
    "validate_upload_metadata",
]
