#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Verify the Vault unseal shard-secret set in a namespace. The StarlingX vault
# application uses the prefix "cluster-key": the set is <prefix>-0..4 plus
# <prefix>-root, every member holding non-empty .data. The prefix defaults to
# "cluster-key" and can be overridden as the second argument. If the set is not
# complete, migration should not continue. Prints the prefix on success; exits
# non-zero otherwise.

set -euo pipefail

NAMESPACE="${1:?namespace required}"
PREFIX="${2:-cluster-key}"
SHARES=5

names="$(kubectl get secrets -n "$NAMESPACE" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"

# Every shard (0..4) and the root secret must be present.
for member in $(seq 0 $((SHARES - 1))) root; do
    printf '%s\n' "$names" | grep -qx "${PREFIX}-${member}" || {
        echo "incomplete unseal shard-secret set: missing ${PREFIX}-${member} in namespace $NAMESPACE" >&2
        exit 1
    }
done

# Every member must have non-empty .data.
for member in $(seq 0 $((SHARES - 1))) root; do
    data="$(kubectl get secret "${PREFIX}-${member}" -n "$NAMESPACE" \
        -o jsonpath='{.data}' 2>/dev/null || true)"
    case "$data" in
        ""|"{}")
            echo "unseal shard-secret ${PREFIX}-${member} has empty .data in namespace $NAMESPACE" >&2
            exit 1
            ;;
    esac
done

echo "$PREFIX"
