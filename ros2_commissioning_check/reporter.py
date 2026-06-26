"""
reporter.py — Markdown commissioning report generator.

Takes a completed Report object and renders a structured Markdown document
with:
  - Executive summary (verdict badge, counts)
  - Per-section tables: Nodes, Topic Hz, Topic Types, Topic Echo, TF Pairs
  - Anomaly / failure detail section
  - Overall PASS / PARTIAL / FAIL verdict block
"""

from __future__ import annotations

from typing import List

from .models import CheckResult, Report, Status, Verdict


# ---------------------------------------------------------------------------
# Emoji / badge helpers
# ---------------------------------------------------------------------------

_STATUS_BADGE = {
    Status.PASS: "✅ PASS",
    Status.FAIL: "❌ FAIL",
    Status.WARN: "⚠️ WARN",
    Status.ERROR: "🔴 ERROR",
}

_VERDICT_BADGE = {
    Verdict.PASS: "# ✅ OVERALL VERDICT: PASS",
    Verdict.PARTIAL: "# ⚠️ OVERALL VERDICT: PARTIAL",
    Verdict.FAIL: "# ❌ OVERALL VERDICT: FAIL",
}

_VERDICT_DESCRIPTION = {
    Verdict.PASS: (
        "All required checks passed. The system meets the commissioning "
        "specification and is cleared for operation."
    ),
    Verdict.PARTIAL: (
        "Required checks passed, but one or more advisory thresholds or "
        "optional checks did not meet specification. Review warnings before "
        "proceeding to production."
    ),
    Verdict.FAIL: (
        "One or more **required** checks failed. The system does **not** meet "
        "the commissioning specification. Address failures before deployment."
    ),
}


def _table_row(*cells: str) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table_sep(*widths: int) -> str:
    return "| " + " | ".join("-" * max(w, 3) for w in widths) + " |"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_nodes(results: List[CheckResult]) -> str:
    node_results = [r for r in results if r.check_type == "node"]
    if not node_results:
        return ""

    lines = [
        "## 🤖 Node Presence",
        "",
        _table_row("Node", "Required", "Status", "Notes"),
        _table_sep(40, 8, 10, 40),
    ]
    for r in node_results:
        req = "Yes" if r.required else "No"
        lines.append(_table_row(f"`{r.name}`", req, _STATUS_BADGE[r.status], r.notes or "—"))
    lines.append("")
    return "\n".join(lines)


def _render_topic_hz(results: List[CheckResult]) -> str:
    hz_results = [r for r in results if r.check_type == "topic_hz" and r.notes != "No Hz threshold defined — skipped"]
    if not hz_results:
        return ""

    lines = [
        "## 📡 Topic Publish Rate (Hz)",
        "",
        _table_row("Topic", "Required", "Expected", "Measured", "Status", "Notes"),
        _table_sep(45, 8, 22, 12, 10, 40),
    ]
    for r in hz_results:
        req = "Yes" if r.required else "No"
        lines.append(_table_row(
            f"`{r.name}`",
            req,
            r.expected or "—",
            r.measured or "—",
            _STATUS_BADGE[r.status],
            r.notes or "—",
        ))
    lines.append("")
    return "\n".join(lines)


def _render_topic_types(results: List[CheckResult]) -> str:
    type_results = [r for r in results if r.check_type == "topic_type" and r.notes != "No type constraint defined — skipped"]
    if not type_results:
        return ""

    lines = [
        "## 📦 Topic Message Types",
        "",
        _table_row("Topic", "Required", "Expected Type", "Actual Type", "Status"),
        _table_sep(45, 8, 40, 40, 10),
    ]
    for r in type_results:
        req = "Yes" if r.required else "No"
        lines.append(_table_row(
            f"`{r.name}`",
            req,
            f"`{r.expected}`" if r.expected else "—",
            f"`{r.measured}`" if r.measured else "—",
            _STATUS_BADGE[r.status],
        ))
    lines.append("")
    return "\n".join(lines)


def _render_topic_echo(results: List[CheckResult]) -> str:
    echo_results = [r for r in results if r.check_type == "topic_echo"]
    if not echo_results:
        return ""

    lines = [
        "## 📨 Topic Liveness (Echo Check)",
        "",
        _table_row("Topic", "Required", "Status", "Notes"),
        _table_sep(45, 8, 10, 60),
    ]
    for r in echo_results:
        req = "Yes" if r.required else "No"
        lines.append(_table_row(
            f"`{r.name}`",
            req,
            _STATUS_BADGE[r.status],
            r.notes or "—",
        ))
    lines.append("")
    return "\n".join(lines)


def _render_tf(results: List[CheckResult]) -> str:
    tf_results = [r for r in results if r.check_type == "tf"]
    if not tf_results:
        return ""

    lines = [
        "## 🌐 TF Frame Connectivity",
        "",
        _table_row("Transform (parent → child)", "Required", "Status", "Details"),
        _table_sep(40, 8, 10, 60),
    ]
    for r in tf_results:
        req = "Yes" if r.required else "No"
        lines.append(_table_row(
            f"`{r.name}`",
            req,
            _STATUS_BADGE[r.status],
            r.notes or "—",
        ))
    lines.append("")
    return "\n".join(lines)


def _render_anomalies(report: Report) -> str:
    bad = [r for r in report.results if r.status in (Status.FAIL, Status.ERROR, Status.WARN)]
    if not bad:
        return "## 🔍 Anomalies\n\n_No anomalies detected._\n"

    lines = [
        "## 🔍 Anomalies & Action Items",
        "",
    ]
    for r in bad:
        icon = _STATUS_BADGE[r.status]
        lines.append(f"### {icon} `{r.name}` ({r.check_type})")
        lines.append("")
        if r.expected:
            lines.append(f"- **Expected:** {r.expected}")
        if r.measured:
            lines.append(f"- **Measured:** {r.measured}")
        if r.notes:
            lines.append(f"- **Details:** {r.notes}")
        if not r.required:
            lines.append("- _(This check is advisory — failure does not block PASS verdict)_")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------------

def render_report(report: Report) -> str:
    """Return the full Markdown commissioning report as a string."""
    total = len(report.results)
    n_pass = len(report.passed)
    n_fail = len(report.failed)
    n_warn = len(report.warned)
    n_err = len(report.errored)

    sections: List[str] = []

    # ---- Header -------------------------------------------------------------
    sections.append(f"# ROS2 Commissioning Report — {report.spec_name}")
    sections.append("")
    sections.append(f"> **Profile:** `{report.profile_path}`  ")
    sections.append(f"> **ROS Distro:** {report.ros_distro}  ")
    sections.append(f"> **Timestamp:** {report.timestamp}  ")
    if report.spec_description:
        sections.append(f"> **Description:** {report.spec_description}  ")
    sections.append("")

    # ---- Summary ------------------------------------------------------------
    sections.append("## 📊 Summary")
    sections.append("")
    sections.append(_table_row("Metric", "Count"))
    sections.append(_table_sep(25, 8))
    sections.append(_table_row("Total checks", total))
    sections.append(_table_row("✅ Passed", n_pass))
    sections.append(_table_row("❌ Failed", n_fail))
    sections.append(_table_row("⚠️ Warnings", n_warn))
    sections.append(_table_row("🔴 Errors", n_err))
    sections.append("")

    # ---- Per-section tables -------------------------------------------------
    node_section = _render_nodes(report.results)
    if node_section:
        sections.append(node_section)

    hz_section = _render_topic_hz(report.results)
    if hz_section:
        sections.append(hz_section)

    type_section = _render_topic_types(report.results)
    if type_section:
        sections.append(type_section)

    echo_section = _render_topic_echo(report.results)
    if echo_section:
        sections.append(echo_section)

    tf_section = _render_tf(report.results)
    if tf_section:
        sections.append(tf_section)

    # ---- Anomalies ----------------------------------------------------------
    sections.append(_render_anomalies(report))

    # ---- Verdict block ------------------------------------------------------
    verdict = report.verdict
    sections.append("---")
    sections.append("")
    sections.append(_VERDICT_BADGE[verdict])
    sections.append("")
    sections.append(_VERDICT_DESCRIPTION[verdict])
    sections.append("")
    sections.append(f"_Exit code: {report.exit_code}_")
    sections.append("")

    return "\n".join(sections)
