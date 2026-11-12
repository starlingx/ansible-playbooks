#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Compare the OpenBao inventory (stdin) against the Phase 2 source inventory.
Must match exactly: engine/auth mounts, policies (minus --builtin-policy on the target) and,
at --level values, secret paths and value hashes. Audit device names are compared.
No hash is printed.
Exit: 0 equivalent / 2 usage / 3 source level mismatch / 4 inventory unreadable / 6 not equivalent."""
import argparse
import json
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple

EXIT_LEVEL = 3
EXIT_INPUT = 4
EXIT_MISMATCH = 6
DIMENSIONS = ("engine_mounts", "auth_mounts", "audit_devices", "secret_paths", "policies",
              "values")
NAMED = ("engine_mounts", "auth_mounts", "audit_devices", "policies")  # safe to list by name


class InputError(Exception):
    """An inventory is missing, unreadable, or at the wrong level."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def err(msg: str) -> None:
    """Write a one-line diagnostic to stderr."""
    print("[compare-inventory] %s" % msg, file=sys.stderr)


def load(text: str, what: str) -> Dict[str, Any]:
    """Parse an inventory JSON object; raise InputError if it is not one."""
    try:
        inv = json.loads(text)
    except ValueError:
        raise InputError(EXIT_INPUT, "%s inventory is not JSON" % what)
    if not isinstance(inv, dict) or not inv:
        raise InputError(EXIT_INPUT, "%s inventory is empty or not a JSON object" % what)
    return inv


def as_items(values: Iterable[Any]) -> List[Any]:
    """Pairs become tuples so they can be counted; plain strings are kept."""
    return [tuple(v) if isinstance(v, list) else v for v in values or []]


def diff(source: List[Any], target: List[Any]) -> Tuple[List[Any], List[Any]]:
    """(missing from target, extra in target), as multisets."""
    s, t = Counter(source), Counter(target)
    return sorted((s - t).elements()), sorted((t - s).elements())


def compare(source: Dict[str, Any], target: Dict[str, Any], level: str,
            builtins: List[str]) -> Dict[str, Any]:
    """Per-dimension verdicts and a printable diff."""
    # secret_paths and values exist only at level values; a values-level source
    # compared at structure would otherwise always report every path missing.
    at_values = level == "values"
    pairs = {
        "engine_mounts": (source.get("engine_mounts"), target.get("engine_mounts")),
        "auth_mounts": (source.get("auth_mounts"), target.get("auth_mounts")),
        "audit_devices": (source.get("audit_devices"), target.get("audit_devices")),
        "secret_paths": ((source.get("secret_paths"), target.get("secret_paths"))
                         if at_values else ([], [])),
        "policies": (source.get("policies"),
                     [p for p in target.get("policies") or [] if p[0] not in builtins]),
        "values": ((source.get("value_hashes"), target.get("value_hashes"))
                   if at_values else ([], [])),
    }
    dims, report = {}, {}
    for dim in DIMENSIONS:
        missing, extra = diff(as_items(pairs[dim][0]), as_items(pairs[dim][1]))
        dims[dim] = not missing and not extra
        if dims[dim]:
            continue
        if dim in NAMED:
            # Policy pairs: report the name only, never the hash.
            name = (lambda x: x[0]) if dim == "policies" else (lambda x: x)
            report[dim] = {"missing": sorted({name(x) for x in missing}),
                           "extra": sorted({name(x) for x in extra})}
        else:
            report[dim] = {"missing": len(missing), "extra": len(extra)}
    return {"result": "PASS" if all(dims.values()) else "FAIL", "level": level,
            "dimensions": dims, "diff": report}


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("source", help="Phase 2 source-inventory.json")
    p.add_argument("--level", required=True, choices=("structure", "values"))
    p.add_argument("--builtin-policy", action="append", default=[],
                   help="OpenBao built-in policy ignored on the target (repeatable)")
    return p.parse_args(argv)


def main(argv: List[str], stdin=sys.stdin) -> int:
    """Entry point: print one JSON result line and return the exit code."""
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        try:
            with open(args.source) as f:
                source = load(f.read(), "source")
        except OSError as exc:
            raise InputError(EXIT_INPUT, "cannot read the source inventory %s: %s"
                             % (args.source, exc.strerror))
        source_level = source.get("verification_level", "structure")
        if args.level == "values" and source_level != "values":
            raise InputError(EXIT_LEVEL, "verification_level=values requested but the "
                             "source was gathered at '%s'; Phase 2 needs "
                             "-e verification_level=values while Vault is up"
                             % source_level)
        target = load(stdin.read(), "target")
    except InputError as exc:
        err(str(exc))
        print(json.dumps({"result": "FAIL", "error": str(exc)}))
        return exc.code
    result = compare(source, target, args.level, args.builtin_policy)
    err("%s at level=%s: %s" % (result["result"], args.level,
                                ", ".join("%s=%s" % kv for kv in result["dimensions"].items())))
    print(json.dumps(result))
    return 0 if result["result"] == "PASS" else EXIT_MISMATCH


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
