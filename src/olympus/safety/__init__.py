"""Copyright and platform-readiness risk assessment for Olympus outputs."""

from olympus.safety.checker import (
    CopyrightSafetyChecker,
    copyright_safety_markdown,
    write_copyright_safety_reports,
)
from olympus.safety.contracts import (
    CHECKER_VERSION,
    COPYRIGHT_SAFETY_DISCLAIMER,
    RiskLevel,
    UploadReadiness,
)

__all__ = [
    "CHECKER_VERSION",
    "COPYRIGHT_SAFETY_DISCLAIMER",
    "CopyrightSafetyChecker",
    "RiskLevel",
    "UploadReadiness",
    "copyright_safety_markdown",
    "write_copyright_safety_reports",
]
