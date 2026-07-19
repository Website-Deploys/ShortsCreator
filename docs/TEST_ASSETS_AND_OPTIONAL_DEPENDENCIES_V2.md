# Test Assets and Optional Dependencies V2

Olympus keeps the core application importable without local ML, computer-vision,
OCR, diarization, object-detection, or video-link packages. These capabilities are
reported as unavailable until their explicit dependencies and any required local
models or binaries are present.

No model weights, music, video, or remote assets are downloaded automatically.

## Required Local Tools

- Python 3.11 or newer is required by the package.
- FFmpeg and FFprobe are required for media extraction, rendering, probing, and
  media-backed validators.
- Git is required by the repository hygiene validator.
- Tesseract is optional and is only useful with an installed OCR adapter.

The core API can import without the optional ML/CV packages. A workflow that selects
an unavailable provider fails with an actionable configuration error rather than
silently claiming that provider ran.

## Installation Groups

Core application:

```powershell
pip install -e .
```

Development tools:

```powershell
pip install -e ".[dev]"
```

Local Faster-Whisper transcription and its CTranslate2 runtime:

```powershell
pip install -e ".[transcription]"
```

OpenCV-based local vision support:

```powershell
pip install -e ".[vision]"
```

Video-link ingestion:

```powershell
pip install -e ".[video-links]"
```

OCR (`pytesseract` or `easyocr`), diarization (`pyannote.audio`), and optional
object-detection packages (`ultralytics` or `torchvision`) are capability-detected,
but Olympus does not currently bundle provider-specific extras or model weights for
them. Installing a Python package alone does not prove a model-backed feature is
ready.

## Availability Contract

`src/olympus/dependencies.py` is the shared optional-dependency boundary:

- `is_module_available(name)` checks availability without importing a heavy package.
- `get_optional_dependency_status()` returns deterministic JSON-safe status records.
- `require_optional_dependency(name, feature_name)` imports lazily and raises a
  structured `ConfigurationError` with an install hint when unavailable.

Faster-Whisper and CTranslate2 are loaded only when the real transcription provider
is used. OpenCV, OCR, diarization, and object-detection discovery also avoids loading
those packages during normal Olympus imports.

Missing optional dependencies are warnings in the dependency validator. Missing
FFmpeg/FFprobe, invalid required JSON fixtures, unsafe tracked media, or a validator
that cannot import are failures.

## Music Manifest Policy

The committed canonical manifest is:

```text
assets/music/music_manifest.json
```

It is deliberately empty and contains no remote URL, absolute user path, or
copyrighted file reference. The file gives clean clones a deterministic schema while
preserving truthful runtime behavior: no tracks means no music is available, and the
renderer must not mark music as mixed.

Real music stays local and must have documented rights. Use the curated music-library
tooling to import and validate it. The repository ignore rules allow only the empty
canonical JSON manifest under `assets/`; generated or user audio remains ignored.

## Test Fixture Policy

- Tests that exercise registry behavior create manifests under `tmp_path`.
- Tests that need audio generate a tiny synthetic fixture during the test.
- Tests never depend on a developer's local `assets/` contents.
- Optional-provider tests inject fakes or assert the honest unavailable state.
- Media integration tests must check FFmpeg/FFprobe availability and skip clearly or
  return a failed self-check when those tools are absent.
- Generated media, model weights, reports, and caches are never staged.

The Faster-Whisper unit suite injects a fake model. It validates adapter behavior but
does not prove that local transcription works without the optional packages and model
weights.

## Validator

Run the local capability self-check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_test_assets_dependencies.py --self-check
```

Run repository policy and import checks:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_test_assets_dependencies.py --repo-check
```

Reports are written to the ignored directory:

```text
work/validation_reports/test_assets_dependencies/
  test_assets_dependencies_report.json
  test_assets_dependencies_summary.md
```

The repository check validates the canonical music JSON, scans for absolute user paths
and remote references, rejects tracked/staged media and generated paths, checks for
top-level imports of known optional packages, and imports the relevant validators.

## Validation Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe -m ruff check src tests tools
D:\Olympus\.venv\Scripts\python.exe -m pytest tests/unit/test_dependencies.py tests/unit/test_music_manifest_assets.py
D:\Olympus\.venv\Scripts\python.exe -m mypy src/olympus tools/validate_test_assets_dependencies.py
```

## Known Limitations

- The committed music library contains no production tracks, so music quality and
  audibility are not validated by this pass.
- Missing Faster-Whisper/CTranslate2 means real local transcription is unavailable.
- Missing OpenCV means OpenCV-backed face or visual validation is unavailable.
- OCR, diarization, and object detection still require separately configured packages,
  binaries, and models.
- A passing dependency self-check proves local prerequisites and repository hygiene;
  it is not a release-readiness or media-quality claim.
