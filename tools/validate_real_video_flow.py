"""Validate Olympus V2 with real local videos and write runtime reports."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.validation.real_video import (  # noqa: E402
    DEFAULT_REPORT_DIR,
    DEFAULT_SAMPLE_DIRS,
    ValidationHttpClient,
    aggregate_report,
    build_empty_report,
    discover_video_samples,
    git_branch,
    run_http_validation_for_sample,
    write_reports,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        action="append",
        type=Path,
        default=[],
        help="Explicit video file",
    )
    parser.add_argument(
        "--samples-dir",
        action="append",
        type=Path,
        default=[],
        help="Directory to search for sample videos",
    )
    parser.add_argument(
        "--tier",
        choices=["tiny", "short", "medium", "long", "very_long", "unknown"],
    )
    parser.add_argument("--smoke", action="store_true", help="Process at most one smallest sample")
    parser.add_argument("--long", action="store_true", help="Only process long/very_long samples")
    parser.add_argument("--discover", action="store_true", help="Only discover/classify videos")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument("--content-category", default="educational")
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--require-audio", action="store_true")
    parser.add_argument("--max-videos", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workspace = Path(__file__).resolve().parents[1]
    branch = git_branch(workspace)
    sample_dirs = args.samples_dir or list(DEFAULT_SAMPLE_DIRS)
    samples = discover_video_samples(
        explicit_files=args.file,
        sample_dirs=sample_dirs,
        tier=args.tier,
        long_only=args.long,
    )
    if args.smoke and samples:
        samples = samples[:1]
    if args.max_videos > 0:
        samples = samples[: args.max_videos]

    mode_bits = []
    if args.discover:
        mode_bits.append("discover")
    if args.smoke:
        mode_bits.append("smoke")
    if args.long:
        mode_bits.append("long")
    if args.tier:
        mode_bits.append(f"tier:{args.tier}")
    mode = "+".join(mode_bits) or "full"

    if args.discover or not samples:
        report = build_empty_report(
            workspace=workspace,
            branch=branch,
            mode=mode,
            samples=samples,
            synthetic_validation=not samples,
        )
        paths = write_reports(report, args.report_dir)
        print(json.dumps({"samples": [s.to_dict() for s in samples], "reports": paths}, indent=2))
        return 0

    started_at = time.monotonic()
    client = ValidationHttpClient(args.base, timeout_seconds=30.0)
    video_reports = []
    for sample in samples:
        print(f"VALIDATING {sample.filename} ({sample.tier}, {sample.duration}s)")
        video_reports.append(
            run_http_validation_for_sample(
                sample=sample,
                client=client,
                report_dir=args.report_dir,
                content_category=args.content_category,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                require_audio=args.require_audio,
            )
        )
    report = aggregate_report(
        workspace=workspace,
        branch=branch,
        mode=mode,
        samples=samples,
        video_reports=video_reports,
        started_at=started_at,
        synthetic_validation=False,
    )
    paths = write_reports(report, args.report_dir)
    print(
        json.dumps(
            {"reports": paths, "summary": report["real_video_validation_report"]},
            indent=2,
        )
    )
    return 0 if report["real_video_validation_report"]["videos_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
