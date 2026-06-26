"""
models.py — Dataclasses for commissioning spec and check results.

CommissioningSpec is the parsed representation of a YAML profile.
CheckResult holds the outcome of a single validation check.
Report aggregates results and computes the overall verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import yaml


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Status(str, Enum):
    """Per-check result status."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"   # threshold advisory (non-blocking)
    ERROR = "ERROR"  # subprocess / environment error


class Verdict(str, Enum):
    """Overall commissioning verdict."""
    PASS = "PASS"        # exit 0 — all required checks passed
    PARTIAL = "PARTIAL"  # exit 1 — warnings or optional failures
    FAIL = "FAIL"        # exit 2 — one or more required checks failed


# ---------------------------------------------------------------------------
# Spec dataclasses (parsed from YAML)
# ---------------------------------------------------------------------------

@dataclass
class NodeSpec:
    """A ROS2 node that must be present in `ros2 node list` output."""
    name: str
    required: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "NodeSpec":
        if isinstance(d, str):
            return cls(name=d)
        return cls(
            name=d["name"],
            required=d.get("required", True),
        )


@dataclass
class TopicSpec:
    """A ROS2 topic with optional Hz threshold and type validation."""
    name: str
    min_hz: Optional[float] = None        # minimum acceptable publish rate (Hz)
    warn_hz: Optional[float] = None       # warn (not fail) below this rate
    expected_type: Optional[str] = None   # e.g. "sensor_msgs/msg/LaserScan"
    required: bool = True
    hz_timeout: float = 10.0              # seconds to run `ros2 topic hz`
    echo_timeout: float = 5.0            # seconds for `ros2 topic echo --once`

    @classmethod
    def from_dict(cls, d: dict) -> "TopicSpec":
        return cls(
            name=d["name"],
            min_hz=d.get("min_hz"),
            warn_hz=d.get("warn_hz"),
            expected_type=d.get("expected_type"),
            required=d.get("required", True),
            hz_timeout=float(d.get("hz_timeout", 10.0)),
            echo_timeout=float(d.get("echo_timeout", 5.0)),
        )


@dataclass
class TFSpec:
    """A required tf2 transform pair (parent → child)."""
    parent: str
    child: str
    required: bool = True
    timeout: float = 5.0   # seconds to wait for `tf2_echo` to produce output

    @classmethod
    def from_dict(cls, d: dict) -> "TFSpec":
        return cls(
            parent=d["parent"],
            child=d["child"],
            required=d.get("required", True),
            timeout=float(d.get("timeout", 5.0)),
        )


@dataclass
class CommissioningSpec:
    """Top-level spec parsed from a YAML profile."""
    name: str
    description: str = ""
    nodes: List[NodeSpec] = field(default_factory=list)
    topics: List[TopicSpec] = field(default_factory=list)
    tf_pairs: List[TFSpec] = field(default_factory=list)

    # Global defaults that individual specs can override
    default_hz_timeout: float = 10.0
    default_echo_timeout: float = 5.0
    default_tf_timeout: float = 5.0

    @classmethod
    def from_dict(cls, d: dict) -> "CommissioningSpec":
        defaults = d.get("defaults", {})
        spec = cls(
            name=d.get("name", "Unnamed Profile"),
            description=d.get("description", ""),
            default_hz_timeout=float(defaults.get("hz_timeout", 10.0)),
            default_echo_timeout=float(defaults.get("echo_timeout", 5.0)),
            default_tf_timeout=float(defaults.get("tf_timeout", 5.0)),
        )

        for node_entry in d.get("nodes", []):
            spec.nodes.append(NodeSpec.from_dict(node_entry))

        for topic_entry in d.get("topics", []):
            t = TopicSpec.from_dict(topic_entry)
            # Apply global defaults if not explicitly set in the topic block
            if "hz_timeout" not in topic_entry:
                t.hz_timeout = spec.default_hz_timeout
            if "echo_timeout" not in topic_entry:
                t.echo_timeout = spec.default_echo_timeout
            spec.topics.append(t)

        for tf_entry in d.get("tf_pairs", []):
            tf = TFSpec.from_dict(tf_entry)
            if "timeout" not in tf_entry:
                tf.timeout = spec.default_tf_timeout
            spec.tf_pairs.append(tf)

        return spec

    @classmethod
    def from_yaml(cls, path: str) -> "CommissioningSpec":
        with open(path, "r") as fh:
            data = yaml.safe_load(fh)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of a single validation check."""
    check_type: str    # "node" | "topic_hz" | "topic_type" | "topic_echo" | "tf"
    name: str          # human-readable identifier (node name, topic name, etc.)
    status: Status
    expected: Optional[str] = None   # what the spec required
    measured: Optional[str] = None   # what was actually observed
    notes: str = ""                  # free-form diagnostic text
    required: bool = True


@dataclass
class Report:
    """Aggregated results for the full commissioning run."""
    spec_name: str
    spec_description: str
    profile_path: str
    timestamp: str
    ros_distro: str
    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    # -----------------------------------------------------------------------
    # Derived counts
    # -----------------------------------------------------------------------

    @property
    def passed(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == Status.PASS]

    @property
    def failed(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == Status.FAIL]

    @property
    def warned(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == Status.WARN]

    @property
    def errored(self) -> List[CheckResult]:
        return [r for r in self.results if r.status == Status.ERROR]

    @property
    def required_failures(self) -> List[CheckResult]:
        return [r for r in self.results if r.status in (Status.FAIL, Status.ERROR) and r.required]

    # -----------------------------------------------------------------------
    # Overall verdict
    # -----------------------------------------------------------------------

    @property
    def verdict(self) -> Verdict:
        if self.required_failures:
            return Verdict.FAIL
        if self.warned or any(
            r.status in (Status.FAIL, Status.ERROR) and not r.required
            for r in self.results
        ):
            return Verdict.PARTIAL
        return Verdict.PASS

    @property
    def exit_code(self) -> int:
        return {Verdict.PASS: 0, Verdict.PARTIAL: 1, Verdict.FAIL: 2}[self.verdict]
