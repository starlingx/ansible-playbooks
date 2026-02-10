#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
set_worker_cpu_memory.py

Sets both CPU and memory reservations for worker HostProfiles.

Features:
  - node0 memory in MiB  (human friendly)
  - node0 platform CPUs configurable
  - --add-node1 adds 1 CPU + 1 GiB on node 1 (both CPU and memory)

Examples:
  # Classic Wind River worker (7 GiB + 1 CPU on node0)
  ./set_worker_cpu_memory.py --node0-mib 7168 input.yaml > worker.yaml

  # 8 GiB memory + 2 platform CPUs on node0
  ./set_worker_cpu_memory.py --node0-mib 8192 --node0-cpus 2 input.yaml > worker.yaml

  # Dual-socket: 10 GiB + 2 CPUs on node0, 1 CPU + 1 GiB on node1
  ./set_worker_cpu_memory.py --node0-mib 10240 --node0-cpus 2 --add-node1 input.yaml > worker.yaml
"""

import sys
import yaml
import argparse


def mib_to_pages(mib: int) -> int:
    return mib * 256


def build_memory_section(node0_mib: int, add_node1: bool):
    node0_pages = mib_to_pages(node0_mib)
    memory = [
        {
            "functions": [{"function": "platform", "pageCount": node0_pages, "pageSize": "4KB"}],
            "node": 0
        }
    ]
    if add_node1:
        memory.append(
            {
                "functions": [{"function": "platform", "pageCount": 256000, "pageSize": "4KB"}],
                "node": 1
            }
        )
    return memory


def build_processors_section(node0_cpus: int, add_node1: bool):
    processors = [
        {
            "functions": [{"function": "platform", "count": node0_cpus}],
            "node": 0
        }
    ]
    if add_node1:
        processors.append(
            {
                "functions": [{"function": "platform", "count": 1}],
                "node": 1
            }
        )
    return processors


def update_profile(doc, node0_mib: int, node0_cpus: int, add_node1: bool):
    if not isinstance(doc, dict) or doc.get("kind") != "HostProfile":
        return doc

    name = doc["metadata"].get("name", "<unnamed>")
    spec = doc.get("spec", {})

    pages = mib_to_pages(node0_mib)
    gib = pages * 4 / 1024 / 1024

    print(f"Updating profile: {name}", file=sys.stderr)
    print(f"  CPUs  -> node0: {node0_cpus} core(s)", end="", file=sys.stderr)
    print(f" | node1: {1 if add_node1 else 0} core(s)" if add_node1 else "", file=sys.stderr)
    print(f"  Memory-> node0: {node0_mib:,} MiB ({gib:.2f} GiB)", end="", file=sys.stderr)
    print(" | node1: 1 GiB" if add_node1 else "", file=sys.stderr)

    # Replace or add memory
    if "memory" in spec:
        print("    Replacing existing memory section", file=sys.stderr)
    spec["memory"] = build_memory_section(node0_mib, add_node1)

    # Replace or add processors
    if "processors" in spec:
        print("    Replacing existing processors section", file=sys.stderr)
    spec["processors"] = build_processors_section(node0_cpus, add_node1)

    return doc


def main():
    parser = argparse.ArgumentParser(description="Set CPU + Memory reservations for worker profiles")
    parser.add_argument("--node0-mib", type=int, default=7168,
                        help="Memory to reserve on node 0 in MiB (default: 7168 ≈ traditional 7 GiB)")
    parser.add_argument("--node0-cpus", type=int, default=1,
                        help="Number of platform CPUs on node 0 (default: 1)")
    parser.add_argument("--add-node1", action="store_true",
                        help="Also reserve 1 CPU + 1 GiB on NUMA node 1")
    parser.add_argument("input_file", help="Input YAML file")
    args = parser.parse_args()

    # Summary header
    pages = mib_to_pages(args.node0_mib)
    gib = pages * 4 / 1024 / 1024
    print("Configuration:", file=sys.stderr)
    print(f"  node0: {args.node0_cpus} CPU(s) + {args.node0_mib:,} MiB ({gib:.2f} GiB)", file=sys.stderr)
    if args.add_node1:
        print("  node1: 1 CPU + 1 GiB", file=sys.stderr)
    print(file=sys.stderr)

    with open(args.input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    updated = []
    for doc in docs:
        if doc is None:
            continue
        updated.append(update_profile(doc, args.node0_mib, args.node0_cpus, args.add_node1))

    yaml.safe_dump_all(
        updated,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,
    )


if __name__ == "__main__":
    main()
