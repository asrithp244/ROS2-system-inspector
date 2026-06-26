cmake_minimum_required(VERSION 3.8)
project(ros2_commissioning_check)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

install(
  PROGRAMS
    ros2_commissioning_check/main.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY profiles/
  DESTINATION share/${PROJECT_NAME}/profiles
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
