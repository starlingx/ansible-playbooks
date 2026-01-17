#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import sys
import json

try:
    data = json.load(sys.stdin)["nodes"]
except Exception as e:
    sys.exit(f"Error loading JSON: {e}")

by_id = {n["id"]: n for n in data}
parent = {c: n["id"] for n in data for c in n.get("children", [])}


def path(osd_id):
    p, chain = parent.get(osd_id), []
    current_node = by_id.get(p)

    while current_node and current_node.get("type") != "root":
        node_type = current_node.get("type")
        node_name = current_node.get("name")
        if node_type and node_name:
            chain.append(f"{node_type}={node_name}")
        p = parent.get(p)
        current_node = by_id.get(p)

    if current_node and current_node.get("type") == "root":
        node_type = current_node.get("type")
        node_name = current_node.get("name")
        if node_type and node_name:
            chain.append(f"{node_type}={node_name}")

    return " ".join(reversed(chain))


for n in data:
    if n.get("type") != "osd":
        continue
    print(json.dumps({
        "osd_id": n.get("id"),
        "osd_class": n.get("device_class"),
        "osd_weight": n.get("crush_weight"),
        "osd_reweight": n.get("reweight"),
        "osd_crush_location": path(n["id"])
    }))
