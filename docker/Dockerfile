# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
# ROS 2 Kilted (Ubuntu 24.04) with webots_ros2_driver, for hosts that cannot run Kilted natively.
# Webots itself runs on the host; the driver connects to it as an extern controller over TCP.
FROM ros:kilted-ros-base
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-kilted-webots-ros2-driver \
        python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*
# webots_ros2 looks for a Webots install; the controller library ships with the driver package.
ENV WEBOTS_HOME=/opt/ros/kilted/share/webots_ros2_driver
WORKDIR /ws
CMD ["bash"]
