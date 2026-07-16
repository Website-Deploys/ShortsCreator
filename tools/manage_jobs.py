"""Inspect and control Olympus Durable Job Queue / Resume V2 locally."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from olympus.api.dependencies import build_workflow_service
from olympus.platform.errors import NotFoundError
from olympus.services.workflow import WorkflowService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("job_id")
    project = commands.add_parser("project")
    project.add_argument("project_id")
    for name in ("resume", "retry", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
    commands.add_parser("recover-stale")
    commands.add_parser("worker")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    service = build_workflow_service(run_in_process=False)
    try:
        if args.command == "list":
            return {"jobs": await service.list_jobs()}
        if args.command == "show":
            job = await service.get_durable_job(args.job_id)
            if job is None:
                raise NotFoundError("Durable job not found.", details={"job_id": args.job_id})
            return job
        if args.command == "project":
            return {"jobs": await service.list_jobs(project_id=args.project_id)}
        if args.command == "resume":
            return await service.resume_by_job_id(args.job_id)
        if args.command == "retry":
            return await service.retry_by_job_id(args.job_id)
        if args.command == "cancel":
            return await service.cancel_by_job_id(args.job_id)
        if args.command == "recover-stale":
            recovered = await service.recover()
            return {"recovered_jobs": recovered, "scheduler": await service.scheduler_status()}
        if args.command == "worker":
            return await _worker(service)
        raise ValueError(f"Unsupported command: {args.command}")
    finally:
        await service.stop_pool()


async def _worker(service: WorkflowService) -> dict[str, Any]:
    recovered = await service.recover()
    service.start_pool(force=True)
    print(json.dumps({"worker": "running", "recovered_jobs": recovered}, indent=2))
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        return {"worker": "stopped", "recovered_jobs": recovered}


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
