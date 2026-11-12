#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Clone the Vault data PV and make the clone the OpenBao data PVC.
rebind clones (or adopts) the PV and binds it straight to the destination PVC,
then hands it to OpenBao (reclaim Delete, relabelled). Original Vault
PVs are refused. Namespaces/names default from $VAULT_NAMESPACE, $VAULT_STS,
$BAO_NAMESPACE, $CLONE_PVC. stdout: one JSON line. Exit: 0 ok / 2 usage / 3 refused / 4 read / 5 mutate."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

CLONE_PV_LABEL = "app=vault-migration,role=source-data-clone-pv"
DATA_PV_ROLE_LABEL = "vault-migration/role"
DATA_PV_ROLE = "openbao-data"

DEFAULT_TIMEOUT = 300
SOURCE_PVC_ANNOTATION = "vault-migration/source-pvc"
# Per kubectl call; a call carrying its own --timeout=Ns gets N plus this margin instead.
KUBECTL_TIMEOUT = 60
TIMEOUT_MARGIN = 30
RC_TIMEOUT = 124
EXIT_REFUSED = 3
EXIT_READ = 4
EXIT_MUTATE = 5

# (args, stdin) -> (rc, stdout, stderr). Injectable so tests need no cluster.
Kube = Callable[[List[str], Optional[str]], Tuple[int, str, str]]
Sleep = Callable[[float], None]


class StepError(Exception):
    """A step failed; carries the process exit code."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def run_kubectl(args: List[str], stdin: Optional[str] = None) -> Tuple[int, str, str]:
    """Run kubectl with args (no shell); return (rc, stdout, stderr).
    A call that outlives its limit is killed and reported as rc 124."""
    limit = KUBECTL_TIMEOUT
    for arg in args:
        if arg.startswith("--timeout=") and arg[10:-1].isdigit() and arg.endswith("s"):
            limit = max(limit, int(arg[10:-1]) + TIMEOUT_MARGIN)
    try:
        proc = subprocess.run(["kubectl"] + args, input=stdin, capture_output=True,
                              text=True, check=False, timeout=limit)
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, "", "kubectl %s timed out after %ds" % (" ".join(args[:3]), limit)
    return proc.returncode, proc.stdout, proc.stderr


def err(msg: str) -> None:
    """Write a one-line diagnostic to stderr."""
    print("[clone-pv] %s" % msg, file=sys.stderr)


def get_json(kube: Kube, args: List[str]) -> Dict[str, Any]:
    """kubectl get ... -o json; a read failure is fatal (fail closed)."""
    rc, out, stderr = kube(["get"] + args + ["-o", "json"], None)
    if rc != 0:
        raise StepError(EXIT_READ, "kubectl get %s failed: %s"
                        % (" ".join(args), stderr.strip()))
    return json.loads(out)


def get_optional(kube: Kube, args: List[str]) -> Optional[Dict[str, Any]]:
    """kubectl get one object; None when NotFound, fatal on any other error."""
    rc, out, stderr = kube(["get"] + args + ["-o", "json"], None)
    if rc == 0:
        return json.loads(out)
    if "NotFound" in stderr:
        return None
    raise StepError(EXIT_READ, "kubectl get %s failed: %s"
                    % (" ".join(args), stderr.strip()))


def mutate(kube: Kube, args: List[str], stdin: Optional[str] = None) -> None:
    """Run a mutating kubectl call; raise StepError(EXIT_MUTATE) on failure."""
    rc, _, stderr = kube(args, stdin)
    if rc != 0:
        raise StepError(EXIT_MUTATE, "kubectl %s failed: %s"
                        % (" ".join(args[:3]), stderr.strip()))


def claim_ref(pv: Dict[str, Any]) -> Tuple[str, str]:
    """Return the PV's claimRef (namespace, name), or ("", "") when unclaimed."""
    ref = pv.get("spec", {}).get("claimRef") or {}
    return ref.get("namespace", ""), ref.get("name", "")


def phase(obj: Optional[Dict[str, Any]]) -> str:
    """status.phase of a PV/PVC object ('' when absent)."""
    return ((obj or {}).get("status") or {}).get("phase", "")


def protected_pvs(pvs: List[Dict[str, Any]], vault_pvcs: List[Dict[str, Any]],
                  vault_ns: str, vault_sts: str) -> List[str]:
    """Names of original Vault PVs: never patched or deleted."""
    pat = re.compile(r"^(data|audit)-%s-[0-9]+$" % re.escape(vault_sts))
    names = {p.get("spec", {}).get("volumeName") for p in vault_pvcs
             if pat.match(p.get("metadata", {}).get("name", ""))}
    for pv in pvs:
        ns, name = claim_ref(pv)
        if ns == vault_ns and pat.match(name):
            names.add(pv["metadata"]["name"])
    names.discard(None)
    names.discard("")
    return sorted(names)


def guard(kube: Kube, args: argparse.Namespace, pv_name: str) -> None:
    """Refuse pv_name if it is an original Vault PV; re-reads the cluster."""
    pvs = get_json(kube, ["pv"]).get("items", [])
    vault_pvcs = get_json(kube, ["pvc", "-n", args.vault_ns]).get("items", [])
    originals = protected_pvs(pvs, vault_pvcs, args.vault_ns, args.vault_sts)
    if pv_name in originals:
        raise StepError(EXIT_REFUSED,
                        "refusing to touch %s: it is an original Vault PV "
                        "(originals: %s)" % (pv_name, ", ".join(originals)))


def wait_for(check: Callable[[], bool], timeout: int, interval: int,
             sleep: Sleep) -> bool:
    """Poll check() every interval seconds; return False after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if check():
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(interval)


def wait_phase(kube: Kube, args: argparse.Namespace, sleep: Sleep, target: List[str],
               want: str) -> None:
    """Wait until the object at target reaches status.phase want."""
    if not wait_for(lambda: phase(get_optional(kube, target)) == want,
                    args.timeout, args.interval, sleep):
        raise StepError(EXIT_MUTATE, "%s did not reach %s within %ds"
                        % (" ".join(target), want, args.timeout))


def pvc_manifest(name: str, ns: str, role: str, size: str, sc: str,
                 extra_spec: Dict[str, Any],
                 labels: Optional[Dict[str, str]] = None,
                 annotations: Optional[Dict[str, str]] = None) -> str:
    """Return a ReadWriteOnce PVC manifest (JSON).

    Without labels the PVC is a migration-labelled one (app/role); with labels
    they are used verbatim.
    """
    spec = {"accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": size}},
            "storageClassName": sc}
    spec.update(extra_spec)
    meta: Dict[str, Any] = {
        "name": name, "namespace": ns,
        "labels": labels if labels is not None
        else {"app": "vault-migration", "role": role}}
    if annotations:
        meta["annotations"] = annotations
    return json.dumps({"apiVersion": "v1", "kind": "PersistentVolumeClaim",
                       "metadata": meta, "spec": spec})


def patch_pv(kube: Kube, pv_name: str, spec: Dict[str, Any]) -> None:
    """Merge-patch a PV's spec."""
    mutate(kube, ["patch", "pv", pv_name, "--type", "merge", "-p",
                  json.dumps({"spec": spec}, separators=(",", ":"))])


# --- rebind -----------------------------------------------------------------

def find_orphan(kube: Kube, source_pvc: str) -> Optional[Dict[str, Any]]:
    """The Retained, labelled clone PV of source_pvc left Available/Released by an earlier run.
    A candidate stamped with another source, or with none, stops the step."""
    mine, foreign = None, []
    for pv in get_json(kube, ["pv", "-l", CLONE_PV_LABEL]).get("items", []):
        if not (phase(pv) in ("Available", "Released")
                and pv["spec"].get("persistentVolumeReclaimPolicy") == "Retain"):
            continue
        stamp = (pv["metadata"].get("annotations") or {}).get(SOURCE_PVC_ANNOTATION)
        if stamp == source_pvc:
            mine = mine or pv
        else:
            foreign.append("%s (%s)" % (pv["metadata"]["name"], stamp or "no source stamp"))
    if foreign:
        raise StepError(EXIT_REFUSED,
                        "clone PV(s) not made from %s: %s; inspect and delete them, "
                        "then re-run" % (source_pvc, ", ".join(foreign)))
    return mine


def clone_and_release(kube: Kube, args: argparse.Namespace,
                      sleep: Sleep) -> Tuple[str, str, str]:
    """Clone the source PVC, Retain and release its PV; return (pv, size, sc)."""
    src = get_optional(kube, ["pvc", args.source_pvc, "-n", args.vault_ns])
    if src is None:
        raise StepError(EXIT_READ, "source Vault PVC %s/%s not found; it is the "
                        "clone source" % (args.vault_ns, args.source_pvc))
    # ceph-csi rejects a clone smaller than its source, so size and SC come
    # from the source.
    src_spec = src.get("spec", {})
    size = (src_spec.get("resources", {}).get("requests", {}).get("storage")
            or args.fallback_size)
    sc = src_spec.get("storageClassName") or args.fallback_sc
    mutate(kube, ["apply", "-f", "-"], pvc_manifest(
        args.clone_pvc, args.vault_ns, "source-data-clone", size, sc,
        {"dataSource": {"kind": "PersistentVolumeClaim", "name": args.source_pvc}}))
    target = ["pvc", args.clone_pvc, "-n", args.vault_ns]
    wait_phase(kube, args, sleep, target, "Bound")
    clone = get_optional(kube, target) or {}
    pv_name = (clone.get("spec") or {}).get("volumeName") or ""
    if not pv_name:
        raise StepError(EXIT_MUTATE, "clone PVC %s/%s is Bound but has no volumeName"
                        % (args.vault_ns, args.clone_pvc))
    # The destination must request the clone PV's own SC or the bind is rejected.
    sc = (clone.get("spec") or {}).get("storageClassName") or sc
    guard(kube, args, pv_name)
    # Stamp before labelling: a labelled clone PV always names its source.
    mutate(kube, ["annotate", "pv", pv_name, "--overwrite",
                  "%s=%s" % (SOURCE_PVC_ANNOTATION, args.source_pvc)])
    mutate(kube, ["label", "pv", pv_name, "--overwrite",
                  "app=vault-migration", "role=source-data-clone-pv"])
    # Retain before the claim goes, or ceph-csi deletes the clone image.
    patch_pv(kube, pv_name, {"persistentVolumeReclaimPolicy": "Retain"})
    mutate(kube, ["delete", "pvc", args.clone_pvc, "-n", args.vault_ns,
                  "--ignore-not-found=true", "--wait=true", "--timeout=%ds" % args.timeout])
    return pv_name, size, sc


def parse_kv(items: List[str]) -> Dict[str, str]:
    """Turn ['k=v', ...] into a dict; raise StepError on a malformed item."""
    out = {}
    for item in items or []:
        key, sep, val = item.partition("=")
        if not sep or not key:
            raise StepError(2, "expected key=value, got '%s'" % item)
        out[key] = val
    return out


def hand_over_to_openbao(kube: Kube, pv_name: str) -> None:
    """Make a bound clone PV an ordinary OpenBao data volume.

    Order matters: Delete only once Bound, relabel last, so an interrupt before
    the relabel still leaves a PV that a re-run recognises and finishes.
    """
    patch_pv(kube, pv_name, {"persistentVolumeReclaimPolicy": "Delete"})
    mutate(kube, ["label", "pv", pv_name, "--overwrite", "app-", "role-",
                  "%s=%s" % (DATA_PV_ROLE_LABEL, DATA_PV_ROLE)])


def rebind(kube: Kube, args: argparse.Namespace,
           sleep: Sleep = time.sleep) -> Dict[str, Any]:
    """Clone (or adopt) the clone PV and bind it as the destination PVC.

    Raises StepError on refusal, a failed read, or a failed or slow mutation.
    """
    annotations = parse_kv(args.dest_annotation)
    labels = parse_kv(args.dest_label)
    dest_target = ["pvc", args.dest_pvc, "-n", args.openbao_ns]
    dest = get_optional(kube, dest_target)
    if dest is not None:
        have = (dest.get("metadata", {}).get("annotations") or {})
        if any(have.get(k) != v for k, v in annotations.items()):
            raise StepError(EXIT_REFUSED,
                            "PVC %s/%s exists but is not a migration clone "
                            "(annotation missing); not ours to rebind"
                            % (args.openbao_ns, args.dest_pvc))
        pv_name = (dest.get("spec") or {}).get("volumeName") or ""
        if phase(dest) != "Bound":
            wait_phase(kube, args, sleep, dest_target, "Bound")
            pv_name = (get_optional(kube, dest_target) or {}).get(
                "spec", {}).get("volumeName", "")
        pv_obj = get_optional(kube, ["pv", pv_name]) if pv_name else None
        if pv_obj is not None:
            guard(kube, args, pv_name)
            if (pv_obj.get("metadata", {}).get("labels") or {}).get("role") \
                    == "source-data-clone-pv":
                hand_over_to_openbao(kube, pv_name)
        return {"result": "PASS", "clone_pv": pv_name, "adopted": False,
                "already_bound": True}
    orphan = find_orphan(kube, args.source_pvc)
    if orphan is not None:
        pv_name = orphan["metadata"]["name"]
        size = orphan["spec"].get("capacity", {}).get("storage") or args.fallback_size
        sc = orphan["spec"].get("storageClassName") or args.fallback_sc
        guard(kube, args, pv_name)
    else:
        pv_name, size, sc = clone_and_release(kube, args, sleep)
    # A Released PV keeps its claimRef and will not bind a new claim until cleared.
    patch_pv(kube, pv_name, {"claimRef": None})
    wait_phase(kube, args, sleep, ["pv", pv_name], "Available")
    mutate(kube, ["apply", "-f", "-"], pvc_manifest(
        args.dest_pvc, args.openbao_ns, "", size, sc,
        {"volumeName": pv_name}, labels=labels, annotations=annotations))
    wait_phase(kube, args, sleep, dest_target, "Bound")
    hand_over_to_openbao(kube, pv_name)
    return {"result": "PASS", "clone_pv": pv_name, "adopted": orphan is not None,
            "already_bound": False, "size": size, "storage_class": sc}


# --- CLI --------------------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse the command line."""
    common = argparse.ArgumentParser(add_help=False)
    for flag, var in (("vault-ns", "VAULT_NAMESPACE"), ("vault-sts", "VAULT_STS"),
                      ("openbao-ns", "BAO_NAMESPACE"), ("clone-pvc", "CLONE_PVC")):
        common.add_argument("--" + flag, default=os.environ.get(var),
                            help="default: $" + var)
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="seconds for each bind/phase/delete wait")
    common.add_argument("--interval", type=int, default=5)
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    rb = sub.add_parser("rebind", parents=[common])
    rb.add_argument("--source-pvc", required=True)
    rb.add_argument("--dest-pvc", required=True,
                    help="OpenBao data PVC the clone PV is bound to")
    rb.add_argument("--dest-label", action="append", default=[],
                    help="key=value label for the destination PVC (repeatable)")
    rb.add_argument("--dest-annotation", action="append", default=[],
                    help="key=value annotation marking the PVC as a clone "
                    "(repeatable; checked on resume)")
    rb.add_argument("--fallback-size", required=True,
                    help="clone size when the source PVC does not state one")
    rb.add_argument("--fallback-sc", required=True,
                    help="storage class when the source/clone does not state one")
    args = p.parse_args(argv)
    missing = [f for f in ("vault_ns", "vault_sts", "openbao_ns", "clone_pvc")
               if not getattr(args, f)]
    if missing:
        p.error("missing (flag or env): " + ", ".join(missing))
    return args


def main(argv: List[str], kube: Kube = run_kubectl, sleep: Sleep = time.sleep) -> int:
    """Entry point: print one JSON result line and return the exit code."""
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        action = {"rebind": rebind}
        result = action[args.action](kube, args, sleep)
    except StepError as exc:
        err(str(exc))
        print(json.dumps({"result": "FAIL", "error": str(exc)}))
        return exc.code
    except ValueError as exc:
        err("unparseable kubectl output: %s" % exc)
        print(json.dumps({"result": "FAIL", "error": "unparseable kubectl output"}))
        return EXIT_READ
    err("%s: clone PV '%s' %s" % (args.action, result["clone_pv"],
                                  {k: v for k, v in result.items()
                                   if k not in ("result", "clone_pv")}))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
