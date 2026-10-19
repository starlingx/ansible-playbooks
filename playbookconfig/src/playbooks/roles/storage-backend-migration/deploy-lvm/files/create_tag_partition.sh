#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Idempotently create ONE LVM-PV partition on a disk and tag it in the sysinv DB
# with flat migration_* capability keys, so a re-run knows exactly which
# partitions this migration created and never duplicates a slot.
#
# A "slot" is identified by (device, index, size_gib) — the position of the
# partition within its disk's plan. Per invocation (one slot):
#   1. If a partition on this disk is already tagged with this (device, index,
#      size_gib) -> it was created on a previous run; do nothing.
#   2. Else, if there is an UNTAGGED partition of this size on this disk (an
#      orphan from a previous run that died between the add and the tag; the
#      pre-check guarantees the disk had no partitions, so any untagged one of
#      the right size is ours) -> adopt it: tag it with this slot.
#   3. Else -> create the partition, then tag the newest matching untagged one.
# The add and the tag are issued back to back; the orphan branch closes the
# add/tag crash window on re-run.
#
# Required environment variables:
#   MIGRATION_HOST       - hostname (inventory_hostname)
#   MIGRATION_DEVICE     - disk device_path
#   MIGRATION_SIZE_GIB   - requested partition size in GiB (integer)
#   MIGRATION_INDEX      - 0-based per-disk partition index (user/canonical order)
#
# Prints "slot already present" on stdout when nothing was created (case 1), so
# the caller can report changed=false.

set -euo pipefail

: "${MIGRATION_HOST:?MIGRATION_HOST is required}"
: "${MIGRATION_DEVICE:?MIGRATION_DEVICE is required}"
: "${MIGRATION_SIZE_GIB:?MIGRATION_SIZE_GIB is required}"
: "${MIGRATION_INDEX:?MIGRATION_INDEX is required}"

SIZE_MIB=$(( MIGRATION_SIZE_GIB * 1024 ))


MARK=$(printf '{"migration_action": "create", "migration_size_gib": "%s", "migration_device": "%s", "migration_index": "%s"}' \
    "$MIGRATION_SIZE_GIB" "$MIGRATION_DEVICE" "$MIGRATION_INDEX")

psql_sysinv() {
    sudo -u postgres psql -d sysinv -t -A -c "$1"
}

# 1. Slot already created and tagged on a previous run -> nothing to do.
SQL_SEL_SLOT="SELECT COUNT(*) FROM partition p \
    JOIN i_idisk d ON p.idisk_id = d.id \
    JOIN i_host h ON p.forihostid = h.id \
    WHERE h.hostname = '${MIGRATION_HOST}' AND d.device_path = '${MIGRATION_DEVICE}' \
    AND p.capabilities::jsonb->>'migration_device' = '${MIGRATION_DEVICE}' \
    AND p.capabilities::jsonb->>'migration_index' = '${MIGRATION_INDEX}' \
    AND p.capabilities::jsonb->>'migration_size_gib' = '${MIGRATION_SIZE_GIB}'"
SLOT_COUNT=$(psql_sysinv "$SQL_SEL_SLOT")
if [ "$SLOT_COUNT" -ge 1 ]; then
    echo "slot already present"
    exit 0
fi

# Orphan = untagged partition of the right size on this disk (ours by the
# clean-disk pre-check). Ordered by id ASC (creation order == user order).
SQL_ORPHAN="SELECT p.uuid FROM partition p \
    JOIN i_idisk d ON p.idisk_id = d.id \
    JOIN i_host h ON p.forihostid = h.id \
    WHERE h.hostname = '${MIGRATION_HOST}' AND d.device_path = '${MIGRATION_DEVICE}' \
    AND p.size_mib = ${SIZE_MIB} \
    AND (p.capabilities IS NULL OR p.capabilities::jsonb->>'migration_device' IS NULL) \
    ORDER BY p.id ASC LIMIT 1"
ORPHAN_UUID=$(psql_sysinv "$SQL_ORPHAN")

# 3. No orphan to adopt -> create the partition now, then re-read it.
if [ -z "$ORPHAN_UUID" ]; then
    system host-disk-partition-add "$MIGRATION_HOST" "$MIGRATION_DEVICE" "$MIGRATION_SIZE_GIB"
    ORPHAN_UUID=$(psql_sysinv "$SQL_ORPHAN")
fi

# 2/3. Tag the adopted or just-created partition with this slot's marker.
if [ -z "$ORPHAN_UUID" ]; then
    echo "ERROR: no partition to tag on ${MIGRATION_DEVICE} for index ${MIGRATION_INDEX}" >&2
    exit 1
fi

SQL_TAG="UPDATE partition \
    SET capabilities = (COALESCE(capabilities, '{}')::jsonb || '${MARK}'::jsonb)::text \
    WHERE uuid = '${ORPHAN_UUID}'"
sudo -u postgres psql -d sysinv -c "$SQL_TAG"

# A later add on the same disk is rejected while any partition is still
# 'Creating', so wait for this one to reach 'Ready' (status 0); fail otherwise.
READY=""
for _ in $(seq 1 60); do
    READY=$(psql_sysinv "SELECT status FROM partition WHERE uuid = '${ORPHAN_UUID}'")
    [ "$READY" = "0" ] && break
    sleep 10
done
if [ "$READY" != "0" ]; then
    echo "ERROR: partition ${ORPHAN_UUID} on ${MIGRATION_DEVICE} did not reach Ready (status=${READY})" >&2
    exit 1
fi
