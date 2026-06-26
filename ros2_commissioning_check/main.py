#!/usr/bin/env python3
"""
ros2_commissioning_check — ROS2 system commissioning validator.

Reads a YAML spec file, concurrently validates the running ROS2 system
against the spec using subprocess calls, and writes a structured Markdown
commissioning report.

Exit codes
----------
0  PASS    — all required checks passed
1  PARTIAL — warnings or optional failures; no required failures
2  FAIL    — one or more required checks failed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .checker import (
    check_nodes,
    check_tf_pair,
    check_topic_echo,
    check_topic_hz,
    check_topic_type,
)
from .models import CheckResult, CommissioningSpec, Report
from .reporter import render_report

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

try:
    from ament_index_python.packages import get_package_share_directory
    PROFILES_DIR = Path(get_package_share_directory("ros2_commissioning_check")) / "profiles"
except (ImportError, KeyError):
    # Fallback for development / non-colcon installs
    PROFILES_DIR = Path(__file__).parent.parent / "profiles"
DEFAULT_CONCURRENCY = 8   # max concurrent subprocess invocations
DEFAULT_NODE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_profile(profile: str) -> Path:
    """
    Resolve a profile argument to an absolute path.

    Accepts:
      - An absolute or relative path to a .yaml file
      - A bare name like "turtlebot4" → looks up profiles/turtlebot4.yaml in
        the package's installed profiles directory
    """
    p = Path(profile)
    if p.suffix in (".yaml", ".yml") or p.is_absolute():
        if p.exists():
            return p.resolve()
        # Try relative to cwd
        cwd_p = Path.cwd() / p
        if cwd_p.exists():
            return cwd_p.resolve()
        raise FileNotFoundError(f"Profile file not found: {p}")

    # Bare name — look in bundled profiles directory
    for suffix in (".yaml", ".yml"):
        candidate = PROFILES_DIR / (profile + suffix)
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        f"No profile named '{profile}' found in {PROFILES_DIR}. "
        f"Available: {', '.join(str(f.stem) for f in PROFILES_DIR.glob('*.yaml'))}"
    )


def _detect_ros_distro() -> str:
    return os.environ.get("ROS_DISTRO", "unknown")


def _make_report(spec: CommissioningSpec, profile_path: Path) -> Report:
    return Report(
        spec_name=spec.name,
        spec_description=spec.description,
        profile_path=str(profile_path),
        timestamp=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ros_distro=_detect_ros_distro(),
    )


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------

async def run_checks(
    spec: CommissioningSpec,
    report: Report,
    concurrency: int,
    verbose: bool,
) -> None:
    """
    Concurrently execute all checks defined in *spec* and populate *report*.
    """
    sem = asyncio.Semaphore(concurrency)

    # -------------------------------------------------------------------------
    # 1. Node checks — single `ros2 node list` call, fan-out per spec
    # -------------------------------------------------------------------------
    if spec.nodes:
        if verbose:
            print(f"[nodes] Checking {len(spec.nodes)} node(s)…", flush=True)
        node_results = await check_nodes(spec.nodes, timeout=DEFAULT_NODE_TIMEOUT)
        for r in node_results:
            report.add(r)
            _print_result(r, verbose)

    # -------------------------------------------------------------------------
    # 2. Topic checks — Hz, type, and echo run concurrently per topic
    # -------------------------------------------------------------------------
    topic_tasks: List[asyncio.Task] = []

    for t in spec.topics:
        # Hz check (skipped internally if no threshold is set)
        topic_tasks.append(asyncio.create_task(
            check_topic_hz(t, sem), name=f"hz:{t.name}"
        ))
        # Type check (skipped internally if no type is set)
        topic_tasks.append(asyncio.create_task(
            check_topic_type(t, sem), name=f"type:{t.name}"
        ))
        # Echo liveness check only when no Hz threshold is set
        # (Hz check already implies liveness; avoid duplicate waits)
        if t.min_hz is None and t.warn_hz is None:
            topic_tasks.append(asyncio.create_task(
                check_topic_echo(t, sem), name=f"echo:{t.name}"
            ))

    if topic_tasks:
        if verbose:
            print(f"[topics] Running {len(topic_tasks)} topic check(s) concurrently…", flush=True)
        topic_results: List[CheckResult] = await asyncio.gather(*topic_tasks)
        for r in topic_results:
            report.add(r)
            _print_result(r, verbose)

    # -------------------------------------------------------------------------
    # 3. TF checks — each tf2_echo runs concurrently
    # -------------------------------------------------------------------------
    tf_tasks = [
        asyncio.create_task(check_tf_pair(tf, sem), name=f"tf:{tf.parent}->{tf.child}")
        for tf in spec.tf_pairs
    ]

    if tf_tasks:
        if verbose:
            print(f"[tf] Checking {len(tf_tasks)} TF pair(s) concurrently…", flush=True)
        tf_results: List[CheckResult] = await asyncio.gather(*tf_tasks)
        for r in tf_results:
            report.add(r)
            _print_result(r, verbose)


def _print_result(r: CheckResult, verbose: bool) -> None:
    if not verbose:
        return
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "ERROR": "🔴"}[r.status.value]
    measured = f" ({r.measured})" if r.measured else ""
    notes = f" — {r.notes}" if r.notes else ""
    print(f"  {icon} [{r.check_type}] {r.name}{measured}{notes}", flush=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ros2_commissioning_check",
        description=(
            "Validate a running ROS2 system against a YAML commissioning spec "
            "and produce a Markdown report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use a bundled profile by name
  ros2_commissioning_check --profile turtlebot4

  # Use an absolute path to a custom spec
  ros2_commissioning_check --profile /path/to/my_robot.yaml

  # Write the report to a file
  ros2_commissioning_check --profile turtlebot4 --output report.md

  # Verbose real-time progress
  ros2_commissioning_check --profile turtlebot4 --verbose

  # Increase concurrency for faster checks on capable systems
  ros2_commissioning_check --profile turtlebot4 --concurrency 16
""",
    )

    parser.add_argument(
        "--profile", "-p",
        required=True,
        help=(
            "YAML spec file path, or bare profile name to load from the "
            "package's bundled profiles directory "
            "(e.g. 'turtlebot4', 'manipulator')."
        ),
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write the Markdown report to this file instead of stdout.",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"Max concurrent subprocess checks (default: {DEFAULT_CONCURRENCY}).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-check results to stderr as they complete.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Suppress emoji and colour in console output (for CI log parsers).",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # Resolve and load the spec
    # -------------------------------------------------------------------------
    try:
        profile_path = _resolve_profile(args.profile)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        spec = CommissioningSpec.from_yaml(str(profile_path))
    except Exception as exc:
        print(f"ERROR: Failed to parse spec file {profile_path}: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        print(f"Loaded spec: {spec.name!r} from {profile_path}", flush=True)
        print(
            f"  Nodes: {len(spec.nodes)}  "
            f"Topics: {len(spec.topics)}  "
            f"TF pairs: {len(spec.tf_pairs)}",
            flush=True,
        )

    # -------------------------------------------------------------------------
    # Build report skeleton and run all checks
    # -------------------------------------------------------------------------
    report = _make_report(spec, profile_path)

    # Use explicit loop lifecycle to suppress asyncio subprocess cleanup noise
    # on Python 3.10 (RuntimeError: Event loop is closed on __del__).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            run_checks(
                spec=spec,
                report=report,
                concurrency=args.concurrency,
                verbose=args.verbose,
            )
        )
        loop.run_until_complete(asyncio.sleep(0.1))  # flush pending callbacks
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

    # -------------------------------------------------------------------------
    # Render and output the Markdown report
    # -------------------------------------------------------------------------
    md = render_report(report)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(md, encoding="utf-8")
        print(f"Report written to: {out_path}", file=sys.stderr)
    else:
        print(md)

    # -------------------------------------------------------------------------
    # Print verdict to stderr for easy CI parsing
    # -------------------------------------------------------------------------
    verdict_line = {
        0: "VERDICT: PASS (exit 0)",
        1: "VERDICT: PARTIAL (exit 1)",
        2: "VERDICT: FAIL (exit 2)",
    }[report.exit_code]
    print(verdict_line, file=sys.stderr)

    sys.exit(report.exit_code)


if __name__ == "__main__":
    main()
