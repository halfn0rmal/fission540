#!/usr/bin/env bash
# Install build dependencies on Ubuntu 24.04.
# Uses the distro OCCT (7.6). Later phases will switch to OCCT 7.8+ built from source.
set -euo pipefail

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git pkg-config \
    qt6-base-dev libgl-dev libglu1-mesa-dev zlib1g-dev libzstd-dev \
    libocct-foundation-dev libocct-modeling-data-dev libocct-modeling-algorithms-dev \
    libocct-visualization-dev libocct-data-exchange-dev libocct-ocaf-dev libocct-draw-dev \
    occt-misc libtbb-dev libfreetype-dev \
    catch2
