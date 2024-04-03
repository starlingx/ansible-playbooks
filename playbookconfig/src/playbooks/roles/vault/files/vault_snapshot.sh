#!/bin/bash

# Script to take a snapshot of the vault

###
#  Globals
#

NAME="$( basename $0 )"

KUBECMD="kubectl"
SCRIPT="source /opt/script/init.sh"
MAXATTEMPTS=10
GPGSLEEP=6

K8S_SECRET_PREFIX="snapshot-metadata"
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
        "$NAME <output_dir> [--encrypt <variable> ]\n" \
        "\n" \
        "All parameters are positional:\n" \
        "  output_dir: required, location to output snapshot tarball\n" \
        "   --encrypt: optional\n" \
        "    variable: required if --encrypt is specified, the name\n" \
        "              of a variable containing a secret with which\n" \
        "              encrypt the snapshot\n" >&2

}

# Exit with the specified code after unpausing the vault manager
function unpause_exit {
    local toreturn="$1"

    # don't worry about the result
    kubectl exec -n "$VAULT_NS" "$POD" -- \
        bash -c "${SCRIPT}; rm \"\${PAUSEFILE}\""

    exit $toreturn
}

# The stdout is a tarball
function get_snapshot {
    kubectl exec -n "$VAULT_NS" "$POD" -- \
        bash -c "${SCRIPT}; snapshotCreate"
}

# Intended for deleting the fifo files
function cleanup {
    rm $2 2>/dev/null
    rmdir $1 2>/dev/null
}

# Retrieve a snapshot for the vault, using vault-manager's code, and
# encrypt the file using the user-supplied passphrase
#
# The snapshot is received as stdin from vault-manager, whereas the
# passphrase is provided to gpg via fifo file.
function get_encrypted_snapshot {
    local secret="$1"
    local outf="$2"
    local tmpf
    local tmpd
    local gpgpid
    local attempts
    local result

    tmpd="$( mktemp -d )"
    tmpf="${tmpd}/.snapshot"

    # try our best to make sure the fifo file is deleted.
    trap "cleanup $tmpd $tmpf" SIGTERM
    trap "cleanup $tmpd $tmpf" SIGINT
    trap "cleanup $tmpd $tmpf" EXIT
    trap "cleanup $tmpd $tmpf" RETURN

    mkfifo -m 600 "$tmpf"

    # run gpg in the background, waiting for passphrase on fifo file
    get_snapshot \
    | gpg --symmetric \
    --output="$outf" \
    --passphrase-file "$tmpf" \
    --batch \
    --pinentry-mode loopback \
    /dev/stdin  &

    gpgpid=$!

    echo -n "${!secret}" > "$tmpf"

    # wait for gpgpid
    attempts=0
    while [ "$attempts" -lt "$MAXATTEMPTS" ]; do
        ps -p $gpgpid >/dev/null 2>&1
        if [ $? -ne 0 ]; then
            break
        fi
        attempts=$(( attempts + 1 ))
        sleep $GPGSLEEP
    done

    if [ "$attempts" -ge "$MAXATTEMPTS" ]; then
        echo "failed to wait for gpg" >&2
        kill $gpgpid

        return 1
    fi

    wait $gpgpid
    result=$?

    # don't leave a passphrase laying around, in case the fifo
    # was unread
    rm -r "$tmpd" 2>/dev/null >/dev/null

    return $result
}

# Use mktemp to get a random string and test to see if a k8s secret
# already exists with that suffix within the vault namespace
#
# Try a few times before giving up; unpause the vault-manager and
# exit on failure.
#
# Return the random string via stdout
function get_unique_string {
    local attempts
    local rndtmp
    local secret
    local secrets

    # the loop below runs really fast, ready the secret names
    # once should be fine
    secrets="$( kubectl get secrets -n "$VAULT_NS" \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | grep "^${K8S_SECRET_PREFIX}" )"

    attempts=0
    while [ "$attempts" -lt "$MAXATTEMPTS" ]; do
        rndtmp="$( mktemp --dry-run \
            | cut -f 2 -d'.' \
            | tr '[:upper:]' '[:lower:]' )"
        secret="${K8S_SECRET_PREFIX}-$rndtmp"
        if [[ " $secrets " != *"$secret"* ]]; then
            break
        fi
        attempts=$(( attempts + 1 ))
    done

    if [ "$attempts" -ge "$MAXATTEMPTS" ]; then
        echo "Failed to get a unique string for the snapshot" >&2
        unpause_exit 1
    fi

    echo -n "$rndtmp"
}


###
# Main
#

OUTPUTDIR="$1"
ENCRYPT="$2"
SECRET="$3"

if [ -z "$OUTPUTDIR" -o ! -d "$OUTPUTDIR" ]; then
    echo "Non-existing output directory: [$OUTPUTDIR]" >&2
    usage
    exit 1
fi
if [ -n "$ENCRYPT" ]; then
    if [ ! "$ENCRYPT" = "--encrypt" ]; then
        echo "Unrecognized parameter: [$ENCRYPT]" >&2
        usage
        exit 1
    elif [ -z "$SECRET" ]; then
        echo "Required variable name when --encrypt is used" >&2
        usage
        exit 1
    elif [ -z "${!SECRET}" ]; then
        echo "Required secret when --encrypt is used" \
            "(is '$SECRET' variable exported?)" >&2
        usage
        exit 1
    fi
fi

# Pause vault manager
logs="$( kubectl exec -n "$VAULT_NS" "$POD" -- \
    bash -c "${SCRIPT}; touch \"\${PAUSEFILE}\"" 2>&1 )"
if [ $? -ne 0 ]; then
    echo "Failed to pause vault-manager: [$logs]" >&2
    exit 1
fi

# ensure that vault is in a good state for taking the snapshot
logs="$( kubectl exec -n "$VAULT_NS" "$POD" -- \
    bash -c "${SCRIPT}; snapshotPreCheck" 2>&1 )"
if [ $? -ne 0 ]; then
    echo "$logs" >&2
    unpause_exit 1
fi

rndtmp="$( get_unique_string )"
secret="${K8S_SECRET_PREFIX}-$rndtmp"
fname="${OUTPUTDIR}/snapshot-${rndtmp}.tar"
metaf="${fname}.metadata"

# get the snapshot
if [ "$ENCRYPT" == "--encrypt" ]; then
    encrypted=true
    get_encrypted_snapshot "$SECRET" "$fname"
    if [ $? -ne 0 ]; then
        unpause_exit 1
    fi
else
    encrypted=false
    get_snapshot > "$fname"
    if [ $? -ne 0 ]; then
        unpause_exit 1
    fi
fi

# Prepare metadata file. This procedure only uses 'secret',
# but I'm sure the other information will be useful to humans
sum="$( sha256sum "$fname" | cut -f 1 -d' ' )"
now="$( date )"

metadata="{\"date\":\"$now\",
    \"snapshot_sum\":\"$sum\",
    \"secret\":\"$secret\",
    \"user_encrypted\":\"$encrypted\"}"

echo "$metadata" > "${metaf}"

# write the metadata to k8s secret, along with the shards
# associated with the snapshot
kubectl exec -n "$VAULT_NS" "$POD" -- \
    bash -c "${SCRIPT}; snapshotSetSecret '$secret' '$metadata'"
if [ $? -ne 0 ]; then
    echo "Failed to set k8s secret for snapshot" >&2
    unpause_exit 1
fi

unpause_exit 0
