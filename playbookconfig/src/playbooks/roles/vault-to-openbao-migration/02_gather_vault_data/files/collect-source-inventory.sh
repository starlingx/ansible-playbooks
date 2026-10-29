#!/bin/sh
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Runs IN-POD. Reads the Vault root token from STDIN (never argv), performs the
# authenticated reads (secrets/auth/audit list, policy list + per-policy hash),
# the recursive KV path walk, and (when arg1 == "values") per-secret value
# hashing, then emits ONE inventory JSON on stdout. Diagnostics -> stderr only.
#   argv: <verification_level>   stdin: VAULT_TOKEN
#   verification_level (the caller gates level "none" out before reaching here,
#   so only these two are handled):
#     structure - (default) list mounts/auth/audit/policies only; the KV path
#                 walk is skipped so the secret path list is not emitted, and
#                 secret_paths and value_hashes stay empty arrays.
#     values    - structure plus the KV path walk and per-secret value hashing;
#                 secret_paths and value_hashes are populated.
#   stdout JSON keys: engine_mounts, auth_mounts, audit_devices, policies
#     ([name,sha256] pairs), secret_paths, value_hashes ([path,sha256] pairs | [])
set -eu

VERIFICATION_LEVEL="${1:-structure}"

case "$VERIFICATION_LEVEL" in
    structure|values) ;;
    *)
        echo "[collect-source-inventory] unknown verification_level:" \
             "$VERIFICATION_LEVEL (expected structure|values)" >&2
        exit 2
        ;;
esac

IFS= read -r VAULT_TOKEN || true
export VAULT_TOKEN

err() { echo "[collect-source-inventory] $*" >&2; }

# JSON-escape a string (backslash, double-quote).
json_escape() {
    s="$1"
    s=$(printf '%s' "$s" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
    printf '%s' "$s"
}

# Emit a JSON array of strings (one per input line, sorted, blanks dropped).
emit_str_array() {
    first=1
    printf '['
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        if [ "$first" -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '"%s"' "$(json_escape "$line")"
    done
    printf ']'
}

# List the mount/auth/audit paths from `vault <sub> list -format=json`. In that
# JSON the paths are the top-level object keys, printed at two-space indentation;
# nested config keys are indented deeper. The sed matches only lines with exactly
# two leading spaces, so it returns the paths and not any nested keys.
list_paths() {
    # $1 = vault subcommand words (e.g. "secrets list")
    # shellcheck disable=SC2086
    vault $1 -format=json 2>/dev/null \
        | sed -n 's/^  "\([^"]*\)":[[:space:]]*{.*/\1/p' \
        | sort -u
}

# Policy names: -format=json is a flat JSON array of name strings.
policy_names() {
    vault policy list -format=json 2>/dev/null \
        | sed -e 's/[][",]//g' -e '/^[[:space:]]*$/d' \
        | awk '{$1=$1}; $1 != "" {print $1}' \
        | sort -u
}

# Recursive KV v2 walk under secret/. Emits "secret/<path>" per leaf. `local`
# (busybox/dash ash and bash support it) keeps each recursion's keys isolated.
kv_walk() {
    local _p _keys _k
    _p="$1"
    _keys=$(vault kv list -format=json "secret/$_p" 2>/dev/null \
            | sed -e 's/[][",]//g' -e '/^[[:space:]]*$/d') || return 0
    for _k in $_keys; do
        case "$_k" in
            */) kv_walk "$_p$_k" ;;
            *)  echo "secret/$_p$_k" ;;
        esac
    done
}

# ---- gather ----------------------------------------------------------------
engine_mounts=$(list_paths "secrets list")
auth_mounts=$(list_paths "auth list")
audit_devices=$(list_paths "audit list")
policies=$(policy_names)

# The KV path walk feeds only the value-hashing loop, which runs at level
# "values" alone. At "structure" it is skipped so the (sensitive) secret path
# list is never walked or emitted; secret_paths stays empty.
secret_paths=""
if [ "$VERIFICATION_LEVEL" = "values" ]; then
    secret_paths=$(kv_walk "" | sort)
fi

# ---- emit JSON -------------------------------------------------------------
printf '{\n'

printf '  "engine_mounts": '
printf '%s\n' "$engine_mounts" | emit_str_array
printf ',\n'

printf '  "auth_mounts": '
printf '%s\n' "$auth_mounts" | emit_str_array
printf ',\n'

printf '  "audit_devices": '
printf '%s\n' "$audit_devices" | emit_str_array
printf ',\n'

# policies: [name, sha256] pairs, sorted by name. The policy body is hashed
# in-pod and never leaves the pod as plaintext.
printf '  "policies": ['
first=1
if [ -n "$policies" ]; then
    printf '%s\n' "$policies" | while IFS= read -r name; do
        [ -n "$name" ] || continue
        h=$(vault policy read "$name" 2>/dev/null | sha256sum | awk '{print $1}')
        if [ "$first" -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '["%s","%s"]' "$(json_escape "$name")" "$h"
    done
fi
printf '],\n'

# secret_paths: populated only at level "values" (the walk is skipped at
# "structure"), so an empty array at "structure".
printf '  "secret_paths": '
printf '%s\n' "$secret_paths" | emit_str_array
printf ',\n'

# value_hashes: [path, sha256] pairs only when verification_level == values;
# the .data payload is hashed in-pod so plaintext never leaves.
printf '  "value_hashes": ['
first=1
if [ "$VERIFICATION_LEVEL" = "values" ] && [ -n "$secret_paths" ]; then
    printf '%s\n' "$secret_paths" | while IFS= read -r path; do
        [ -n "$path" ] || continue
        # Hash only the KV v2 .data.data value map. vault kv get -format=json
        # is pretty-printed multi-line, so collapse whitespace first (tr) before
        # the single-line sed match; a line-oriented sed on the raw output
        # matches nothing and every secret would hash to sha256("") — making the
        # "values" equivalence check pass even when values differ. Dropping
        # .data.metadata keeps the hash stable across re-reads (version,
        # timestamps vary). Note: a value containing the literal },"metadata"
        # could skew the greedy capture, but the extraction is deterministic and
        # identical on both source and destination, so the comparison still holds.
        h=$(vault kv get -format=json "$path" 2>/dev/null \
            | tr -d ' \n\t' \
            | sed -n 's/.*"data":{\(.*\)},"metadata".*/\1/p' \
            | sha256sum | awk '{print $1}')
        if [ "$first" -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '["%s","%s"]' "$(json_escape "$path")" "$h"
    done
fi
printf ']\n'

printf '}\n'

err "inventory collected (verification_level=$VERIFICATION_LEVEL)"
exit 0
