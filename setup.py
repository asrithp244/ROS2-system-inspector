from setuptools import find_packages, setup
import os
from glob import glob

package_name = "ros2_commissioning_check"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "profiles"), glob("profiles/*.yaml")),
    ],
    install_requires=["setuptools", "pyyaml"],
    zip_safe=True,
    maintainer="Your Name",
    maintainer_email="you@example.com",
    description=(
        "CLI tool that validates actual ROS2 system state against a YAML "
        "commissioning specification and produces a structured Markdown report."
    ),
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "ros2_commissioning_check = ros2_commissioning_check.main:main",
        ],
    },
)
