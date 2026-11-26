#!/usr/bin/env bash
# Install build dependencies on Arch Linux (and derivatives such as Omarchy).
# Uses the distro OCCT (7.9 at the time of writing).
#
# Installs without refreshing the package databases (no -y): installing against
# a freshly synced database on an out-of-date system is a partial upgrade, which
# Arch does not support. Bring the system up to date first (pacman -Syu, or
# `omarchy update` on Omarchy); if a package then 404s, the system is behind.
set -euo pipefail

sudo pacman -S --needed --noconfirm \
    base-devel cmake ninja git pkgconf python \
    qt6-base mesa glu zlib zstd freetype2 onetbb \
    opencascade \
    catch2
