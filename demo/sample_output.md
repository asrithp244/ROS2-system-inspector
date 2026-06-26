# ROS2 Commissioning Report — Demo System — No Hardware Required
> **Profile:** `profiles/demo.yaml`  
> **ROS Distro:** humble  
> **Timestamp:** 2026-06-26T22:53:10Z  
> **Description:** Minimal spec that validates against demo_system.py fake publishers. Use this profile to show PASS output for portfolio / interview demos.
  
## 📊 Summary
| Metric | Count |
| ------------------------- | -------- |
| Total checks | 19 |
| ✅ Passed | 19 |
| ❌ Failed | 0 |
| ⚠️ Warnings | 0 |
| 🔴 Errors | 0 |

## 🤖 Node Presence
| Node | Required | Status | Notes |
| ---------------------------------------- | -------- | ---------- | ---------------------------------------- |
| `/demo_system` | Yes | ✅ PASS | — |

## 📡 Topic Publish Rate (Hz)
| Topic | Required | Expected | Measured | Status | Notes |
| --------------------------------------------- | -------- | ---------------------- | ------------ | ---------- | ---------------------------------------- |
| `/scan` | Yes | ≥8.0 Hz (required) | 9.99 Hz | ✅ PASS | — |
| `/odom` | Yes | ≥20.0 Hz (required) | 25.02 Hz | ✅ PASS | — |
| `/imu` | Yes | ≥45.0 Hz (required) | 48.84 Hz | ✅ PASS | — |
| `/battery_state` | Yes | ≥0.5 Hz (required) | 1.00 Hz | ✅ PASS | — |
| `/tf` | Yes | ≥20.0 Hz (required) | 39.28 Hz | ✅ PASS | — |

## 📦 Topic Message Types
| Topic | Required | Expected Type | Actual Type | Status |
| --------------------------------------------- | -------- | ---------------------------------------- | ---------------------------------------- | ---------- |
| `/scan` | Yes | `sensor_msgs/msg/LaserScan` | `sensor_msgs/msg/LaserScan` | ✅ PASS |
| `/odom` | Yes | `nav_msgs/msg/Odometry` | `nav_msgs/msg/Odometry` | ✅ PASS |
| `/imu` | Yes | `sensor_msgs/msg/Imu` | `sensor_msgs/msg/Imu` | ✅ PASS |
| `/battery_state` | Yes | `sensor_msgs/msg/BatteryState` | `sensor_msgs/msg/BatteryState` | ✅ PASS |
| `/cmd_vel` | Yes | `geometry_msgs/msg/Twist` | `geometry_msgs/msg/Twist` | ✅ PASS |
| `/tf` | Yes | `tf2_msgs/msg/TFMessage` | `tf2_msgs/msg/TFMessage` | ✅ PASS |

## 📨 Topic Liveness (Echo Check)
| Topic | Required | Status | Notes |
| --------------------------------------------- | -------- | ---------- | ------------------------------------------------------------ |
| `/cmd_vel` | Yes | ✅ PASS | First line: linear: |

## 🌐 TF Frame Connectivity
| Transform (parent → child) | Required | Status | Details |
| ---------------------------------------- | -------- | ---------- | ------------------------------------------------------------ |
| `odom → base_footprint` | Yes | ✅ PASS | Translation: (0.000, 0.000, 0.000) |
| `map → odom` | Yes | ✅ PASS | Translation: (0.000, 0.000, 0.000) |
| `base_footprint → base_link` | Yes | ✅ PASS | Translation: (0.000, 0.000, 0.050) |
| `base_link → laser_frame` | Yes | ✅ PASS | Translation: (0.000, 0.000, 0.180) |
| `base_link → imu_link` | Yes | ✅ PASS | Translation: (0.000, 0.000, 0.100) |

## 🔍 Anomalies
_No anomalies detected._

---

# ✅ OVERALL VERDICT: PASS
All required checks passed. The system meets the commissioning specification and is cleared for operation.

_Exit code: 0_