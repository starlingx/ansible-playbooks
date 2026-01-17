#!/bin/bash

# Script to restore a snapshot to the vault

###
#  Globals
#

NAME="$( basename $0 )"

KUBECMD="kubectl"
SCRIPT="source /opt/script/init.sh"

VAULT_NS="vault"
MANAGER_PREFIX="sva-vault-manager"

# get vault manager pod
JSONPATH='{range .items[*]}{.metadata.name}{"\n"}{end}'
POD="$( $KUBECMD get pods -n "$VAULT_NS" -o jsonpath="$JSONPATH" \
    | grep "^$MANAGER_PREFIX" )"

if [ -z "$POD" ]; then
    echo "Vault manager not found" >&2
    exit 1
fi

###
# Functions
#

function usage {
    echo -e "Usage: \n" \
        "\n" \
        "$NAME <input_file> [--decrypt <variable> ]\n" \
        "\n" \
        "All parameters are positional:\n" \
        "  input_file: required, snapshot file to restore from\n" \
        "   --decrypt: optional\n" \
        "    variable: required if --decrypt is specified, the name\n" \
        "              of a variable containing a secret with which\n" \
        "              decrypt the snapshot file\n" >&2
}

# Exit with the specified code after unpausing the vault manager
function unpause_exit {
    local toreturn="$1"

    # don't worry about the result
    kubectl exec -n "$VAULT_NS" "$POD" -- \
        bash -c "${SCRIPT}; rm \"\${PAUSEFILE}\""

    exit $toreturn
}


###
# Main
#

INPUTFILE="$1"
DECRYPT="$2"
SECRET="$3"

if [ -z "$INPUTFILE" -o ! -f "$INPUTFILE" ]; then
    echo "Non-existing snapshot file: [$INPUTFILE]" >&2
    usage
    exit 1
fi

if [ -n "$DECRYPT" ]; then
    if [ ! "$DECRYPT" = "--decrypt" ]; then
        echo "Unrecognized parameter: [$DECRYPT]" >&2
        usage
        exit 1
    elif [ -z "$SECRET" ]; then
        echo "Required variable name when --decrypt is used" >&2
        usage
        exit 1
    elif [ -z "${!SECRET}" ]; then
        echo "Required secret when --decrypt is used" \
            "(is '$SECRET' variable exported?)" >&2
        usage
        exit 1
    fi
fi


# get the metadata, and snapshot secret associated with the snapshot
# file.  This is expected to be in the same directory as the snapshot
METADATAF="${INPUTFILE}.metadata"
if [ ! -f "$METADATAF" ]; then
    echo "The metadata file associated with snapshot file" \
        "$INPUTFILE is not found: $METADATAF" >&2
    exit 1
fi

# vault manager code will do more sanity on the json, make sure
# at least that it is not empty
METADATA="$( cat "$METADATAF" )"
if [ -z "$METADATA" ]; then
    echo "The metadata should at least contain:" \
        '{"secret":"name_of_k8s_secret"}' >&2
    exit 1
fi

# Pause vault manager
logs="$( kubectl exec -n "$VAULT_NS" "$POD" -- \
    bash -c "${SCRIPT}; touch \"\${PAUSEFILE}\"" 2>&1 )"
if [ $? -ne 0 ]; then
    echo "Failed to pause vault-manager: [$logs]" >&2
    exit 1
fi

# ensure that vault is in a good state for restoring the snapshot
logs="$( kubectl exec -n "$VAULT_NS" "$POD" -- \
    bash -c "${SCRIPT}; snapshotPreCheck" 2>&1 )"
if [ $? -ne 0 ]; then
    echo "$logs" >&2
    unpause_exit 1
fi

# restore the snapshot
if [ "$DECRYPT" == "--decrypt" ]; then
    logs="$( echo "${!SECRET}" \
        | gpg --no-symkey-cache \
            -q \
            --batch \
            --passphrase-fd 0 \
            --decrypt "$INPUTFILE" \
        | kubectl exec -n "$VAULT_NS" "$POD" -i -- \
            bash -c "${SCRIPT}; \
                snapshotRestore '$METADATA'" )"

    if [ $? -ne 0 ]; then
        echo "Failed to restore snapshot: [$logs]" >&2
        unpause_exit 1
    fi
else
    logs="$( cat "$INPUTFILE" \
        | kubectl exec -n "$VAULT_NS" "$POD" -i -- \
            bash -c "${SCRIPT}; \
                snapshotRestore '$METADATA'" )"

    if [ $? -ne 0 ]; then
        echo "Failed to restore snapshot: [$logs]" >&2
        unpause_exit 1
    fi
fi

echo "Snapshot restore complete." >&2
unpause_exit 0
