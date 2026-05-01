#!/bin/bash

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Script for creating and restoring a raft snapshot of the Openbao platform
# (host) service. Used as the interface between the backup & restore ansible
# role and the local openbao server via the 'bao' CLI.
#
# The bao CLI addresses the local server (127.0.0.1) by default; snapshot
# operations are then sent to the active (leader) server, see below. TLS
# verification: backup relies on the system trust store; restore exports
# BAO_CACERT pointing at the initial self-signed cert (the restore window
# serves only that leaf, before the system CA is installed).
#
# Two distinct secrets are involved:
#   - admin login password: passed as a FILE PATH; bao reads it directly via
#     'password=@<file>'. Never held in a shell variable.
#   - backup encryption passphrase (optional): passed as the NAME of an
#     environment variable holding the value; fed to gpg via a file descriptor,
#     never on a command line and never written to disk.

set -u -o pipefail

BAO_CMD="${BAO_CMD:-/usr/bin/bao}"

# Cert trusted for the restore window (overridable for testing).
BAO_INITIAL_CERT="/etc/openbao/openbao-cert-initial.crt"
BAO_RESTORE_CACERT="${BAO_RESTORE_CACERT:-${BAO_INITIAL_CERT}}"

# Populated after a successful login; exported for the snapshot sub-commands.
BAO_TOKEN=""

# Address of the active (raft leader) server, resolved by openbao_check_health.
# A raft snapshot save/restore MUST be sent to the active server: the bao CLI
# defaults to the local server (127.0.0.1), but on a duplex system the local
# controller may be the standby. 'save' against a standby fails loudly, while
# 'restore' against a standby silently succeeds (rc=0) WITHOUT applying the
# snapshot. We therefore address the leader explicitly and verify the restore.
BAO_LEADER_ADDR=""

# It is possible for bao snapshot restore to fail but with success
# return code; observed when the targeted server is/becomes standby.
# Implement a 'canary' procedure to detect failure.
#
# CANARY_MOUNT: puppet ::restore class omits the kv-v2 mount before
#   restore, it should be restored with the snapshot
# CANARY_PREFIX: tolerate kv-v2 mount existing before restore, inject
#   a canary secret which should be absent after restore
CANARY_MOUNT="secret"
CANARY_PREFIX="admin/snapshot"

# Temp dir for the plaintext snapshot during (de)encryption. Created under the
# destination's own directory so it shares the destination filesystem.
TMPDIR_SNAP=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Print usage information
function usage {
    local prog
    prog="$( basename "$0" )"
    echo "Usage: ${prog} <create|restore> <snapshotpath> <true|false>" \
        "<pw_file> [passphrase_var]"
    echo ""
    echo "Arguments:"
    echo "  create|restore  Command to execute"
    echo "  snapshotpath    Path to the snapshot file"
    echo "                  (create: output; restore: input, must exist)"
    echo "  true|false      Whether the snapshot is encrypted"
    echo "  pw_file         Path to the admin userpass password file"
    echo "                  (bao reads it directly)"
    echo "  passphrase_var  Name of the env var holding the encryption"
    echo "                  passphrase (needed only when encrypted='true')"
    echo ""
    echo "Environment:"
    echo "  BAO_CMD    Path to the bao binary (default /usr/bin/bao)"
    echo "  BAO_RESTORE_CACERT  Cert used to verify bao on restore"
    echo "             (default /etc/openbao/openbao-cert-initial.crt)"
}

# Remove the plaintext-snapshot temp dir, shredding its contents.
# shellcheck disable=SC2329  # invoked indirectly via 'trap cleanup EXIT'
function cleanup {
    if [ -n "${TMPDIR_SNAP}" ] \
        && [ -d "${TMPDIR_SNAP}" ]; then
        if [[ "${TMPDIR_SNAP}" =~ \.bao_snap\.[^/]{1,}\.bao_snap$ ]]; then
            find "${TMPDIR_SNAP}" -type f -exec shred -u {} + 2>/dev/null
            rm -rf "${TMPDIR_SNAP}" 2>/dev/null
        else
            echo "Refuse to delete tmp, the bao snapshot may remain" \
                "on disk: [${TMPDIR_SNAP}]" >&2
        fi
    fi
}
trap cleanup EXIT

# Run the bao CLI and keep its output instead of discarding it. stdout goes to
# BAO_OUT and stderr to BAO_ERR (kept apart so -field=... values such as a
# token are never mixed with warnings). On a non-zero exit the stderr text (or
# stdout when stderr is empty) is printed to OUR stderr with the failing
# sub-command, so an error is never silent. Chatter-tolerant callers (probes
# where failure is an expected answer) redirect with '2>/dev/null'.
# Must be called directly, not inside $( ), so the variables are retained.
BAO_OUT=""
BAO_ERR=""
function bao_run {
    local errf
    local rc

    BAO_OUT=""
    BAO_ERR=""

    errf="$( mktemp --suffix _bao_run_cmd_errf )" || return 1
    BAO_OUT="$( "${BAO_CMD}" "$@" 2>"${errf}" )"
    rc="$?"
    BAO_ERR="$( cat "${errf}" )"
    if [[ "$errf" =~ _bao_run_cmd_errf ]]; then
        if [ -f "$errf" ]; then
            rm -f "${errf}"
        fi
    else
        echo "Refuse to delete [${errf}]," \
            "bao command output may remain on disk" >&2
    fi

    if [ "${rc}" -ne 0 ]; then
        echo "bao $1 failed (rc=${rc}): ${BAO_ERR:-${BAO_OUT}}" >&2
    fi
    return "${rc}"
}

# True when the last bao_run failed only because the path does not exist.
function bao_not_found {
    case "${BAO_ERR}${BAO_OUT}" in
        *"No value found"*) return 0 ;;
    esac
    return 1
}

# Health + readiness. 'bao status' needs no auth. A snapshot op requires the
# server initialized, unsealed, and (for raft) having a leader.
function openbao_check_health {
    local initialized
    local sealed
    local leader

    # rc is non-zero when sealed; bao_run already reported any failure.
    bao_run status -format=json
    if [ -z "${BAO_OUT}" ]; then
        echo "Openbao status returned no data" >&2
        return 1
    fi

    initialized="$( echo "${BAO_OUT}" | jq -r '.initialized' )"
    sealed="$( echo "${BAO_OUT}" | jq -r '.sealed' )"
    leader="$( echo "${BAO_OUT}" | jq -r '.leader_address' )"

    if [ "${initialized}" != "true" ]; then
        echo "Openbao is not initialized" >&2
        return 1
    fi
    if [ "${sealed}" != "false" ]; then
        echo "Openbao is sealed" >&2
        return 1
    fi
    if [ -z "${leader}" ] || [ "${leader}" = "null" ]; then
        echo "Openbao has no raft leader" >&2
        return 1
    fi

    # Remember the active server; snapshot save/restore must target it.
    BAO_LEADER_ADDR="${leader}"

    echo "Openbao is healthy for snapshot operations (leader=${leader})"
    return 0
}

# Login with the admin userpass account. bao reads the password file itself;
# the plaintext password is never placed in a shell variable. The token is
# captured in-memory (-field=token) and not persisted (-no-store).
function openbao_login {
    local pw_file="$1"

    if ! bao_run login -field=token -no-store \
        -method=userpass username=admin password=@"${pw_file}"; then
        return 1
    fi
    BAO_TOKEN="${BAO_OUT}"
    BAO_OUT=""
    if [ -z "${BAO_TOKEN}" ]; then
        echo "Openbao login returned no token" >&2
        return 1
    fi
    export BAO_TOKEN

    # Confirm the token is usable.
    bao_run token lookup >/dev/null
    local rc="$?"
    BAO_OUT=""
    return "${rc}"
}

# A restore replaces the whole raft state, including the token store, so the
# token used before the restore is not valid afterwards. Log in again (the
# leader may still be settling, so retry briefly) before verifying.
function openbao_relogin {
    local pw_file="$1"
    local tries=10

    while [ "${tries}" -gt 0 ]; do
        if openbao_login "${pw_file}" 2>/dev/null; then
            return 0
        fi
        tries=$(( tries - 1 ))
        sleep 1
    done
    # Final attempt reports the error to stderr.
    openbao_login "${pw_file}"
}

# Create a raft snapshot to the given file. Requires a valid BAO_TOKEN.
# Targets the active (leader) server; a save against a standby fails.
function openbao_create_snapshot {
    local outf="$1"
    bao_run operator raft snapshot save \
        -address="${BAO_LEADER_ADDR}" "${outf}"
}

# Restore a raft snapshot from the given file. Requires a valid BAO_TOKEN.
# Targets the active (leader) server; a restore against a standby returns
# success without applying the snapshot, so addressing the leader is required.
function openbao_restore_snapshot {
    local inf="$1"
    bao_run operator raft snapshot restore \
        -address="${BAO_LEADER_ADDR}" "${inf}"
}

# Is the kv-v2 'secret/' mount present on the active server? Absent is an
# expected, tolerated state (see openbao_restore_verified).
#   0 present, 1 absent (definitively), 2 could not be determined (reported).
function openbao_kvv2_mounted {
    if bao_run read -address="${BAO_LEADER_ADDR}" \
        "sys/mounts/${CANARY_MOUNT}" 2>/dev/null; then
        return 0
    fi
    # An unmounted path is the expected state on a restore into a freshly
    # initialized server (kv-v2 is not self-initialized); bao reports it as a
    # 400 "No secret engine mount", not a 404.
    case "${BAO_ERR}" in
        *"No secret engine mount"*) return 1 ;;
    esac
    echo "Cannot determine '${CANARY_MOUNT}/' mount state: ${BAO_ERR}" >&2
    return 2
}

# Write a unique canary secret to the active server and echo its kv path.
# Because the snapshot was captured at backup time, any secret written now is
# guaranteed to be absent from it: a correct restore must therefore remove it.
# (Called inside $( ) so bao's own error is printed via bao_run's stderr.)
function openbao_canary_write {
    local tag="$1"
    local path="${CANARY_PREFIX}/canary_${tag}"
    bao_run kv put -address="${BAO_LEADER_ADDR}" \
        -mount="${CANARY_MOUNT}" "${path}" "v=${tag}" || return 1
    echo "${path}"
}

# Is the canary secret present on the active server?
#   0 present, 1 absent (definitively), 2 could not be determined (reported).
function openbao_canary_state {
    local path="$1"
    if bao_run kv get -address="${BAO_LEADER_ADDR}" \
        -mount="${CANARY_MOUNT}" "${path}" 2>/dev/null; then
        return 0
    fi
    if bao_not_found; then
        return 1
    fi
    echo "Cannot determine canary state: ${BAO_ERR}" >&2
    return 2
}

# Best-effort removal of a canary secret (and its metadata) from the active
# server. Used only when a restore did NOT take effect and the canary must be
# cleaned up; a successful restore removes it implicitly.
function openbao_canary_delete {
    local path="$1"
    bao_run kv metadata delete -address="${BAO_LEADER_ADDR}" \
        -mount="${CANARY_MOUNT}" "${path}" 2>/dev/null || true
}

# Restore a snapshot with verification that it actually took effect on the
# active server. A restore against a standby returns rc=0 without applying the
# snapshot, so rc alone cannot be trusted. Two canary conditions:
#
#   1. kv-v2 'secret/' mount NOT present before restore -> the restore must
#      bring it back; verify the mount is present afterwards.
#   2. kv-v2 'secret/' mount present before restore -> write a unique canary
#      secret (absent from the snapshot, which was captured at backup time),
#      restore, then verify the canary is GONE afterwards.
#
# The restore invalidates the pre-restore token, so we log in again before
# checking; otherwise a 403 would be indistinguishable from "absent".
# Returns 0 only when the restore is proven to have applied; else non-zero.
function openbao_restore_verified {
    local inf="$1"
    local pw_file="$2"
    local canary_path=""
    local had_mount="false"
    local rc

    openbao_kvv2_mounted
    rc="$?"
    if [ "${rc}" -eq 2 ]; then
        return 1
    elif [ "${rc}" -eq 0 ]; then
        had_mount="true"
        canary_path="$( openbao_canary_write "$( date +%s%N )" )"
        if [ -z "${canary_path}" ]; then
            echo "Failed to write restore canary secret" >&2
            return 1
        fi
    fi

    if ! openbao_restore_snapshot "${inf}"; then
        echo "Snapshot restore command failed." >&2
        [ -n "${canary_path}" ] && openbao_canary_delete "${canary_path}"
        return 1
    fi

    if ! openbao_relogin "${pw_file}"; then
        echo "Cannot log in after restore to verify it." >&2
        return 1
    fi

    # Mount was absent before restore; a real restore must recreate it.
    # Otherwise, it should still be there.
    if ! openbao_kvv2_mounted; then
        echo "Restore not applied: '${CANARY_MOUNT}/' absent" >&2
        return 1
    fi
    if [ "${had_mount}" = "true" ]; then
        # A real restore rolls state back to the snapshot, removing the canary.
        openbao_canary_state "${canary_path}"
        rc="$?"
        if [ "${rc}" -eq 0 ]; then
            echo "Restore not applied: canary present (${canary_path})" >&2
            openbao_canary_delete "${canary_path}"
            return 1
        elif [ "${rc}" -ne 1 ]; then
            return 1
        fi
    fi

    return 0
}

# Create a temp dir (0700) alongside the destination so it shares the
# destination filesystem. Sets TMPDIR_SNAP.
function make_tmpdir {
    local dest="$1"
    local parent
    parent="$( dirname "${dest}" )"
    TMPDIR_SNAP="$( mktemp -d "${parent}/.bao_snap.XXXXXX.bao_snap" )"
    chmod 0700 "${TMPDIR_SNAP}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CMD="${1:-}"
SNAPSHOT_PATH="${2:-}"
ENCRYPTED="${3:-}"
PW_FILE="${4:-}"
PASSPHRASE_VAR="${5:-}"

if [ "$#" -ne 4 ] && [ "$#" -ne 5 ]; then
    echo "Expected 4 or 5 arguments, got $#" >&2
    usage
    exit 1
fi

if [ "${CMD}" != "create" ] && [ "${CMD}" != "restore" ]; then
    echo "CMD must be 'create' or 'restore', got '${CMD}'" >&2
    usage
    exit 1
fi

if [ -z "${SNAPSHOT_PATH}" ]; then
    echo "Snapshot path is required" >&2
    usage
    exit 1
fi

if [ "${ENCRYPTED}" != "true" ] && [ "${ENCRYPTED}" != "false" ]; then
    echo "Encrypted must be 'true' or 'false', got '${ENCRYPTED}'" >&2
    usage
    exit 1
fi

if [ -z "${PW_FILE}" ] || [ ! -r "${PW_FILE}" ]; then
    echo "Password file is required and must be readable: '${PW_FILE}'" >&2
    usage
    exit 1
fi

if [ "${ENCRYPTED}" = "true" ]; then
    if [ -z "${PASSPHRASE_VAR}" ]; then
        echo "Passphrase var name is required when encrypted is 'true'" >&2
        usage
        exit 1
    fi
    if [ -z "${!PASSPHRASE_VAR:-}" ]; then
        echo "Env var '${PASSPHRASE_VAR}' is empty; passphrase required" >&2
        usage
        exit 1
    fi
fi

# Restore window: verify bao with the initial self-signed cert. Exported so it
# applies to every bao call below (same effect as -ca-cert=<file>).
if [ "${CMD}" = "restore" ]; then
    if [ ! -r "${BAO_RESTORE_CACERT}" ]; then
        echo "Restore CA cert not readable: '${BAO_RESTORE_CACERT}'" >&2
        exit 1
    fi
    export BAO_CACERT="${BAO_RESTORE_CACERT}"
fi

# Health/readiness is mandatory before any snapshot op.
if ! openbao_check_health; then
    echo "Openbao health check failed" >&2
    exit 1
fi

# Login is mandatory; snapshot save/restore require the admin token.
if ! openbao_login "${PW_FILE}"; then
    echo "Openbao login failed" >&2
    exit 1
fi

if [ "${CMD}" = "create" ]; then
    if [ "${ENCRYPTED}" = "true" ]; then
        # save plaintext snapshot to a 0700/0600 temp, then gpg to the output,
        # then shred the plaintext temp (handled by the EXIT trap).
        make_tmpdir "${SNAPSHOT_PATH}"
        plain="${TMPDIR_SNAP}/snapshot"
        if ! openbao_create_snapshot "${plain}"; then
            echo "Snapshot creation failed." >&2
            exit 1
        fi
        # Passphrase to gpg via fd 3 from the named env var (never on argv).
        if ! { printf '%s' "${!PASSPHRASE_VAR}" \
            | gpg --symmetric \
                --batch \
                --pinentry-mode loopback \
                --passphrase-fd 0 \
                --output "${SNAPSHOT_PATH}" \
                "${plain}"; } ; then
            echo "Snapshot encryption failed." >&2
            exit 1
        fi
    else
        if ! openbao_create_snapshot "${SNAPSHOT_PATH}"; then
            echo "Snapshot creation failed." >&2
            exit 1
        fi
    fi

elif [ "${CMD}" = "restore" ]; then
    if [ ! -r "${SNAPSHOT_PATH}" ]; then
        echo "Snapshot file not found or unreadable: '${SNAPSHOT_PATH}'" >&2
        exit 1
    fi
    if [ "${ENCRYPTED}" = "true" ]; then
        # Decrypt to a 0700/0600 temp, restore, then shred (EXIT trap).
        make_tmpdir "${SNAPSHOT_PATH}"
        plain="${TMPDIR_SNAP}/snapshot"
        if ! (
            umask 0177
            printf '%s' "${!PASSPHRASE_VAR}" \
                | gpg --no-symkey-cache \
                    -q --batch \
                    --passphrase-fd 0 \
                    --pinentry-mode loopback \
                    --output "${plain}" \
                    --decrypt "${SNAPSHOT_PATH}"
        ) || [ ! -s "${plain}" ]; then
            echo "Snapshot decryption failed." >&2
            exit 1
        fi
        if ! openbao_restore_verified "${plain}" "${PW_FILE}"; then
            echo "Snapshot restore failed." >&2
            exit 1
        fi
    else
        if ! openbao_restore_verified "${SNAPSHOT_PATH}" "${PW_FILE}"; then
            echo "Snapshot restore failed." >&2
            exit 1
        fi
    fi
fi

echo "Openbao snapshot operation complete."
exit 0
