# ros2_commissioning_check

A CLI tool for validating a running ROS2 system against a YAML-defined commissioning specification. Runs on **ROS2 Humble / Ubuntu 22.04**.

It concurrently checks node presence, topic publish rates, message types, topic liveness, and TF frame connectivity, then produces a structured Markdown commissioning report with a `PASS` / `PARTIAL` / `FAIL` verdict.

```
ros2_commissioning_check --profile turtlebot4 --output report.md --verbose
```

---

## Table of Contents

1. [When to Use This Tool](#when-to-use-this-tool)
2. [Build & Install](#build--install)
3. [CLI Usage](#cli-usage)
4. [Spec File Format](#spec-file-format)
5. [Exit Codes](#exit-codes)
6. [Example Output](#example-output)
7. [Writing Custom Profiles](#writing-custom-profiles)
8. [Architecture](#architecture)

---

## When to Use This Tool

- **Post-deployment acceptance testing** — run after bringing up a new robot cell to confirm all drivers, navigation, and sensor stacks are alive.
- **Regression checks in CI** — run in simulation (Gazebo + a ROS bag replay) as a smoke test on every PR.
- **Field commissioning** — hand the Markdown report to a customer as a signed-off commissioning document.
- **Debugging** — quickly triage which layer of the stack (drivers, middleware, navigation) is unhealthy.

---

## Build & Install

### Prerequisites

```bash
sudo apt install ros-humble-ros-base python3-yaml
source /opt/ros/humble/setup.bash
```

### Build with colcon

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone <repo-url> ros2_commissioning_check

cd ~/ros2_ws
colcon build --packages-select ros2_commissioning_check
source install/setup.bash
```

### (Optional) pip install for development

```bash
cd ~/ros2_ws/src/ros2_commissioning_check
pip install -e . --break-system-packages
```

---

## CLI Usage

```
usage: ros2_commissioning_check [-h] --profile PROFILE [--output OUTPUT]
                                [--concurrency N] [--verbose] [--no-color]

options:
  --profile PROFILE, -p PROFILE
        YAML spec file path, or bare name of a bundled profile
        (e.g. 'turtlebot4', 'manipulator').

  --output OUTPUT, -o OUTPUT
        Write the Markdown report to this file (default: stdout).

  --concurrency N, -c N
        Max concurrent subprocess checks (default: 8).
        Increase on fast machines to reduce total check time.

  --verbose, -v
        Print per-check results to stderr as they complete.

  --no-color
        Suppress emoji in console output (for plain-text CI log parsers).
```

### Quick examples

```bash
# Bundled profile by name (output to terminal)
ros2_commissioning_check --profile turtlebot4

# Custom spec file with verbose progress and report saved to disk
ros2_commissioning_check --profile /path/to/my_robot.yaml \
  --output /tmp/commissioning_report.md --verbose

# CI usage — exit code drives pass/fail
ros2_commissioning_check --profile turtlebot4 --output report.md
echo "Exit: $?"   # 0=PASS 1=PARTIAL 2=FAIL

# Manipulator profile with high concurrency
ros2_commissioning_check --profile manipulator --concurrency 16
```

---

## Spec File Format

A spec file is a YAML document with four top-level sections.

```yaml
name: My Robot Commissioning Spec
description: Validates the full stack for MyRobot v2.

# Optional: override global timeouts (seconds)
defaults:
  hz_timeout: 12.0      # window for `ros2 topic hz` measurements
  echo_timeout: 6.0     # timeout for `ros2 topic echo --once`
  tf_timeout: 6.0       # timeout for `tf2_echo`

nodes:
  - name: /my_driver_node          # required: true (default)
  - name: /optional_debugger
    required: false                # WARN on absence, don't FAIL

topics:
  - name: /scan
    expected_type: sensor_msgs/msg/LaserScan  # checked via `ros2 topic info`
    min_hz: 8.0          # FAIL if measured rate < 8 Hz
    warn_hz: 9.5          # WARN if measured rate < 9.5 Hz (but ≥ min_hz)
    required: true
    hz_timeout: 15.0     # override global default for this topic

  - name: /cmd_vel
    expected_type: geometry_msgs/msg/Twist
    # No Hz threshold → tool runs `ros2 topic echo --once` for liveness

tf_pairs:
  - parent: map
    child: base_link
    required: true
    timeout: 10.0        # override global default for this pair
```

### Field reference

#### `nodes[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Full node name (leading `/` optional) |
| `required` | bool | `true` | If `false`, absence is WARN not FAIL |

#### `topics[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Full topic name |
| `min_hz` | float | null | Minimum publish rate (Hz). FAIL below this. |
| `warn_hz` | float | null | Advisory Hz floor. WARN below this (but ≥ min_hz). |
| `expected_type` | string | null | Full message type string, e.g. `sensor_msgs/msg/LaserScan` |
| `required` | bool | `true` | If `false`, failures become WARNs |
| `hz_timeout` | float | 10.0 | Seconds to run `ros2 topic hz` (overrides `defaults.hz_timeout`) |
| `echo_timeout` | float | 5.0 | Seconds to wait for one message (overrides `defaults.echo_timeout`) |

#### `tf_pairs[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `parent` | string | — | Parent TF frame name |
| `child` | string | — | Child TF frame name |
| `required` | bool | `true` | If `false`, missing transform is WARN |
| `timeout` | float | 5.0 | Seconds to wait for `tf2_echo` output |

---

## Exit Codes

| Code | Verdict | Meaning |
|------|---------|---------|
| 0 | `PASS` | All required checks passed |
| 1 | `PARTIAL` | Warnings or optional failures; no required failures |
| 2 | `FAIL` | One or more required checks failed |

---

## Example Output

Below is a sample Markdown report for a TurtleBot4 with one failing sensor and one TF anomaly.

```markdown
# ROS2 Commissioning Report — TurtleBot4 Standard Commissioning

> **Profile:** `/opt/ros/humble/share/ros2_commissioning_check/profiles/turtlebot4.yaml`
> **ROS Distro:** humble
> **Timestamp:** 2026-06-26T14:30:00Z
> **Description:** Validates Nav2, slam_toolbox, sensor drivers, and TF tree...

## 📊 Summary

| Metric        | Count |
|---------------|-------|
| Total checks  | 38    |
| ✅ Passed     | 33    |
| ❌ Failed     | 2     |
| ⚠️ Warnings   | 1     |
| 🔴 Errors     | 0     |

## 🤖 Node Presence

| Node                       | Required | Status    | Notes                        |
|----------------------------|----------|-----------|------------------------------|
| `/bt_navigator`            | Yes      | ✅ PASS   | —                            |
| `/slam_toolbox`            | Yes      | ✅ PASS   | —                            |
| `/rplidar_node`            | Yes      | ✅ PASS   | —                            |
| `/teleop_twist_keyboard`   | No       | ⚠️ WARN   | Node not found (24 nodes active) |

## 📡 Topic Publish Rate (Hz)

| Topic   | Required | Expected              | Measured  | Status  | Notes                          |
|---------|----------|-----------------------|-----------|---------|--------------------------------|
| `/scan` | Yes      | ≥8.0 Hz (required)    | 3.21 Hz   | ❌ FAIL | Rate below minimum 8.0 Hz      |
| `/odom` | Yes      | ≥20.0 Hz (required)   | 31.44 Hz  | ✅ PASS | —                              |
| `/imu`  | Yes      | ≥50.0 Hz (required)   | 62.17 Hz  | ✅ PASS | —                              |

## 🌐 TF Frame Connectivity

| Transform (parent → child) | Required | Status  | Details                              |
|----------------------------|----------|---------|--------------------------------------|
| `map → odom`               | Yes      | ❌ FAIL | LookupException (frame never published) |
| `odom → base_link`         | Yes      | ✅ PASS | Translation: (0.012, 0.003, 0.000)   |

## 🔍 Anomalies & Action Items

### ❌ FAIL `/scan` (topic_hz)
- **Expected:** ≥8.0 Hz (required)
- **Measured:** 3.21 Hz
- **Details:** Rate 3.21 Hz is below minimum 8.0 Hz

### ❌ FAIL `map → odom` (tf)
- **Expected:** transform present
- **Measured:** transform absent
- **Details:** TF lookup failed — LookupException (frame never published)

---

# ❌ OVERALL VERDICT: FAIL

One or more **required** checks failed. The system does **not** meet
the commissioning specification. Address failures before deployment.

_Exit code: 2_
```

---

## Writing Custom Profiles

1. Copy a bundled profile as a starting point:
   ```bash
   cp $(ros2 pkg prefix ros2_commissioning_check)/share/ros2_commissioning_check/profiles/turtlebot4.yaml \
      ~/my_robot.yaml
   ```

2. Edit `~/my_robot.yaml` — update node names, topic names, Hz thresholds, and TF pairs to match your robot's URDF and launch configuration.

3. Run:
   ```bash
   ros2_commissioning_check --profile ~/my_robot.yaml --verbose
   ```

4. Iterate: start with `required: false` on new entries, confirm they PASS, then promote to `required: true`.

**Pro tip:** use `ros2 node list`, `ros2 topic list -t`, and `ros2 run tf2_tools view_frames` on a known-good robot to generate the initial spec content quickly.

---

## Architecture

```
ros2_commissioning_check/
├── CMakeLists.txt              # ament_cmake build rules
├── package.xml                 # ROS2 package manifest
├── setup.py / setup.cfg        # Python package entry point
├── resource/
│   └── ros2_commissioning_check  # ament resource marker
├── profiles/
│   ├── turtlebot4.yaml         # bundled TurtleBot4 spec
│   └── manipulator.yaml        # bundled 6-DOF manipulator spec
└── ros2_commissioning_check/
    ├── __init__.py
    ├── models.py               # CommissioningSpec, CheckResult, Report dataclasses
    ├── checker.py              # asyncio subprocess wrappers (nodes, Hz, type, echo, TF)
    ├── reporter.py             # Markdown report renderer
    └── main.py                 # CLI entry point + asyncio orchestration
```

### Concurrency model

All checks run concurrently via `asyncio.gather()`. A single `asyncio.Semaphore` limits the number of concurrent subprocesses (default: 8) to avoid overwhelming the ROS2 daemon.

Node presence uses a single `ros2 node list` call; results are fanned out to all `NodeSpec` entries with no additional subprocesses. Topic Hz, type, echo, and TF checks each spawn their own subprocess with a configurable per-check timeout enforced via `asyncio.wait_for()`.

### Subprocess timeout guarantees

Every subprocess is wrapped with `asyncio.wait_for(..., timeout=N)`. On timeout, `SIGKILL` is sent and the process is reaped before the result is recorded. This ensures the tool always terminates within a bounded time even if a topic has no publisher or a TF frame is permanently missing.

---

## License

Apache-2.0
