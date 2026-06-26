#!/usr/bin/env python3
"""
demo_system.py — Minimal fake ROS2 system for ros2_commissioning_check demo.

Spins up the nodes and topics defined in demo.yaml so the tool produces
a PASS report without requiring real hardware.

Run in one terminal:
    python3 demo_system.py

Then in another terminal:
    ros2_commissioning_check --profile demo/demo.yaml --verbose
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
import threading

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, LaserScan, BatteryState
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
from geometry_msgs.msg import TransformStamped
import math


class DemoSystem(Node):
    def __init__(self):
        super().__init__('demo_system')
        self.get_logger().info('Demo system starting...')

        best_effort = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )

        # Publishers
        self.scan_pub = self.create_publisher(LaserScan, '/scan', 10)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.imu_pub  = self.create_publisher(Imu, '/imu', 10)
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.battery_pub = self.create_publisher(BatteryState, '/battery_state', 10)

        # TF broadcasters
        self.tf_broadcaster = TransformBroadcaster(self)
        self.static_tf_broadcaster = StaticTransformBroadcaster(self)

        # Publish static transforms once
        self._publish_static_transforms()

        # Timers — publish at rates that satisfy demo.yaml thresholds
        self.create_timer(0.1,  self._pub_scan)       # 10 Hz  (min 8 Hz)
        self.create_timer(0.04, self._pub_odom)       # 25 Hz  (min 20 Hz)
        self.create_timer(0.02, self._pub_imu)        # 50 Hz  (min 50 Hz)
        self.create_timer(0.1,  self._pub_cmd_vel)    # 10 Hz
        self.create_timer(1.0,  self._pub_battery)    # 1 Hz   (min 0.5 Hz)
        self.create_timer(0.05, self._pub_tf)         # 20 Hz  (min 20 Hz)

        self.get_logger().info('Demo system running. Press Ctrl+C to stop.')

    # ------------------------------------------------------------------ #
    # Static TF (one-shot)
    # ------------------------------------------------------------------ #
    def _publish_static_transforms(self):
        now = self.get_clock().now().to_msg()
        static_transforms = [
            ('base_footprint', 'base_link',   0.0,  0.0,  0.05),
            ('base_link',      'laser_frame', 0.0,  0.0,  0.18),
            ('base_link',      'imu_link',    0.0,  0.0,  0.10),
        ]
        msgs = []
        for parent, child, x, y, z in static_transforms:
            t = TransformStamped()
            t.header.stamp = now
            t.header.frame_id = parent
            t.child_frame_id  = child
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = z
            t.transform.rotation.w = 1.0
            msgs.append(t)
        self.static_tf_broadcaster.sendTransform(msgs)

    # ------------------------------------------------------------------ #
    # Dynamic TF (odom → base_footprint, map → odom)
    # ------------------------------------------------------------------ #
    def _pub_tf(self):
        now = self.get_clock().now().to_msg()
        dynamic_pairs = [
            ('odom',          'base_footprint'),
            ('map',           'odom'),
        ]
        for parent, child in dynamic_pairs:
            t = TransformStamped()
            t.header.stamp    = now
            t.header.frame_id = parent
            t.child_frame_id  = child
            t.transform.rotation.w = 1.0
            self.tf_broadcaster.sendTransform(t)

    # ------------------------------------------------------------------ #
    # Sensor publishers
    # ------------------------------------------------------------------ #
    def _pub_scan(self):
        msg = LaserScan()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = 'laser_frame'
        msg.angle_min       = -math.pi
        msg.angle_max       =  math.pi
        msg.angle_increment =  math.pi / 180.0
        msg.range_min       = 0.15
        msg.range_max       = 12.0
        msg.ranges          = [1.0] * 360
        self.scan_pub.publish(msg)

    def _pub_odom(self):
        msg = Odometry()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = 'odom'
        msg.child_frame_id  = 'base_footprint'
        msg.pose.pose.orientation.w = 1.0
        self.odom_pub.publish(msg)

    def _pub_imu(self):
        msg = Imu()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = 'imu_link'
        msg.orientation.w   = 1.0
        msg.linear_acceleration.z = 9.81
        self.imu_pub.publish(msg)

    def _pub_cmd_vel(self):
        self.cmd_vel_pub.publish(Twist())

    def _pub_battery(self):
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.voltage      = 25.2
        msg.percentage   = 0.85
        msg.present      = True
        self.battery_pub.publish(msg)


def main():
    rclpy.init()
    node = DemoSystem()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
