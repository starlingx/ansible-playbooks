#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Renames PVCs by creating the new PVC first, rebinding the PV,
# and only deleting the old PVC after the new one is confirmed Bound.
#
# Reads PVC list from stdin, one per line: "namespace from to"
#
# Environment variables:
#   KUBECONFIG - Path to kubeconfig
#
# State handling:
#
#   FROM exists | TO exists | Same PV | Action
#   ------------|-----------|---------|------------------------------------------
#   Yes         | No        | -       | Normal rename (full flow)
#   Yes         | Yes       | Yes     | Resume from step 4 (claimRef patch)
#   Yes         | Yes       | No      | Error: destination bound to different PV
#   No          | -         | -       | Rename already done; restore reclaim policy
#                                       from PV annotation if still present, then skip
#

import json
import logging
import sys

from kubernetes import client
from kubernetes import config
from kubernetes import watch
from kubernetes.client.rest import ApiException

RECLAIM_ANNOTATION = "rename-pvcs/original-reclaim-policy"

BOUND_TIMEOUT_SECONDS = 120

log = logging.getLogger(__name__)


def _read_pvc(v1, namespace, name):
    try:
        return v1.read_namespaced_persistent_volume_claim(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _read_pv(v1, name):
    try:
        return v1.read_persistent_volume(name)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _pvc_raw(v1, namespace, name):
    resp = v1.read_namespaced_persistent_volume_claim(
        name, namespace, _preload_content=False)
    return json.loads(resp.data)


def _reclaim_annotation(pv):
    if pv is None:
        return ""
    annotations = pv.metadata.annotations or {}
    return annotations.get(RECLAIM_ANNOTATION) or ""


def restore_reclaim_policy(v1, pv_name, policy):
    log.info("  Restoring reclaim policy of PV %s to %s", pv_name, policy)
    v1.patch_persistent_volume(
        pv_name, {"spec": {"persistentVolumeReclaimPolicy": policy}})
    log.info("  Removing reclaim policy annotation from PV %s", pv_name)
    v1.patch_persistent_volume(
        pv_name, {"metadata": {"annotations": {RECLAIM_ANNOTATION: None}}})


def prepare_rename(v1, namespace, from_, to):
    if from_ == to:
        log.info("ERROR: %s/%s: from and to are the same", namespace, from_)
        sys.exit(1)

    if _read_pvc(v1, namespace, from_) is None:
        to_pvc = _read_pvc(v1, namespace, to)
        pv_name = to_pvc.spec.volume_name if to_pvc is not None else ""
        if pv_name:
            original_reclaim_policy = _reclaim_annotation(_read_pv(v1, pv_name))
            if original_reclaim_policy:
                restore_reclaim_policy(v1, pv_name, original_reclaim_policy)
        log.info("WARNING: PVC %s/%s does not exist, skipping", namespace, from_)
        return None

    log.info("Renaming %s/%s -> %s", namespace, from_, to)

    from_pvc = _read_pvc(v1, namespace, from_)
    pv_name = from_pvc.spec.volume_name
    if not pv_name:
        log.info("ERROR: PVC %s/%s has no bound PV", namespace, from_)
        sys.exit(1)

    original_reclaim_policy = _reclaim_annotation(_read_pv(v1, pv_name))

    to_pvc = _read_pvc(v1, namespace, to)
    if to_pvc is not None:
        pv_dst = to_pvc.spec.volume_name

        if pv_name != pv_dst:
            log.info(
                "ERROR: PVC %s/%s already exists and is bound to a different PV "
                "(expected: %s, found: %s)", namespace, to, pv_name, pv_dst)
            sys.exit(1)

        log.info(
            "  PVC %s/%s already exists with same PV, resuming from claimRef "
            "update to new PVC", namespace, to)

    else:
        if not original_reclaim_policy:
            pv = _read_pv(v1, pv_name)
            original_reclaim_policy = pv.spec.persistent_volume_reclaim_policy

            log.info("  PV: %s, Reclaim: %s", pv_name, original_reclaim_policy)

            log.info("  Annotating PV %s with original reclaim policy %s",
                     pv_name, original_reclaim_policy)
            v1.patch_persistent_volume(
                pv_name,
                {"metadata": {"annotations": {
                    RECLAIM_ANNOTATION: original_reclaim_policy}}})

        log.info("  Setting PV %s reclaim policy to Retain (safety net)", pv_name)
        v1.patch_persistent_volume(
            pv_name, {"spec": {"persistentVolumeReclaimPolicy": "Retain"}})

        log.info("  Creating new PVC %s/%s as a copy of %s", namespace, to, from_)
        pvc = _pvc_raw(v1, namespace, from_)
        pvc["metadata"]["name"] = to
        for key in ("uid", "creationTimestamp", "resourceVersion"):
            pvc["metadata"].pop(key, None)
        pvc.pop("status", None)
        v1.create_namespaced_persistent_volume_claim(namespace, pvc)

    new_pvc_uid = v1.read_namespaced_persistent_volume_claim(
        to, namespace).metadata.uid

    log.info("  Updating PV %s claimRef to point to %s/%s", pv_name, namespace, to)
    v1.patch_persistent_volume(
        pv_name,
        {
            "spec": {
                "claimRef": {
                    "namespace": namespace,
                    "name": to,
                    "uid": new_pvc_uid,
                }
            }
        })

    return {
        "namespace": namespace,
        "from": from_,
        "to": to,
        "pv_name": pv_name,
        "new_pvc_uid": new_pvc_uid,
        "original_reclaim_policy": original_reclaim_policy,
    }


def _bound_to_expected(pvc, expected_uid, expected_pv):
    phase = getattr(getattr(pvc, "status", None), "phase", None)
    if phase != "Bound":
        return False
    metadata = getattr(pvc, "metadata", None)
    spec = getattr(pvc, "spec", None)
    if expected_uid and getattr(metadata, "uid", None) != expected_uid:
        return False
    if expected_pv and getattr(spec, "volume_name", None) != expected_pv:
        return False
    return True


def _remove_pvc_finalizers(v1, namespace, name):
    log.info("  Removing finalizers from PVC %s/%s", namespace, name)
    patch = [{"op": "remove", "path": "/metadata/finalizers"}]
    try:
        v1.patch_namespaced_persistent_volume_claim(name, namespace, patch)
    except ApiException as exc:
        if exc.status == 404:
            return
        raise


def _finalize_bound_record(v1, record):
    namespace = record["namespace"]
    from_ = record["from"]
    to = record["to"]
    pv_name = record["pv_name"]
    original_reclaim_policy = record["original_reclaim_policy"]

    log.info("  Deleting old PVC %s/%s", namespace, from_)
    v1.delete_namespaced_persistent_volume_claim(from_, namespace)
    _remove_pvc_finalizers(v1, namespace, from_)
    log.info('  PVC "%s" deleted from %s namespace', from_, namespace)

    if original_reclaim_policy:
        restore_reclaim_policy(v1, pv_name, original_reclaim_policy)

    log.info("Done: %s/%s -> %s (PV: %s)", namespace, from_, to, pv_name)


def finalize_records(v1, records):
    by_namespace = {}
    for record in records:
        by_namespace.setdefault(record["namespace"], []).append(record)

    for namespace, ns_records in by_namespace.items():
        pending = {}
        for record in ns_records:
            log.info("  Waiting for PVC %s/%s to become Bound",
                     namespace, record["to"])
            pvc = _read_pvc(v1, namespace, record["to"])
            if _bound_to_expected(pvc, record["new_pvc_uid"], record["pv_name"]):
                _finalize_bound_record(v1, record)
            else:
                pending[record["to"]] = record

        if pending:
            _drain_pending(v1, namespace, pending)


def _drain_pending(v1, namespace, pending):
    w = watch.Watch()
    try:
        for event in w.stream(
                v1.list_namespaced_persistent_volume_claim,
                namespace,
                timeout_seconds=BOUND_TIMEOUT_SECONDS):
            obj = event.get("object")
            name = getattr(getattr(obj, "metadata", None), "name", None)
            record = pending.get(name)
            if record is not None and _bound_to_expected(
                    obj, record["new_pvc_uid"], record["pv_name"]):
                _finalize_bound_record(v1, pending.pop(name))
                if not pending:
                    return
    finally:
        w.stop()

    for name in sorted(pending):
        log.info("ERROR: PVC %s/%s not Bound after timeout", namespace, name)
    sys.exit(1)


def main():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    config.load_kube_config()
    v1 = client.CoreV1Api()

    records = []
    for line in sys.stdin:
        parts = line.split(None, 2)
        if not parts:
            continue
        namespace = parts[0] if len(parts) > 0 else ""
        from_ = parts[1] if len(parts) > 1 else ""
        to = parts[2].rstrip() if len(parts) > 2 else ""
        if not namespace or not from_ or not to:
            log.info(
                "ERROR: Invalid input: namespace='%s' from='%s' to='%s' "
                "(all 3 fields required)", namespace, from_, to)
            sys.exit(1)
        record = prepare_rename(v1, namespace, from_, to)
        if record is not None:
            records.append(record)

    finalize_records(v1, records)


if __name__ == "__main__":
    main()
