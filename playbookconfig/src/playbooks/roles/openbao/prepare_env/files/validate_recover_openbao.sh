#!/bin/bash
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# The unsealed state of all openbao server pods is required for the openbao
# snapshot restore procedure.
#
# Under normal circumstances the openbao restore procedure does not
# require the user to put the openbao application into the required state.
# This script attempts to put the openbao server pods into an unsealed
# state - this includes deleting PVCs and shard secrets.
#
# The script ends by verifying the required state, or failing.

OPENBAO_NS="openbao"
OPENBAO_REAPPLIED=false
APP_TAR_PATH="/usr/local/share/applications/helm"

# List of pauses
# app upload:
#     60s == OPENBAO_UPLOAD_TRIES @ OPENBAO_UPLOAD_SLEEP intervals
# app abort:
#     120s == OPENBAO_ABORT_TRIES @ OPENBAO_ABORT_SLEEP intervals
# app remove:
#     60s == OPENBAO_REMOVE_TRIES @ OPENBAO_REAPPLY_WAITTIME intervals
# PVC delete:
#     120s == PVC_DELETE_TRIES @ OPENBAO_REAPPLY_WAITTIME intervals
# cluster-key delete:
#     60s == CLUSTER_KEY_DELETE_TRIES @ OPENBAO_REAPPLY_WAITTIME intervals
# app apply:
#     300s == OPENBAO_APPLY_TRIES @ OPENBAO_REAPPLY_WAITTIME intervals
# post apply wait time:
#     30s == OPENBAO_UNSEAL_WAITTIME
# unseal per pod:
#     60s == SEALED_STATUS_TRIES @ SEALED_STATUS_WAITTIME intervals

# Number of tries for each action
MAIN_TRIES=2
SEALED_STATUS_TRIES=6
OPENBAO_REMOVE_TRIES=5
PVC_DELETE_TRIES=12
CLUSTER_KEY_DELETE_TRIES=6
OPENBAO_APPLY_TRIES=30
OPENBAO_UPLOAD_TRIES=12
OPENBAO_ABORT_TRIES=24

# Wait times
SEALED_STATUS_WAITTIME=10
OPENBAO_REAPPLY_WAITTIME=10
OPENBAO_UNSEAL_WAITTIME=30
OPENBAO_UPLOAD_SLEEP=5
OPENBAO_ABORT_SLEEP=5

# variables for interpreting application state
# These states are handled by reapplyOpenbao():
APP_STATES="uploading uploaded removing applying applied apply-failed"
REGEX_DELETED="application not found: openbao"
REGEX_NORESOURCES="No resources found in openbao namespace."
APP_STATUS_DEBUG=""

# Generic instruction to the user
GENERIC_INSTRUCTION="$( echo "Resolve the application/platform status" \
    "before running the restore procedure again." )"

# Function to get the application status, insert custom states for
# "deleted" (not-uploaded), and "unknown" for application states this
# script does not address
function getOpenbaoStatus {
    local status
    local result

    # capture both stdout and stderr; When the application is not
    # uploaded then the stderr indicates this response
    status="$( system application-show openbao \
        --format value --column status 2>&1 )"
    result="$?"
    APP_STATUS_DEBUG="$status"
    if [ "$result" -ne 0 ]; then
        if [[ "$status" == *"$REGEX_DELETED"* ]]; then
            status="deleted"
        fi
    fi
    if [[ " $APP_STATES deleted " != *" ${status// /_} "* ]]; then
        status="unknown"
    fi

    echo "$status"
}

function uploadopenbao {
    local status="$1"
    local count=1
    local uploaded

    # The platform may upload the application. Ignore a failed result
    # for application-upload
    if [ "$status" == "deleted" ]; then
        system application-upload "$APP_TAR_PATH"/openbao*.tgz
    fi

    # A small wait before checking the upload status.
    # Start counting at 1 to get OPENBAO_UPLOAD_TRIES sleeps total
    sleep $OPENBAO_UPLOAD_SLEEP
    while [ "$count" -lt "$OPENBAO_UPLOAD_TRIES" ]; do
        uploaded="$( getOpenbaoStatus )"
        echo "openbao application status: $uploaded"
        if [ "$uploaded" == "uploaded" ]; then
            break;
        elif [ "$uploaded" == "deleted" ]; then
            true # pass, the platform is sloooow today
        elif [ "$uploaded" != "uploading" ]; then
            # invoke the failure path
            count="$OPENBAO_UPLOAD_TRIES"
            break
        fi

        count="$(( count + 1 ))"
        sleep $OPENBAO_UPLOAD_SLEEP
    done

    if [ "$count" -ge "$OPENBAO_UPLOAD_TRIES" ]; then
        echo "Failed to upload openbao in" \
            "$(( $OPENBAO_UPLOAD_TRIES * $OPENBAO_UPLOAD_SLEEP ))s." \
            "$GENERIC_INSTRUCTION"
        echo "Application status: [$APP_STATUS_DEBUG]"
        exit 1
    fi

    echo "Application uploaded."
}

function abortOpenbao {
    local count=0
    local aborted

    # "applying" was the trigger state for this function.
    # Expect: applying, applied, apply-failed
    # And ignore the result of system application-abort
    system application-abort openbao

    # Normally the abort will happen promptly, such as when the app was
    # applying for some time already.  A short initial sleep is
    # not required.  But when running application-apply and
    # application-abort in quick succession the actual time is observed
    # at 60s typical for that case.
    while [ "$count" -lt "$OPENBAO_ABORT_TRIES" ]; do
        aborted="$( getOpenbaoStatus )"
        echo "openbao application status: $aborted"
        if [ "$aborted" == "apply-failed" ]; then
            # either interpretation of apply-failed is ok
            break;
        elif [ "$aborted" == "applying" ]; then
            true # pass, abort can take a while
        elif [ "$aborted" == "applied" ]; then
            # race condition probably between seeing 'applying' and
            # running application-abort
            break
        else
            # invoke the failure path
            count="$OPENBAO_ABORT_TRIES"
            break;
        fi

        count="$(( count + 1 ))"
        sleep $OPENBAO_ABORT_SLEEP
    done

    if [ "$count" -ge "$OPENBAO_ABORT_TRIES" ]; then
        echo "Failed to abort apply of openbao app within" \
            "$(( $OPENBAO_ABORT_TRIES * $OPENBAO_ABORT_SLEEP ))s." \
            "$GENERIC_INSTRUCTION"
        echo "Application status: [$APP_STATUS_DEBUG]"
        exit 1
    fi

    echo "Application apply aborted."
}

# Function to clean openbao and reapply.
function reapplyOpenbao {
    local state
    local tries
    local remainingPVC
    local deleteSecrets
    local key
    local keyDelete
    local remaining
    local pods

    if $OPENBAO_REAPPLIED; then
        echo "openbao reapply already tried. Previous apply likely failed."
        return 1
    fi

    # Do not try to fix openbao more than once
    OPENBAO_REAPPLIED=true

    state="$( getOpenbaoStatus )"
    echo "openbao application status: $state"
    if [[ " deleted uploading " == *" $state "* ]]; then
        # exits on failure; else the state is "uploaded"
        uploadopenbao $state
        state="$( getOpenbaoStatus )"
        echo "openbao application status: $state"
    elif [ "$state" == "applying" ]; then
        # Handle this abortable state without giving the app the benefit
        # of the doubt: during restore we anticipate that the
        # application may be waiting for openbao server pods that cannot
        # unseal.
        #
        # exits on failure; else the state is "uploaded", or possibly
        # the state is "applied" due to race
        abortOpenbao
        state="$( getOpenbaoStatus )"
        echo "openbao application status: $state"
    fi

    if [[ " applied apply-failed " == *" $state "* ]]; then
        system application-remove openbao
    fi

    # Seeing the 'removing' status from a previous operation is
    # unlikely, as in practice system application-show does not run fast
    # enough to catch it.  But it should be accounted for.
    if [[ " applied apply-failed removing " == *" $state "* ]]; then
        for tries in $(seq $OPENBAO_REMOVE_TRIES); do
            sleep $OPENBAO_REAPPLY_WAITTIME
            state="$( getOpenbaoStatus )"
            echo "openbao application status: $state"
            if [[ "$state" == "uploaded" ]]; then
                echo "openbao remove completed"
                break
            fi
        done

        # state is updated within the loop
    fi
    # also wait for pods to be removed, for example: before trying
    # to delete the persistentvolumeclaims
    # but ignore if there are still pods
    for tries in $(seq $OPENBAO_REMOVE_TRIES); do
        sleep $OPENBAO_REAPPLY_WAITTIME
        pods="$( kubectl get pods -n $OPENBAO_NS 2>&1 )"
        if [ "$pods" == "$REGEX_NORESOURCES" ]; then
            break;
        fi
    done

    # the state of the application should be "uploaded"
    if [ "$state" != "uploaded" ]; then
        # Other states that we're not handling include: missing,
        # upload-failed, remove-failed, updating, recovering
        # restore-requested
        echo "Failed to put the openbao application into uploaded state." \
            "$GENERIC_INSTRUCTION" \
            "Application status: $state [$APP_STATUS_DEBUG]"
        exit 1
    fi

    # remove PVC resource
    kubectl delete pvc -n $OPENBAO_NS --all
    remainingPVC=-1
    for tries in $(seq $PVC_DELETE_TRIES); do
        sleep $OPENBAO_REAPPLY_WAITTIME
        remainingPVC="$(kubectl get pvc -n $OPENBAO_NS \
                    --no-headers=true | wc -l)"
        if [[ $remainingPVC -eq 0 ]]; then
            echo "openbao PVC removal completed"
            break
        fi
    done
    if [[ $remainingPVC -ne 0 ]]; then
        echo "remove pvc resource failed"
        return 1
    fi

    # remove openbao cluster-key and the root CA secrets
    deleteSecrets="$( kubectl get secrets -n $OPENBAO_NS \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
        | grep '^cluster-key\|^openbao-ca$' )"
    for key in $deleteSecrets; do
        kubectl delete secret -n $OPENBAO_NS "$key"
        keyDelete=$?
        if [[ $keyDelete -ne 0 ]]; then
            echo "kubectl-delete-secret returned error"
            return 1
        fi
    done
    remaining=-1
    for tries in $(seq $CLUSTER_KEY_DELETE_TRIES); do
        sleep $OPENBAO_REAPPLY_WAITTIME
        remaining="$( kubectl get secrets -n $OPENBAO_NS \
            -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
            | grep '^cluster-key\|^openbao-ca$' | wc -l )"
        if [[ remaining -eq 0 ]]; then
            echo "openbao secret removal completed"
            break
        fi
    done
    if [[ $remaining -ne 0 ]]; then
        echo "remove secrets failed"
        return 1
    fi

    # application-apply
    system application-apply openbao
    for tries in $(seq $OPENBAO_APPLY_TRIES); do
        sleep $OPENBAO_REAPPLY_WAITTIME
        state="$( getOpenbaoStatus )"
        echo "openbao application status: $state"
        if [[ "$state" == "applied" ]]; then
            echo "openbao apply completed"
            break
        fi
    done
    if [[ "$state" != "applied" ]]; then
        echo "openbao Reapply: application-apply failed"
        return 1
    fi

    # The openbao server pods remain in unready state until the server is
    # unsealed due to using the healthz endpoint for pod readiness
    # probe.  The openbao application remains in applying status until the
    # first openbao server pod transitions to ready state.
    #
    # For the case of replicas>1, openbao server unseal validation is done
    # in the main

    return 0
}

###
# Main
#

JPATHFULL='{range .items[*]}{.metadata.name}{" "}'\
'{.metadata.labels.openbao-sealed}{"\n"}{end}'
JPATH="$(printf '%s\n' $JPATHFULL | tr '\n' ' ')"

echo "Validating openbao status"
source "/etc/platform/openrc"

for validateTries in $(seq $MAIN_TRIES); do
    echo "Attempting validation number $validateTries"
    # check if openbao application is applied or applying
    rst="$( getOpenbaoStatus )"
    echo "openbao application status: $rst"
    if [ "$rst" != "applied" -a "$rst" != "applying" ]; then
        # if not, run recovery
        echo "openbao not applied. Attempting reapply..."
        reapplyOpenbao
        reapplyOpenbaoRC=$?
        if [[ reapplyOpenbaoRC -eq 0 ]]; then
            echo "openbao reapply completed. Reattempting validation."
            continue
        else
            echo "openbao reapply failed for trying to" \
                "fix not-applied openbao application." \
                "Unable to ready openbao for restore."
            exit 1
        fi

    fi

    # Whether 'applied' or 'applying', we expect to see a running openbao
    # server pod.  In the applying case, there is a window where the
    # applying procedure hasn't gotten that far. Ignore this possibility
    # when it comes from outside this procedure - run abort as if the
    # app is stuck.
    #
    # Check if there is a running openbao pod:
    numRunningPods="$(kubectl get pods -n $OPENBAO_NS | \
                        grep "^stx-openbao-[0-9] " | grep "Running" | wc -l)"
    if [[ $numRunningPods -eq 0 ]]; then
        # if not, run recovery
        echo "No openbao pods are running. Attempting reapply..."
        reapplyOpenbao
        reapplyOpenbaoRC=$?
        if [[ $reapplyOpenbaoRC -eq 0 ]]; then
            echo "openbao reapply completed. Reattempting validation."
            continue
        else
            echo "openbao reapply failed for trying to" \
                "fix no running openbao pods." \
                "Unable to ready openbao for restore."
            exit 1
        fi
    fi

    # Whether applied or applying, in both cases it is possible for a
    # openbao server pod to be waiting to be unsealed.  Wait upon the
    # sealed status of all pods.
    sealedPods=0
    prevSealedPods=0
    sealedExists=true
    triesCount=$SEALED_STATUS_TRIES
    while [[ $triesCount -gt 0 ]]; do
        # get number of sealed pods
        # When pods are starting they have no seal status (empty
        # string). So search for and omit unsealed pods instead.
        sealedPods="$( kubectl get pods -n $OPENBAO_NS -o jsonpath="$JPATH" \
                        | grep "^stx-openbao-[0-9] " \
                        | grep -v "false$" | wc -l )"

        # check if there are no sealed pods, if so mark success and break loop
        if [[ $sealedPods -eq 0 ]]; then
            sealedExists=false
            break
        fi

        # if number of sealed pods decreased, reset wait counter
        if [[ $sealedPods -lt $prevSealedPods ]]; then
            triesCount=$SEALED_STATUS_TRIES
        else
            triesCount=$(( triesCount - 1 ))
        fi

        # wait for pods to unseal
        sleep $SEALED_STATUS_WAITTIME
        prevSealedPods=$sealedPods
    done

    # if there are still sealed pods, attempt reapply
    if $sealedExists; then
        echo "There are sealed pods. Attempting reapply..."
        reapplyOpenbao
        reapplyOpenbaoRC=$?
        if [[ $reapplyOpenbaoRC -eq 0 ]]; then
            echo "openbao reapply completed. Reattempting validation."
            continue
        else
            echo "openbao reapply failed for trying to" \
                "fix sealed openbao pods." \
                "Unable to ready openbao for restore."
            exit 1
        fi
    fi

    # all test passed. exit
    echo "All validation passed. openbao application is ready to be restored."
    exit 0
done

echo "All tries exhausted. Unable to ready openbao for restore."
exit 1
