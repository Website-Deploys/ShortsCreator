"""Default enhancement capabilities - honest about what models are present.

The Optimization Engine performs audio/visual/thumbnail enhancement only through
the ports in ``olympus.domain.contracts.enhancement``. This module builds the
*default* :class:`EnhancementCapabilities` for the running environment.

In this deployment no signal-processing or ML enhancement models are installed
(there is no audio DSP toolchain, no denoise/super-resolution model, no vision
model, and no media decoder), so every capability is reported as **unavailable**
with the precise reason. The engine reads these and emits honest
``UNAVAILABLE``/``UNKNOWN`` results instead of fabricating enhancement.

When a deployment installs real models, it constructs an
:class:`EnhancementCapabilities` with the corresponding adapters and capabilities
marked available; no stage code changes - they simply find the capability present
and run it.
"""

from __future__ import annotations

from olympus.domain.contracts.enhancement import Capability, EnhancementCapabilities

# Named capabilities the stages query. Grouped by the stage that consumes them.
_AUDIO_REASON = (
    "no audio enhancement toolchain is installed in this environment (no DSP/"
    "source-separation/loudness model and no media decoder to read the rendered "
    "audio); audio enhancement cannot be performed without fabricating results."
)
_VISUAL_REASON = (
    "no visual enhancement model is installed in this environment (no decoder to "
    "read rendered frames and no sharpen/denoise/colour/upscale model); visual "
    "enhancement cannot be performed without fabricating results."
)
_THUMB_REASON = (
    "no vision model is installed (no face/expression/composition scoring and no "
    "decoder to extract candidate frames); thumbnail image scoring is UNKNOWN."
)

_DEFAULT_CAPABILITIES = {
    # Audio
    "voice_isolation": _AUDIO_REASON,
    "noise_removal": _AUDIO_REASON,
    "hum_removal": _AUDIO_REASON,
    "equalization": _AUDIO_REASON,
    "compression": _AUDIO_REASON,
    "de_essing": _AUDIO_REASON,
    "limiting": _AUDIO_REASON,
    "loudness_normalization": _AUDIO_REASON,
    "audio_analysis": _AUDIO_REASON,
    "music_mixing": _AUDIO_REASON,
    # Visual
    "sharpening": _VISUAL_REASON,
    "denoising": _VISUAL_REASON,
    "color_correction": _VISUAL_REASON,
    "frame_cleanup": _VISUAL_REASON,
    "upscale": _VISUAL_REASON,
    "hdr": _VISUAL_REASON,
    # Thumbnail
    "thumbnail_scoring": _THUMB_REASON,
    "frame_extraction": _THUMB_REASON,
    # Encoding
    "transcode": (
        "no media encoder (e.g. FFmpeg) is installed; the engine plans exports and "
        "compression but cannot execute encoding here."
    ),
}


def build_default_enhancement_capabilities() -> EnhancementCapabilities:
    """Return capabilities reflecting this environment: all unavailable, with reasons."""

    capabilities = {
        name: Capability(name=name, available=False, reason=reason)
        for name, reason in _DEFAULT_CAPABILITIES.items()
    }
    return EnhancementCapabilities(capabilities, audio=None, visual=None, thumbnail=None)
