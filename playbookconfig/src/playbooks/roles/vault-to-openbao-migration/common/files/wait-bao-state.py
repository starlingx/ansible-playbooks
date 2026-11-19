#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Wait for an OpenBao pod to reach a state (reachable, initialized, unsealed, active) per `bao status`.
Polls `kubectl exec ... bao status -format=json` every 5 s until --timeout (--probe = check
once); `active` uses is_self (OpenBao 2.2 has no ha_mode). `--pod auto` polls every server pod of
--statefulset (default $BAO_STATEFULSET) until one satisfies the state, so the active pod need
not be ordinal 0. stdout: one JSON line {result, state, pod}; stderr: the diagnostic, and on an
`active` timeout the cause from the server log. Exit: 0 reached / 2 usage / 6 timeout.
Namespace and pod default to $BAO_NAMESPACE / $BAO_POD."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
EXIT_TIMEOUT = 6
INTERVAL = 5
# Per kubectl call; a bao status takes about a second, so this only cuts a hang.
CMD_TIMEOUT = 15
RC_TIMEOUT = 124
AUTO = "auto"
LOG_REASONS = re.compile(r"failed to setup audit table|post-unseal setup failed|"
                         r"failed to create audit entry")
# (argv) -> (rc, stdout, stderr). Injectable so tests need no cluster.
Run = Callable[[List[str]], Tuple[int, str, str]]


def run_cmd(argv: List[str]) -> Tuple[int, str, str]:
    """Run argv (no shell); return (rc, stdout, stderr). A call that hangs is killed (rc 124)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False,
                              timeout=CMD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, "", "%s timed out after %ds" % (" ".join(argv[:3]), CMD_TIMEOUT)
    return proc.returncode, proc.stdout, proc.stderr


def err(msg: str) -> None:
    """Write a one-line diagnostic to stderr."""
    print("[wait-bao-state] %s" % msg, file=sys.stderr)


def first_line(text: str) -> str:
    """First non-empty line of text, truncated."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def parse_status(out: str) -> Optional[Dict[str, Any]]:
    """The status JSON object, or None when out is not one."""
    try:
        status = json.loads(out)
    except ValueError:
        return None
    return status if isinstance(status, dict) else None


def holds(state: str, s: Optional[Dict[str, Any]]) -> bool:
    """Whether status s satisfies state."""
    if s is None:
        return False
    if state == "reachable":
        return True
    if state == "initialized":
        return s.get("initialized") is True
    unsealed = s.get("sealed") is False
    if state == "unsealed":
        return unsealed
    return (unsealed
            and (str(s.get("ha_mode") or "").lower() == "active" or s.get("is_self") is True)
            and str(s.get("leader_address") or "").strip() != "")


def candidates(run: Run, args: argparse.Namespace) -> List[str]:
    """Pods to query: the named pod, or every server pod of the StatefulSet for auto."""
    if args.pod != AUTO:
        return [args.pod]
    rc, out, _ = run(["kubectl", "get", "pods", "-n", args.namespace,
                      "-l", "app.kubernetes.io/instance=%s,component=server" % args.statefulset,
                      "-o", "jsonpath={.items[*].metadata.name}"])
    return sorted(out.split()) if rc == 0 else []


def log_reason(run: Run, args: argparse.Namespace, pods: List[str]) -> str:
    """Known post-unseal setup failure lines from the server logs ('' if none)."""
    reasons = []
    for pod in pods:
        rc, out, _ = run(["kubectl", "logs", pod, "-n", args.namespace,
                          "-c", args.container, "--tail=200"])
        found = " | ".join(line.strip() for line in out.splitlines()
                           if LOG_REASONS.search(line)) if rc == 0 else ""
        if found:
            reasons.append(("%s: %s" % (pod, found)) if len(pods) > 1 else found)
    return " | ".join(reasons)


def wait(run: Run, args: argparse.Namespace, clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], None] = time.sleep) -> Tuple[str, str]:
    """Poll until args.state holds on a pod or the timeout passes.
    Returns (pod that reached it or '', message)."""
    start = clock()
    while True:
        pods = candidates(run, args)
        status, stderr = None, ""
        for pod in pods:
            _, out, stderr = run(["kubectl", "exec", pod, "-n", args.namespace,
                                  "-c", args.container, "--", "bao", "status", "-format=json"])
            # bao status exits non-zero when sealed but still prints the JSON.
            status = parse_status(out)
            if holds(args.state, status):
                return pod, "%s is %s (%ds)" % (pod, args.state, clock() - start)
        if clock() - start >= args.timeout:
            break
        sleep(INTERVAL)
    s = status or {}
    msg = ("%s did not reach %s within %ds (last: initialized=%s sealed=%s is_self=%s "
           "leader_address=%r)" % (args.pod, args.state, args.timeout, s.get("initialized"),
                                   s.get("sealed"), s.get("is_self"),
                                   s.get("leader_address") or ""))
    if status is None and first_line(stderr):
        msg += "; kubectl: " + first_line(stderr)
    reason = log_reason(run, args, pods) if args.state == "active" else ""
    return "", msg + ("; server log: " + reason if reason else "")


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--namespace", default=os.environ.get("BAO_NAMESPACE"))
    p.add_argument("--pod", default=os.environ.get("BAO_POD"),
                   help="pod name, or 'auto' for any server pod of --statefulset")
    p.add_argument("--statefulset", default=os.environ.get("BAO_STATEFULSET"))
    p.add_argument("--container", default="openbao")
    p.add_argument("--state", required=True,
                   choices=("reachable", "initialized", "unsealed", "active"))
    p.add_argument("--timeout", type=int, default=300, help="seconds")
    p.add_argument("--probe", action="store_true", help="check once (timeout 0)")
    args = p.parse_args(argv)
    if not (args.namespace and args.pod):
        p.error("--namespace/--pod or $BAO_NAMESPACE/$BAO_POD required")
    if args.pod == AUTO and not args.statefulset:
        p.error("--pod auto needs --statefulset or $BAO_STATEFULSET")
    if args.probe:
        args.timeout = 0
    return args


def main(argv: List[str], run: Run = run_cmd, clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], None] = time.sleep) -> int:
    """Entry point: log the outcome, print the result line and return the exit code."""
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    pod, msg = wait(run, args, clock, sleep)
    err(msg)
    print(json.dumps({"result": "PASS" if pod else "FAIL", "state": args.state, "pod": pod}))
    return 0 if pod else EXIT_TIMEOUT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
