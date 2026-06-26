"""
checker.py — Async subprocess wrappers for ROS2 system validation.

Each check_*() coroutine runs one or more `ros2` CLI commands and returns a
CheckResult.  All subprocess calls are wrapped with asyncio.wait_for() so that
a hanging ros2 command (e.g. waiting for a topic with no publisher) never
blocks the overall commissioning run.

Concurrency model
-----------------
All checks are gathered concurrently via asyncio.gather().  The caller
(main.py) limits concurrency with an asyncio.Semaphore to avoid overwhelming
the ROS2 daemon.

Subprocess timeout semantics
-----------------------------
A SIGKILL is sent to the child process on timeout.  `ros2 topic hz` and
`tf2_echo` are intentionally run for the full timeout window so we accumulate
enough output before killing; we use streaming line-by-line reads so that
output printed before the kill is not lost.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import List, Optional, Tuple

# Force unbuffered output from ros2 CLI subprocesses so output is flushed
# immediately even when piped (Python buffers stdout when not a tty).
_SUBPROCESS_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}

from .models import CheckResult, NodeSpec, Status, TFSpec, TopicSpec


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run(
    cmd: list[str],
    timeout: float,
    stdin_data: Optional[bytes] = None,
) -> Tuple[int, str, str]:
    """
    Run *cmd* as a subprocess, capturing stdout/stderr via communicate().

    Returns (returncode, stdout, stderr).
    returncode == -1 on timeout; stderr will contain "TIMEOUT".
    returncode == -2 on OSError (e.g. ros2 not on PATH).

    Use this for commands that exit quickly (node list, topic info, etc.).
    For long-running commands that need to be killed on timeout, use
    _run_streaming() so output printed before the kill is not lost.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data else None,
            env=_SUBPROCESS_ENV,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=timeout,
            )
            return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return -1, "", "TIMEOUT"
    except OSError as exc:
        return -2, "", str(exc)


async def _run_streaming(
    cmd: list[str],
    timeout: float,
) -> Tuple[int, str, str]:
    """
    Run *cmd* as a subprocess, reading stdout line-by-line as output arrives.

    Unlike _run(), this captures output printed BEFORE the process is killed
    on timeout — critical for `ros2 topic hz` and `tf2_echo` which we
    intentionally kill after a measurement window.

    Returns (returncode, stdout, stderr).
    returncode == -1 on timeout.
    returncode == -2 on OSError.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_SUBPROCESS_ENV,
        )

        stdout_lines: List[str] = []

        async def _drain_stdout() -> None:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                stdout_lines.append(line.decode(errors="replace"))

        timed_out = False
        try:
            await asyncio.wait_for(_drain_stdout(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

        # Drain stderr (best-effort, short timeout)
        stderr_b = b""
        try:
            assert proc.stderr is not None
            stderr_b = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

        rc = -1 if timed_out else (proc.returncode or 0)
        return rc, "".join(stdout_lines), stderr_b.decode(errors="replace")

    except OSError as exc:
        return -2, "", str(exc)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences that some ros2 CLI versions emit."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# Node check
# ---------------------------------------------------------------------------

async def check_nodes(
    node_specs: list[NodeSpec],
    timeout: float = 5.0,
) -> list[CheckResult]:
    """
    Run `ros2 node list` once and compare against all NodeSpecs.

    Returns one CheckResult per NodeSpec.
    """
    rc, stdout, stderr = await _run(["ros2", "node", "list"], timeout=timeout)

    if rc == -2:
        # ros2 binary not found — critical environment failure
        return [
            CheckResult(
                check_type="node",
                name=spec.name,
                status=Status.ERROR,
                notes=f"ros2 binary not found: {stderr}",
                required=spec.required,
            )
            for spec in node_specs
        ]

    if rc not in (0, -1):
        return [
            CheckResult(
                check_type="node",
                name=spec.name,
                status=Status.ERROR,
                notes=f"`ros2 node list` exited {rc}: {stderr.strip()}",
                required=spec.required,
            )
            for spec in node_specs
        ]

    active_nodes = {
        line.strip()
        for line in _strip_ansi(stdout).splitlines()
        if line.strip().startswith("/")
    }

    results: list[CheckResult] = []
    for spec in node_specs:
        node_name = spec.name if spec.name.startswith("/") else f"/{spec.name.lstrip('/')}"
        if node_name in active_nodes:
            results.append(
                CheckResult(
                    check_type="node",
                    name=spec.name,
                    status=Status.PASS,
                    measured="present",
                    expected="present",
                    required=spec.required,
                )
            )
        else:
            results.append(
                CheckResult(
                    check_type="node",
                    name=spec.name,
                    status=Status.FAIL if spec.required else Status.WARN,
                    measured="absent",
                    expected="present",
                    notes=f"Node not found in `ros2 node list` output ({len(active_nodes)} nodes active)",
                    required=spec.required,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Topic Hz check
# ---------------------------------------------------------------------------

_HZ_RE = re.compile(r"average rate:\s*([\d.]+)", re.MULTILINE)


async def check_topic_hz(spec: TopicSpec, semaphore: asyncio.Semaphore) -> CheckResult:
    """
    Run `ros2 topic hz <topic>` for spec.hz_timeout seconds and parse the
    average publish rate.  Fails if below spec.min_hz; warns if below
    spec.warn_hz.
    """
    if spec.min_hz is None and spec.warn_hz is None:
        # Nothing to measure; skip Hz check for this topic
        return CheckResult(
            check_type="topic_hz",
            name=spec.name,
            status=Status.PASS,
            notes="No Hz threshold defined — skipped",
            required=spec.required,
        )

    async with semaphore:
        # --window 10: emit a reading after every 10 messages so we get at
        # least one result even with DDS discovery overhead eating into the
        # timeout.  _run_streaming() reads line-by-line so output printed
        # before we kill the process on timeout is not lost.
        rc, stdout, stderr = await _run_streaming(
            ["ros2", "topic", "hz", "--window", "10", spec.name],
            timeout=spec.hz_timeout,
        )

    stdout = _strip_ansi(stdout)
    stderr = _strip_ansi(stderr)

    # rc == -1 means we timed out — that's expected; we parse whatever was printed
    if rc == -2:
        return CheckResult(
            check_type="topic_hz",
            name=spec.name,
            status=Status.ERROR,
            notes=f"ros2 binary not found: {stderr}",
            required=spec.required,
        )

    matches = _HZ_RE.findall(stdout)
    if not matches:
        return CheckResult(
            check_type="topic_hz",
            name=spec.name,
            status=Status.FAIL if spec.required else Status.WARN,
            expected=_hz_label(spec.min_hz, spec.warn_hz),
            measured="no data",
            notes=(
                "No Hz measurements received within "
                f"{spec.hz_timeout:.1f}s window. "
                "Topic may not be publishing."
            ),
            required=spec.required,
        )

    # Use the last reported average (most up-to-date measurement)
    measured_hz = float(matches[-1])
    measured_str = f"{measured_hz:.2f} Hz"
    expected_str = _hz_label(spec.min_hz, spec.warn_hz)

    if spec.min_hz is not None and measured_hz < spec.min_hz:
        return CheckResult(
            check_type="topic_hz",
            name=spec.name,
            status=Status.FAIL,
            expected=expected_str,
            measured=measured_str,
            notes=f"Rate {measured_hz:.2f} Hz is below minimum {spec.min_hz} Hz",
            required=spec.required,
        )

    if spec.warn_hz is not None and measured_hz < spec.warn_hz:
        return CheckResult(
            check_type="topic_hz",
            name=spec.name,
            status=Status.WARN,
            expected=expected_str,
            measured=measured_str,
            notes=f"Rate {measured_hz:.2f} Hz is below advisory threshold {spec.warn_hz} Hz",
            required=spec.required,
        )

    return CheckResult(
        check_type="topic_hz",
        name=spec.name,
        status=Status.PASS,
        expected=expected_str,
        measured=measured_str,
        required=spec.required,
    )


def _hz_label(min_hz: Optional[float], warn_hz: Optional[float]) -> str:
    parts = []
    if min_hz is not None:
        parts.append(f"≥{min_hz} Hz (required)")
    if warn_hz is not None:
        parts.append(f"≥{warn_hz} Hz (advisory)")
    return ", ".join(parts) if parts else "N/A"


# ---------------------------------------------------------------------------
# Topic type check  (`ros2 topic info`)
# ---------------------------------------------------------------------------

_TYPE_RE = re.compile(r"^Type:\s*(.+)$", re.MULTILINE)


async def check_topic_type(spec: TopicSpec, semaphore: asyncio.Semaphore) -> CheckResult:
    """
    Run `ros2 topic info <topic>` and verify the message type matches
    spec.expected_type.
    """
    if spec.expected_type is None:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.PASS,
            notes="No type constraint defined — skipped",
            required=spec.required,
        )

    async with semaphore:
        rc, stdout, stderr = await _run(
            ["ros2", "topic", "info", spec.name],
            timeout=5.0,
        )

    stdout = _strip_ansi(stdout)

    if rc == -2:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.ERROR,
            notes=f"ros2 binary not found: {stderr}",
            required=spec.required,
        )

    if rc != 0 and rc != -1:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.FAIL if spec.required else Status.WARN,
            expected=spec.expected_type,
            measured="error",
            notes=f"`ros2 topic info` exited {rc}: {stderr.strip()[:200]}",
            required=spec.required,
        )

    match = _TYPE_RE.search(stdout)
    if not match:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.FAIL if spec.required else Status.WARN,
            expected=spec.expected_type,
            measured="not found",
            notes="Could not parse type from `ros2 topic info` output",
            required=spec.required,
        )

    actual_type = match.group(1).strip()
    if actual_type == spec.expected_type:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.PASS,
            expected=spec.expected_type,
            measured=actual_type,
            required=spec.required,
        )
    else:
        return CheckResult(
            check_type="topic_type",
            name=spec.name,
            status=Status.FAIL,
            expected=spec.expected_type,
            measured=actual_type,
            notes="Message type mismatch — verify topic remapping and package versions",
            required=spec.required,
        )


# ---------------------------------------------------------------------------
# Topic echo check  (`ros2 topic echo --once`)
# ---------------------------------------------------------------------------

async def check_topic_echo(spec: TopicSpec, semaphore: asyncio.Semaphore) -> CheckResult:
    """
    Run `ros2 topic echo --once <topic>` to confirm the topic is actively
    publishing at least one message.  Used when min_hz is not set but we still
    want to verify the topic is alive.
    """
    async with semaphore:
        rc, stdout, stderr = await _run(
            ["ros2", "topic", "echo", "--once", spec.name],
            timeout=spec.echo_timeout,
        )

    if rc == -2:
        return CheckResult(
            check_type="topic_echo",
            name=spec.name,
            status=Status.ERROR,
            notes=f"ros2 binary not found: {stderr}",
            required=spec.required,
        )

    stdout = _strip_ansi(stdout)

    # A successful echo exits 0 with YAML-formatted message on stdout.
    # On timeout (rc == -1) no message was received within echo_timeout.
    if rc == -1 or (rc != 0 and not stdout.strip()):
        return CheckResult(
            check_type="topic_echo",
            name=spec.name,
            status=Status.FAIL if spec.required else Status.WARN,
            measured="no message",
            expected="≥1 message",
            notes=(
                f"No message received within {spec.echo_timeout:.1f}s. "
                "Topic may have no publishers."
            ),
            required=spec.required,
        )

    # Grab first non-empty line of the echoed message as a preview
    preview_lines = [l for l in stdout.splitlines() if l.strip()]
    preview = preview_lines[0][:80] if preview_lines else "(empty)"

    return CheckResult(
        check_type="topic_echo",
        name=spec.name,
        status=Status.PASS,
        measured="message received",
        expected="≥1 message",
        notes=f"First line: {preview}",
        required=spec.required,
    )


# ---------------------------------------------------------------------------
# TF check  (`ros2 run tf2_ros tf2_echo`)
# ---------------------------------------------------------------------------

_TF_TRANSLATION_RE = re.compile(r"Translation:\s*[\(\[](.+?)[\)\]]", re.DOTALL)
_TF_AT_TIME_RE = re.compile(r"At time [\d.]+")


async def check_tf_pair(spec: TFSpec, semaphore: asyncio.Semaphore) -> CheckResult:
    """
    Run `ros2 run tf2_ros tf2_echo <parent> <child>` for spec.timeout seconds.
    A single line containing "At time" or "Translation:" indicates the transform
    is being published.
    """
    check_name = f"{spec.parent} → {spec.child}"

    async with semaphore:
        # _run_streaming() so "At time" lines printed before we kill the
        # process on timeout are captured (communicate() would discard them).
        rc, stdout, stderr = await _run_streaming(
            ["ros2", "run", "tf2_ros", "tf2_echo", spec.parent, spec.child],
            timeout=spec.timeout,
        )

    if rc == -2:
        return CheckResult(
            check_type="tf",
            name=check_name,
            status=Status.ERROR,
            notes=f"ros2 binary not found: {stderr}",
            required=spec.required,
        )

    stdout = _strip_ansi(stdout)
    stderr = _strip_ansi(stderr)

    # On timeout we kill the process; if it printed at least one transform, PASS
    if _TF_AT_TIME_RE.search(stdout) or _TF_TRANSLATION_RE.search(stdout):
        # Extract a translation sample if available
        m = _TF_TRANSLATION_RE.search(stdout)
        translation = m.group(1).strip() if m else "see log"
        return CheckResult(
            check_type="tf",
            name=check_name,
            status=Status.PASS,
            measured="transform present",
            expected="transform present",
            notes=f"Translation: ({translation})",
            required=spec.required,
        )

    # No transform output — check stderr for diagnostic clues
    extra = ""
    if "Could not transform" in stderr or "ExtrapolationException" in stderr:
        extra = " — ExtrapolationException (time sync issue?)"
    elif "LookupException" in stderr or "lookup would require" in stderr:
        extra = " — LookupException (frame never published)"
    elif "ConnectivityException" in stderr:
        extra = " — ConnectivityException (frames not connected)"
    elif rc == -1:
        extra = f" — no transform received in {spec.timeout:.1f}s"

    return CheckResult(
        check_type="tf",
        name=check_name,
        status=Status.FAIL if spec.required else Status.WARN,
        measured="transform absent",
        expected="transform present",
        notes=f"TF lookup failed{extra}",
        required=spec.required,
    )
