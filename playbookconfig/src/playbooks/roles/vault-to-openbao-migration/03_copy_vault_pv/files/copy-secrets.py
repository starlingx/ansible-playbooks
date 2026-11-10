#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Copy the legacy unseal secrets from the vault to the openbao namespace.
Missing secrets are created with `kubectl create` (apply would embed the data in an
annotation) from a template of name/namespace/type/.data; existing ones must hold the
same data as the source. Data only passes between kubectl and this process. Exit: 0 / 2 usage / 4 read / 5 create / 6 verify."""
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

EXIT_READ = 4
EXIT_CREATE = 5
EXIT_VERIFY = 6
KUBECTL_TIMEOUT = 60
RC_TIMEOUT = 124

# (args, stdin) -> (rc, stdout, stderr). Injectable so tests need no cluster.
Kube = Callable[[List[str], Optional[str]], Tuple[int, str, str]]


class StepError(Exception):
    """A step failed; carries the process exit code."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def run_kubectl(args: List[str], stdin: Optional[str] = None) -> Tuple[int, str, str]:
    """Run kubectl with args (no shell); return (rc, stdout, stderr).
    A call that exceeds KUBECTL_TIMEOUT returns RC_TIMEOUT.
    """
    try:
        proc = subprocess.run(["kubectl"] + args, input=stdin, capture_output=True,
                              text=True, check=False, timeout=KUBECTL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, "", "kubectl %s timed out after %ds" % (
            " ".join(args[:2]), KUBECTL_TIMEOUT)
    return proc.returncode, proc.stdout, proc.stderr


def err(msg: str) -> None:
    """Write a one-line diagnostic to stderr."""
    print("[copy-secrets] %s" % msg, file=sys.stderr)


def first_line(text: str) -> str:
    """First non-empty line, truncated (kubectl errors name the object, not its data)."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def get_secrets(kube: Kube, ns: str, names: List[str],
                ignore_missing: bool) -> Dict[str, Dict[str, Any]]:
    """Read the named secrets in one call; return {name: secret}."""
    args = ["get", "secret"] + names + ["-n", ns, "-o", "json"]
    if ignore_missing:
        args.append("--ignore-not-found")
    rc, out, stderr = kube(args, None)
    if rc != 0:
        raise StepError(EXIT_READ, "reading secrets in %s failed: %s"
                        % (ns, first_line(stderr)))
    if not out.strip():
        return {}
    doc = json.loads(out)
    # One name yields the object itself; several yield a List.
    items = doc.get("items", []) if doc.get("kind") == "List" else [doc]
    return {s["metadata"]["name"]: s for s in items}


def portable(secret: Dict[str, Any], dst_ns: str) -> Dict[str, Any]:
    """A new Secret for dst_ns carrying only the name, type and base64 data."""
    return {"apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": secret["metadata"]["name"], "namespace": dst_ns},
            "type": secret.get("type", "Opaque"), "data": secret.get("data") or {}}


def same_data(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when both secrets hold the same base64 data."""
    return (a.get("data") or {}) == (b.get("data") or {})


def copy(kube: Kube, args: argparse.Namespace) -> Dict[str, Any]:
    """Copy the missing secrets and verify all; return the result dict.
    Raises StepError on a read/create failure, or a destination secret that is missing,
    empty or different from the source.
    """
    source = get_secrets(kube, args.src_ns, args.names, ignore_missing=False)
    missing_src = [n for n in args.names if n not in source]
    if missing_src:
        raise StepError(EXIT_READ, "source secret(s) not found in %s: %s"
                        % (args.src_ns, ", ".join(missing_src)))
    present = get_secrets(kube, args.dst_ns, args.names, ignore_missing=True)
    differ = [n for n in present if not same_data(present[n], source[n])]
    if differ:
        raise StepError(EXIT_VERIFY, "secret(s) in %s differ from the source in %s: %s; "
                        "delete them from %s"
                        % (args.dst_ns, args.src_ns, ", ".join(differ), args.dst_ns))
    copied = []
    for name in args.names:
        if name in present:
            continue
        rc, _, stderr = kube(["create", "-n", args.dst_ns, "-f", "-"],
                             json.dumps(portable(source[name], args.dst_ns)))
        # AlreadyExists: a concurrent or interrupted run created it first.
        if rc != 0 and "AlreadyExists" not in stderr:
            raise StepError(EXIT_CREATE, "creating %s in %s failed: %s"
                            % (name, args.dst_ns, first_line(stderr)))
        copied.append(name)
    after = get_secrets(kube, args.dst_ns, args.names, ignore_missing=True)
    bad = [n for n in args.names if not (after.get(n) or {}).get("data")]
    if bad:
        raise StepError(EXIT_VERIFY, "missing or empty in %s after the copy: %s"
                        % (args.dst_ns, ", ".join(bad)))
    differ = [n for n in args.names if not same_data(after[n], source[n])]
    if differ:
        raise StepError(EXIT_VERIFY, "differ from the source after the copy in %s: %s"
                        % (args.dst_ns, ", ".join(differ)))
    return {"result": "PASS", "copied": copied,
            "already_present": [n for n in args.names if n in present]}


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src-ns", default=os.environ.get("VAULT_NAMESPACE"),
                   help="default: $VAULT_NAMESPACE")
    p.add_argument("--dst-ns", default=os.environ.get("BAO_NAMESPACE"),
                   help="default: $BAO_NAMESPACE")
    p.add_argument("names", nargs="+", help="secret names")
    args = p.parse_args(argv)
    if not (args.src_ns and args.dst_ns):
        p.error("--src-ns/--dst-ns or $VAULT_NAMESPACE/$BAO_NAMESPACE required")
    return args


def main(argv: List[str], kube: Kube = run_kubectl) -> int:
    """Entry point: print one JSON result line and return the exit code."""
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        result = copy(kube, args)
    except StepError as exc:
        err(str(exc))
        print(json.dumps({"result": "FAIL", "error": str(exc)}))
        return exc.code
    except (ValueError, KeyError, AttributeError):
        # Never echo the parse error: it could quote secret material.
        err("unparseable kubectl output")
        print(json.dumps({"result": "FAIL", "error": "unparseable kubectl output"}))
        return EXIT_READ
    err("copied %d, already present %d, all %d verified in %s"
        % (len(result["copied"]), len(result["already_present"]), len(args.names),
           args.dst_ns))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
