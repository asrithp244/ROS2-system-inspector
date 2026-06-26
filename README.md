# ros2_commissioning_check

A CLI tool that validates a running ROS2 system against a YAML spec file. Runs on **ROS2 Humble / Ubuntu 22.04**.

Checks node presence, topic publish rates, message types, topic liveness, and TF frame connectivity — all concurrently — then outputs a Markdown report with a `PASS` / `PARTIAL` / `FAIL` verdict.

```bash
ros2_commissioning_check --profile turtlebot4 --output report.md --verbose
```

---

## Table of Contents

1. [When to Use This](#when-to-use-this)
2. [Build & Install](#build--install)
3. [Running the Demo](#running-the-demo)
4. [CLI Usage](#cli-usage)
5. [Spec File Format](#spec-file-format)
6. [Exit Codes](#exit-codes)
7. [Example Output](#example-output)
8. [Writing Custom Profiles](#writing-custom-profiles)
9. [Architecture](#architecture)
10. [Known Limitations](#known-limitations)

---

## When to Use This

Useful any time you need to confirm a ROS2 system is healthy — after a fresh deployment, before handing off to a customer, or as a smoke test in CI against a Gazebo simulation. The Markdown report gives you something concrete to attach to a commissioning sign-off.

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
git clone https://github.com/asrithp244/ROS2-system-inspector.git ros2_commissioning_check

cd ~/ros2_ws
colcon build --packages-select ros2_commissioning_check
source install/setup.bash
```

### Development install (no colcon)

```bash
cd ~/ros2_ws/src/ros2_commissioning_check
pip install -e . --break-system-packages
```

---

## Running the Demo

No real hardware needed. `demo/demo_system.py` spins up fake publishers for all topics in `profiles/demo.yaml`.

**Terminal 1 — start the fake system:**
```bash
source /opt/ros/humble/setup.bash
python3 demo/demo_system.py
```

**Terminal 2 — run the check:**
```bash
source ~/ros2_ws/install/setup.bash
ros2_commissioning_check --profile demo --verbose
```

Expected result: 19/19 checks pass. See `demo/sample_output.md` for the actual output.

---

## CLI Usage

```
usage: ros2_commissioning_check [-h] --profile PROFILE [--output OUTPUT]
                                [--concurrency N] [--verbose] [--no-color]

options:
  --profile PROFILE, -p PROFILE
        YAML spec file path, or bare profile name (e.g. 'turtlebot4').

  --output OUTPUT, -o OUTPUT
        Write the Markdown report to a file instead of stdout.

  --concurrency N, -c N
        Max concurrent subprocess checks (default: 8).

  --verbose, -v
        Print each check result as it completes.

  --no-color
        Strip emoji from output (useful for CI log parsers).
```

```bash
# Run a bundled profile
ros2_commissioning_check --profile turtlebot4

# Save report to file
ros2_commissioning_check --profile turtlebot4 --output report.md --verbose

# Use a custom spec
ros2_commissioning_check --profile /path/to/my_robot.yaml --verbose

# CI — exit code tells you pass/fail
ros2_commissioning_check --profile turtlebot4 --output report.md
echo "Exit: $?"   # 0=PASS 1=PARTIAL 2=FAIL
```

---

## Spec File Format

```yaml
name: My Robot
description: Full stack check for MyRobot v2.

defaults:
  hz_timeout: 12.0      # seconds to run `ros2 topic hz`
  echo_timeout: 6.0     # seconds to wait for one message
  tf_timeout: 6.0       # seconds to wait for tf2_echo

nodes:
  - name: /my_driver_node
  - name: /optional_debugger
    required: false       # WARN on absence instead of FAIL

topics:
  - name: /scan
    expected_type: sensor_msgs/msg/LaserScan
    min_hz: 8.0           # FAIL if below this
    warn_hz: 9.5          # WARN if below this (but above min_hz)
    required: true
    hz_timeout: 15.0      # per-topic override

  - name: /cmd_vel
    expected_type: geometry_msgs/msg/Twist
    # no hz threshold → falls back to echo check (is anything publishing?)

tf_pairs:
  - parent: map
    child: base_link
    required: true
    timeout: 10.0
```

### Field reference

#### `nodes[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Full node name (`/` prefix optional) |
| `required` | bool | `true` | If `false`, absence is WARN not FAIL |

#### `topics[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Full topic name |
| `min_hz` | float | null | FAIL if measured rate is below this |
| `warn_hz` | float | null | WARN if below this (must be ≥ min_hz) |
| `expected_type` | string | null | e.g. `sensor_msgs/msg/LaserScan` |
| `required` | bool | `true` | If `false`, failures become WARNs |
| `hz_timeout` | float | 10.0 | Seconds to run `ros2 topic hz` |
| `echo_timeout` | float | 5.0 | Seconds to wait for one message |

#### `tf_pairs[]`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `parent` | string | — | Parent TF frame |
| `child` | string | — | Child TF frame |
| `required` | bool | `true` | If `false`, missing transform is WARN |
| `timeout` | float | 5.0 | Seconds to wait for tf2_echo output |

---

## Exit Codes

| Code | Verdict | Meaning |
|------|---------|---------|
| 0 | `PASS` | All required checks passed |
| 1 | `PARTIAL` | No required failures, but warnings exist |
| 2 | `FAIL` | One or more required checks failed |

---

## Example Output

See `demo/sample_output.md` for a real PASS run. Below is an example FAIL run showing what the report looks like when a sensor and a TF frame are down.

```markdown
# ROS2 Commissioning Report — TurtleBot4 Standard Commissioning

> **Profile:** `profiles/turtlebot4.yaml`
> **ROS Distro:** humble
> **Timestamp:** 2026-06-26T14:30:00Z

## 📊 Summary

| Metric        | Count |
|---------------|-------|
| Total checks  | 38    |
| ✅ Passed     | 33    |
| ❌ Failed     | 2     |
| ⚠️ Warnings   | 1     |

## 📡 Topic Publish Rate (Hz)

| Topic   | Required | Expected           | Measured | Status  | Notes                     |
|---------|----------|--------------------|----------|---------|---------------------------|
| `/scan` | Yes      | ≥8.0 Hz (required) | 3.21 Hz  | ❌ FAIL | Rate below minimum 8.0 Hz |
| `/odom` | Yes      | ≥20.0 Hz (required)| 31.44 Hz | ✅ PASS | —                         |

## 🌐 TF Frame Connectivity

| Transform (parent → child) | Required | Status  | Details                                  |
|----------------------------|----------|---------|------------------------------------------|
| `map → odom`               | Yes      | ❌ FAIL | LookupException (frame never published)  |
| `odom → base_link`         | Yes      | ✅ PASS | Translation: (0.012, 0.003, 0.000)       |

---

# ❌ OVERALL VERDICT: FAIL
```

---

## Writing Custom Profiles

The fastest way to build a spec for a new robot is to run it first and capture what's actually there:

```bash
ros2 node list
ros2 topic list -t
ros2 run tf2_tools view_frames
```

Then copy the closest bundled profile and edit it to match:

```bash
cp $(ros2 pkg prefix ros2_commissioning_check)/share/ros2_commissioning_check/profiles/turtlebot4.yaml \
   ~/my_robot.yaml
```

Start with `required: false` on anything you're not sure about, confirm it passes, then flip it to `required: true`.

---

## Architecture

```
ros2_commissioning_check/
├── CMakeLists.txt
├── package.xml
├── setup.py / setup.cfg
├── profiles/
│   ├── demo.yaml
│   ├── turtlebot4.yaml
│   └── manipulator.yaml
├── demo/
│   ├── demo_system.py        # fake publishers for demo.yaml
│   └── sample_output.md      # real PASS run output
└── ros2_commissioning_check/
    ├── models.py             # spec dataclasses and result types
    ├── checker.py            # asyncio subprocess runners
    ├── reporter.py           # Markdown renderer
    └── main.py               # CLI entry point
```

All checks run concurrently via `asyncio.gather()`. An `asyncio.Semaphore` caps concurrent subprocesses at 8 by default. Node presence is a single `ros2 node list` call fanned out to all specs. Hz and TF checks use streaming line-by-line reads so output printed before the process is killed on timeout isn't lost.

---

## Known Limitations

- Tested on **ROS2 Humble only**. Iron/Jazzy should work but haven't been tested.
- Hz measurements have some jitter on VMs or low-resource machines — set `min_hz` conservatively.
- `ros2 topic echo --once` liveness check can rarely pick up a ROS warning line as a message. Doesn't affect Hz-checked topics since those skip the echo check.

---

## License

Apache-2.0
