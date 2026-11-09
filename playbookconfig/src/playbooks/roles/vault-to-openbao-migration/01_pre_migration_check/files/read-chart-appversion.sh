#!/usr/bin/env bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# read-chart-appversion.sh — print the upstream OpenBao appVersion from a staged
# STX app tarball. argv: <app_tarball>. appVersion on stdout.
# Exit: 0 success / 2 usage / 4 tarball/chart not found / 5 appVersion missing.
set -euo pipefail

err() { echo "[read-chart-appversion] $*" >&2; }

[ "$#" -ge 1 ] || { err "usage: read-chart-appversion.sh <app_tarball>"; exit 2; }
tarball="$1"
[ -f "$tarball" ] || { err "app tarball not found: $tarball"; exit 4; }

# openbao-[0-9]* selects the nested server chart, excluding openbao-manager-*.
# Streamed with 'tar -O', so nothing is extracted to disk.
members="$(tar tf "$tarball" | grep 'charts/openbao-[0-9].*\.tgz$' || true)"
[ -n "$members" ] || { err "nested server chart not found in $tarball"; exit 4; }
[ "$(echo "$members" | wc -l)" -eq 1 ] || { err "multiple server charts in $tarball"; exit 4; }

chart="$(tar xf "$tarball" -O "$members" | tar zxf - -O openbao/Chart.yaml)" ||
    { err "openbao Chart.yaml not found in $members"; exit 4; }

version="$(echo "$chart" | awk '/^appVersion:/ {print $2}' | tr -d '"' | sed 's/^v//')"
[ -n "$version" ] || { err "appVersion missing from $members"; exit 5; }

echo "$version"
