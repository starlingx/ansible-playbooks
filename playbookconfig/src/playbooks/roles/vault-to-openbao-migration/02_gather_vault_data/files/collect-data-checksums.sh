#!/bin/sh
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# collect-data-checksums.sh <data_dir> -> builds a checksum manifest of a Vault
# Raft data directory as JSON {data_dir, files:[{path,sha256,bytes}], file_count,
# total_bytes}. It SHA-256-hashes every regular file and records its size, with
# paths RELATIVE to <data_dir> and sorted (LC_ALL=C), so the source and the
# destination manifests can be compared byte-for-byte to confirm the copy is
# complete and unaltered. Read-only: it never modifies <data_dir>. JSON goes to
# stdout, diagnostics to stderr. Exit 0 ok / 2 usage / 4 hash-or-stat failure.
set -eu

err() { echo "[collect-data-checksums] $*" >&2; }

if [ $# -ne 1 ]; then
    err "usage: collect-data-checksums.sh <data_dir>"
    exit 2
fi

DATA_DIR="$1"

if [ ! -d "$DATA_DIR" ]; then
    err "not a directory: $DATA_DIR"
    exit 2
fi

# Pick a sha256 implementation (sha256sum on Linux; shasum -a 256 as fallback).
if command -v sha256sum >/dev/null 2>&1; then
    _sha256() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
    _sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
else
    err "no sha256sum/shasum available"
    exit 4
fi

# Portable regular-file size in bytes (GNU stat -c, BSD stat -f).
_bytes() {
    if stat -c '%s' "$1" >/dev/null 2>&1; then
        stat -c '%s' "$1"
    else
        stat -f '%z' "$1"
    fi
}

# JSON-escape a relative path (backslash then double-quote) via sed; POSIX sh
# has no ${var//a/b} replacement.
_json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

total_bytes=0
file_count=0
first=1

# find | LC_ALL=C sort gives a stable, locale-independent ordering so the source
# and destination manifests line up for a straight comparison. The listing goes
# to a temp file, not a pipe, so the read loop below runs in the current shell
# (a piped `while` is a subshell in POSIX and would lose the counters). The Vault
# Raft data dir holds only fixed, space/newline-free names (node-id, vault.db,
# raft/raft.db), so newline-delimited reads are safe.
#
# Create the temp file in its own 0700 dir so no other user can pre-create or
# swap it, and clean up with an unlink of the exact path we created (guarded so
# the trap never runs a removal on an empty variable).
_tmpdir="$(mktemp -d)"
_list="$_tmpdir/list"
cleanup() {
    [ -n "${_tmpdir:-}" ] && [ -d "$_tmpdir" ] && unlink "$_list" 2>/dev/null
    [ -n "${_tmpdir:-}" ] && [ -d "$_tmpdir" ] && rmdir "$_tmpdir" 2>/dev/null
    return 0
}
trap cleanup EXIT INT TERM
find "$DATA_DIR" -type f | LC_ALL=C sort > "$_list"

# Emit the JSON incrementally so we never hold the whole tree in memory.
printf '{\n'
printf '  "data_dir": "%s",\n' "$(_json_escape "$DATA_DIR")"
printf '  "files": [\n'

while IFS= read -r abs; do
    rel="${abs#"$DATA_DIR"}"
    rel="${rel#/}"

    if ! sz="$(_bytes "$abs" 2>/dev/null)"; then
        err "FAILED to stat: $abs"
        exit 4
    fi
    if ! sum="$(_sha256 "$abs" 2>/dev/null)"; then
        err "FAILED to hash: $abs"
        exit 4
    fi

    if [ "$first" -eq 0 ]; then
        printf ',\n'
    fi
    first=0

    printf '    {"path": "%s", "sha256": "%s", "bytes": %s}' \
        "$(_json_escape "$rel")" "$sum" "$sz"

    total_bytes=$((total_bytes + sz))
    file_count=$((file_count + 1))
done < "$_list"

printf '\n  ],\n'
printf '  "file_count": %s,\n' "$file_count"
printf '  "total_bytes": %s\n' "$total_bytes"
printf '}\n'

err "collected $file_count file(s), total_bytes=$total_bytes under $DATA_DIR"
exit 0
