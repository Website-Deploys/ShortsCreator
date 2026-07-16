"""Validate real long videos, existing projects, and rendered Olympus outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.validation.long_video import (  # noqa: E402
    CLI_TIER_CHOICES,
    DEFAULT_LONG_REPORT_DIR,
    LongVideoOptions,
    aggregate_reports,
    build_discovery_report,
    discover_long_video_samples,
    validate_local_metadata,
    validate_with_backend,
    write_long_video_reports,
)
from olympus.validation.real_video import (  # noqa: E402
    DEFAULT_SAMPLE_DIRS,
    ValidationHttpClient,
    git_branch,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="One local source video")
    parser.add_argument("--samples-dir", type=Path, help="Folder of source videos")
    parser.add_argument("--project-id", help="Validate an existing Olympus project")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--discover", action="store_true", help="Discover and classify samples")
    mode.add_argument("--metadata-only", action="store_true", help="Probe source without backend")
    mode.add_argument("--planning-only", action="store_true", help="Stop after planning validation")
    mode.add_argument("--full-pipeline", action="store_true", help="Validate through real renders")
    mode.add_argument("--smoke", action="store_true", help="Run fast source/environment checks")
    parser.add_argument("--skip-render", action="store_true", help="Alias for --planning-only")
    parser.add_argument("--from-link", action="store_true", help="Require link-project provenance")
    parser.add_argument("--tier", choices=CLI_TIER_CHOICES)
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument("--content-category", default="auto")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_LONG_REPORT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--stage-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    parser.add_argument("--min-clips", type=int)
    parser.add_argument("--max-clips", type=int)
    parser.add_argument("--require-rendered-clips", action="store_true")
    parser.add_argument("--require-audio", action="store_true")
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    _validate_args(parser, args)
    return args


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.file and args.project_id:
        parser.error("--file and --project-id are mutually exclusive")
    if args.samples_dir and args.project_id:
        parser.error("--samples-dir and --project-id are mutually exclusive")
    if args.skip_render and args.full_pipeline:
        parser.error("--skip-render cannot be combined with --full-pipeline")
    if args.from_link and not args.project_id:
        parser.error("--from-link requires --project-id")
    if args.timeout_seconds <= 0 or args.stage_timeout_seconds <= 0:
        parser.error("timeout values must be positive")
    if args.poll_interval_seconds <= 0:
        parser.error("--poll-interval-seconds must be positive")
    if args.min_clips is not None and args.min_clips < 0:
        parser.error("--min-clips cannot be negative")
    if args.max_clips is not None and args.max_clips < 1:
        parser.error("--max-clips must be at least 1")
    if (
        args.min_clips is not None
        and args.max_clips is not None
        and args.min_clips > args.max_clips
    ):
        parser.error("--min-clips cannot exceed --max-clips")


def _mode(args: argparse.Namespace) -> str:
    if args.discover:
        return "discover"
    if args.smoke or args.tier == "smoke":
        return "smoke"
    if args.planning_only or args.skip_render:
        return "planning_only"
    if args.full_pipeline:
        return "full_pipeline"
    if args.project_id:
        return "existing_project"
    return "metadata_only"


def _options(args: argparse.Namespace, mode: str) -> LongVideoOptions:
    return LongVideoOptions(
        mode=mode,
        tier=args.tier,
        timeout_seconds=args.timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        min_clips=args.min_clips,
        max_clips=args.max_clips,
        require_rendered_clips=args.require_rendered_clips,
        require_audio=args.require_audio,
        from_link=args.from_link,
        keep_artifacts=args.keep_artifacts,
        debug=args.debug,
    )


def main() -> int:
    args = _parse_args()
    workspace = ROOT
    branch = git_branch(workspace)
    mode = _mode(args)
    options = _options(args, mode)
    sample_dirs = [args.samples_dir] if args.samples_dir else list(DEFAULT_SAMPLE_DIRS)
    explicit = [args.file] if args.file else []

    if mode == "discover":
        samples = discover_long_video_samples(
            explicit_files=explicit,
            sample_dirs=sample_dirs,
            tier=args.tier,
        )
        report = build_discovery_report(
            workspace=workspace,
            branch=branch,
            tier=args.tier,
            samples=samples,
            report_dir=args.report_dir,
        )
    elif args.project_id:
        client = ValidationHttpClient(args.base, timeout_seconds=30.0)
        report = validate_with_backend(
            workspace=workspace,
            branch=branch,
            client=client,
            base_url=args.base,
            report_dir=args.report_dir,
            options=options,
            project_id=args.project_id,
            content_category=args.content_category,
        )
    else:
        if args.file and not args.file.exists():
            report = validate_local_metadata(
                workspace=workspace,
                branch=branch,
                path=args.file,
                options=options,
                report_dir=args.report_dir,
            )
        else:
            samples = discover_long_video_samples(
                explicit_files=explicit,
                sample_dirs=[] if args.file else sample_dirs,
                tier=args.tier,
            )
            if mode == "smoke" and not samples:
                report = validate_local_metadata(
                    workspace=workspace,
                    branch=branch,
                    path=None,
                    options=options,
                    report_dir=args.report_dir,
                )
            elif not samples:
                report = build_discovery_report(
                    workspace=workspace,
                    branch=branch,
                    tier=args.tier,
                    samples=[],
                    report_dir=args.report_dir,
                )
            else:
                selected = samples[:1] if mode == "smoke" else samples
                reports = []
                for sample in selected:
                    path = Path(str(sample["path"]))
                    if mode in {"planning_only", "full_pipeline"}:
                        client = ValidationHttpClient(args.base, timeout_seconds=30.0)
                        reports.append(
                            validate_with_backend(
                                workspace=workspace,
                                branch=branch,
                                client=client,
                                base_url=args.base,
                                report_dir=args.report_dir,
                                options=options,
                                source_path=path,
                                content_category=args.content_category,
                            )
                        )
                    else:
                        reports.append(
                            validate_local_metadata(
                                workspace=workspace,
                                branch=branch,
                                path=path,
                                options=options,
                                report_dir=args.report_dir,
                            )
                        )
                report = aggregate_reports(reports)

    paths = write_long_video_reports(report, args.report_dir)
    top = report["long_video_validation_v2"]
    print(
        json.dumps(
            {
                "reports": paths,
                "result": top.get("result"),
                "project_id": top.get("project_id"),
                "mode": top.get("mode"),
                "real_video_validation": top.get("real_video_validation"),
            },
            indent=2,
        )
    )
    status = str(top.get("result", {}).get("status") or "")
    if status == "NO_SAMPLES":
        return 0
    return 0 if top.get("result", {}).get("passed") is True else 1


if __name__ == "__main__":
    sys.exit(main())
