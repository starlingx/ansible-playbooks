#!/bin/sh
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Runs IN-POD. Prints one inventory JSON (mounts, auth, audit, policies; at level
# "values" also secret paths and keyed value hashes) for the vault (Phase 2) or
# bao (Phase 5) CLI. Args: <vault|bao> <structure|values>; stdin: root token, then
# the per-run hash key (values only). Diagnostics go to stderr.
set -eu
# No globbing: secret key names containing * or ? must stay literal.
set -f

CLI="${1:-vault}"
VERIFICATION_LEVEL="${2:-structure}"

case "$CLI" in
    vault|bao) ;;
    *)
        echo "[collect-inventory] unknown cli: $CLI (expected vault|bao)" >&2
        exit 2
        ;;
esac

case "$VERIFICATION_LEVEL" in
    structure|values) ;;
    *)
        echo "[collect-inventory] unknown verification_level:" \
             "$VERIFICATION_LEVEL (expected structure|values)" >&2
        exit 2
        ;;
esac

# The token env var name is CLI-specific: vault reads VAULT_TOKEN, bao BAO_TOKEN.
IFS= read -r CLI_TOKEN || true
# Per-run key mixed into every value hash so a stolen inventory file cannot be
# used to brute-force low-entropy secrets offline. Never written to disk.
IFS= read -r HASH_KEY || true
if [ "$VERIFICATION_LEVEL" = "values" ] && [ -z "$HASH_KEY" ]; then
    echo "[collect-inventory] verification_level=values requires a hash key" \
         "on stdin line 2" >&2
    exit 2
fi
if [ "$CLI" = "bao" ]; then
    BAO_TOKEN="$CLI_TOKEN"
    export BAO_TOKEN
else
    VAULT_TOKEN="$CLI_TOKEN"
    export VAULT_TOKEN
fi

err() { echo "[collect-inventory] $*" >&2; }

# fail <what> <captured output>: report a failed CLI call (first line) and exit 3.
fail() {
    err "$1 failed: $(printf '%s\n' "$2" | head -n 1 | cut -c1-200)"
    exit 3
}

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

# Mount/auth/audit paths are the top-level keys (two-space indent) of the JSON.
list_paths() {
    # $1 = CLI subcommand words (e.g. "secrets list")
    # shellcheck disable=SC2086
    _lp_out=$($CLI $1 -format=json 2>&1) || fail "$CLI $1" "$_lp_out"
    printf '%s\n' "$_lp_out" \
        | sed -n 's/^  "\([^"]*\)":[[:space:]]*{.*/\1/p' \
        | sort -u
}

# Policy names: -format=json is a flat JSON array of name strings.
policy_names() {
    _pn_out=$($CLI policy list -format=json 2>&1) \
        || fail "$CLI policy list" "$_pn_out"
    printf '%s\n' "$_pn_out" \
        | sed -e 's/[][",]//g' -e '/^[[:space:]]*$/d' \
        | awk '{$1=$1}; $1 != "" {print $1}' \
        | sort -u
}

# Recursive KV v2 walk under secret/; emits "secret/<path>" per leaf. The prefix
# stays in $1 (frame-local); `local` is not POSIX.
kv_walk() {
    # "No value found" is not an error; anything else emits '!ERROR' (exit 3).
    if ! _kvwalk_out=$($CLI kv list -format=json "secret/$1" 2>&1); then
        printf '%s\n' "$_kvwalk_out" | grep -q 'No value found' || echo '!ERROR'
        return 0
    fi
    _kvwalk_keys=$(printf '%s\n' "$_kvwalk_out" \
            | sed -e 's/[][",]//g' -e '/^[[:space:]]*$/d')
    # Key names with whitespace cannot be word-split; refuse them.
    if printf '%s\n' "$_kvwalk_keys" \
            | grep -q '[^[:space:]][[:space:]][^[:space:]]'; then
        echo '!ERROR'
        return 0
    fi
    for _kvwalk_k in $_kvwalk_keys; do
        case "$_kvwalk_k" in
            */) kv_walk "$1$_kvwalk_k" ;;
            *)  echo "secret/$1$_kvwalk_k" ;;
        esac
    done
}

# ---- gather ----------------------------------------------------------------
engine_mounts=$(list_paths "secrets list")
auth_mounts=$(list_paths "auth list")
audit_devices=$(list_paths "audit list")
policies=$(policy_names)

# A missing built-in mount means the reads failed (bad token, node not active);
# an empty inventory would otherwise compare equal on both sides.
for _m in sys/ cubbyhole/ identity/; do
    printf '%s\n' "$engine_mounts" | grep -qx "$_m" || {
        err "built-in mount $_m not listed: token invalid or node not active"
        exit 3
    }
done

# The KV walk runs only at level "values", so paths are never listed at "structure".
secret_paths=""
if [ "$VERIFICATION_LEVEL" = "values" ] \
        && printf '%s\n' "$engine_mounts" | grep -qx 'secret/'; then
    secret_paths=$(kv_walk "" | sort)
    if printf '%s\n' "$secret_paths" | grep -qx '!ERROR'; then
        err "secret/ walk failed (kv list error or key name with whitespace)"
        exit 3
    fi
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

# policies: [name, sha256] pairs; bodies are hashed in-pod.
printf '  "policies": ['
first=1
if [ -n "$policies" ]; then
    # Here-document, not a pipe, so a failed read exits this shell.
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        # 'root' is listed but not readable; record a constant.
        if [ "$name" = "root" ]; then
            h="builtin-root"
        else
            _pol=$($CLI policy read "$name" 2>&1) \
                || fail "$CLI policy read" "$_pol"
            h=$(printf '%s\n' "$_pol" | sha256sum | awk '{print $1}')
        fi
        if [ "$first" -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '["%s","%s"]' "$(json_escape "$name")" "$h"
    done <<EOF
$policies
EOF
fi
printf '],\n'

# secret_paths: empty at level "structure".
printf '  "secret_paths": '
printf '%s\n' "$secret_paths" | emit_str_array
printf ',\n'

# value_digest <path> — keyed digest of one secret's value map (see below).
value_digest() {
    # Hash only the KV v2 .data.data map (metadata excluded). awk is anchored on
    # the CLI's fixed layout because the images have no python3/jq.
    _vd_out=$($CLI kv get -format=json "$1" 2>&1) || fail "$CLI kv get" "$_vd_out"
    {
        printf '%s\n' "$HASH_KEY"
        printf '%s\n' "$_vd_out" \
            | awk '
                /^    "data": \{\},?$/ { print; exit }
                /^    "data": \{$/     { inb = 1; print; next }
                inb && /^    \},?$/    { print; exit }
                inb                    { print }
            '
    } | sha256sum | awk '{print $1}'
}
# value_hashes: [path, sha256] pairs, only at level "values".
printf '  "value_hashes": ['
first=1
if [ "$VERIFICATION_LEVEL" = "values" ] && [ -n "$secret_paths" ]; then
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        h=$(value_digest "$path")
        if [ "$first" -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '["%s","%s"]' "$(json_escape "$path")" "$h"
    done <<EOF
$secret_paths
EOF
fi
printf ']\n'

printf '}\n'

err "inventory collected (cli=$CLI verification_level=$VERIFICATION_LEVEL)"
exit 0
