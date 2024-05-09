#!/bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# This script validates if the hashicorp vault application is
# ready to be restored, and if not, attempts to reapply application

VAULT_NS="vault"
VAULT_REAPPLIED=false

# List of pauses
# app remove:
#     60s == VAULT_REMOVE_TRIES @ VAULT_REAPPLY_WAITTIME intervals
# PVC delete:
#     120s == PVC_DELETE_TRIES @ VAULT_REAPPLY_WAITTIME intervals
# cluster-key delete:
#     60s == CLUSTER_KEY_DELETE_TRIES @ VAULT_REAPPLY_WAITTIME intervals
# app apply:
#     300s == VAULT_APPLY_TRIES @ VAULT_REAPPLY_WAITTIME intervals
# post apply wait time:
#     30s == VAULT_UNSEAL_WAITTIME
# unseal per pod:
#     60s == SEALED_STATUS_TRIES @ SEALED_STATUS_WAITTIME intervals

# Number of tries for each action
MAIN_TRIES=2
SEALED_STATUS_TRIES=6
VAULT_REMOVE_TRIES=5
PVC_DELETE_TRIES=12
CLUSTER_KEY_DELETE_TRIES=6
VAULT_APPLY_TRIES=30

# Wait times
SEALED_STATUS_WAITTIME=10
VAULT_REAPPLY_WAITTIME=10
VAULT_UNSEAL_WAITTIME=30

# Function to clean vault and reapply.
function reapplyVault {

    if $VAULT_REAPPLIED; then
        echo "Vault reapply already tried. Previous apply likely failed."
        return 1
    fi

    # application-remove
    system application-remove vault
    rst=""
    for tries in $(seq $VAULT_REMOVE_TRIES); do
        sleep $VAULT_REAPPLY_WAITTIME
        rst="$(system application-show vault --format value --column status)"
        if [[ "$rst" == "uploaded" ]]; then
            echo "Vault remove completed"
            break
        fi
    done
    if [[ "$rst" != "uploaded" ]]; then
        echo "Vault Reapply: application-remove failed"
        return 1
    fi

    # remove PVC resource
    kubectl delete pvc -n $VAULT_NS --all
    remainingPVC=-1
    for tries in $(seq $PVC_DELETE_TRIES); do
        sleep $VAULT_REAPPLY_WAITTIME
        remainingPVC="$(kubectl get pvc -n $VAULT_NS \
                    --no-headers=true | wc -l)"
        if [[ $remainingPVC -eq 0 ]]; then
            echo "Vault PVC removal completed"
            break
        fi
    done
    if [[ $remainingPVC -ne 0 ]]; then
        echo "remove pvc resource failed"
        return 1
    fi

    # remove vault cluster-key secrets
    clusterKeys="$(kubectl get secrets -n vault \
                | grep 'cluster-key' | awk '{print $1}')"
    for cKey in $clusterKeys; do
        kubectl delete secret -n $VAULT_NS "$cKey"
        cKeyDelete=$?
        if [[ $cKeyDelete -ne 0 ]]; then
            echo "kubectl-delete-secret returned error"
            return 1
        fi
    done
    remainingCKey=-1
    for tries in $(seq $CLUSTER_KEY_DELETE_TRIES); do
        sleep $VAULT_REAPPLY_WAITTIME
        remainingCKey="$(kubectl get secrets -n vault \
                | grep 'cluster-key' | wc -l)"
        if [[ remainingCKey -eq 0 ]]; then
            echo "Vault secret removal completed"
            break
        fi
    done
    if [[ $remainingCKey -ne 0 ]]; then
        echo "remove cluster key secret failed"
        return 1
    fi

    # application-apply
    system application-apply vault
    rst=""
    for tries in $(seq $VAULT_APPLY_TRIES); do
        sleep $VAULT_REAPPLY_WAITTIME
        rst="$(system application-show vault --format value --column status)"
        if [[ "$rst" == "applied" ]]; then
            echo "Vault apply completed"
            break
        fi
    done
    if [[ "$rst" != "applied" ]]; then
        echo "Vault Reapply: application-remove failed"
        return 1
    fi

    # Wait for vault manager to initiate and unseal new pods.
    # Pod unseal validation is done in the main
    sleep $VAULT_UNSEAL_WAITTIME

    # reapply completed. return back to main
    VAULT_REAPPLIED=true
    return 0
}

###
# Main
#

JPATHFULL='{range .items[*]}{.metadata.name}{" "}'\
'{.metadata.labels.vault-sealed}{"\n"}{end}'
JPATH="$(printf '%s\n' $JPATHFULL | tr '\n' ' ')"

echo "Validating vault status"
source "/etc/platform/openrc"

for validateTries in $(seq $MAIN_TRIES); do
    echo "Attempting validation number $validateTries"
    # check if vault application is applied
    rst="$(system application-show vault --format value --column status)"
    if [[ "$rst" != "applied" ]]; then
        # if not, run recovery
        echo "Vault not applied. Attempting reapply..."
        reapplyVault
        reapplyVaultRC=$?
        if [[ reapplyVaultRC -eq 0 ]]; then
            echo "Vault reapply completed. Reattempting validation."
            continue
        else
            echo "Vault reapply failed for trying to" \
                "fix not-applied vault application." \
                "Unable to ready vault for restore."
            exit 1
        fi

    fi

    # check if there is a running vault pod
    numRunningPods="$(kubectl get pods -n $VAULT_NS | \
                        grep "^sva-vault-[0-9] " | grep "Running" | wc -l)"
    if [[ $numRunningPods -eq 0 ]]; then
        # if not, run recovery
        echo "No vault pods are running. Attempting reapply..."
        reapplyVault
        reapplyVaultRC=$?
        if [[ $reapplyVaultRC -eq 0 ]]; then
            echo "Vault reapply completed. Reattempting validation."
            continue
        else
            echo "Vault reapply failed for trying to" \
                "fix no running vault pods." \
                "Unable to ready vault for restore."
            exit 1
        fi
    fi

    # check for sealed status

    sealedPods=0
    prevSealedPods=0
    sealedExists=true
    while [[ $SEALED_STATUS_TRIES -gt 0 ]]; do
        # get number of sealed pods
        sealedPods="$( kubectl get pods -n $VAULT_NS -o jsonpath="$JPATH" | \
                        grep "^sva-vault-[0-9] " | grep "true" | wc -l )"

        # check if there are no sealed pods, if so mark success and break loop
        if [[ $sealedPods -eq 0 ]]; then
            sealedExists=false
            break
        fi

        # if number of sealed pods decreased, reset wait counter
        if [[ $sealedPods -lt $prevSealedPods ]]; then
            SEALED_STATUS_TRIES=5
        else
            SEALED_STATUS_TRIES=$(($SEALED_STATUS_TRIES - 1))
        fi

        # wait for pods to unseal
        sleep $SEALED_STATUS_WAITTIME
        prevSealedPods=$sealedPods
    done

    # if there are still sealed pods, attempt reapply
    if $sealedExists; then
        echo "There are unsealable pods. Attempting reapply..."
        reapplyVault
        reapplyVaultRC=$?
        if [[ $reapplyVaultRC -eq 0 ]]; then
            echo "Vault reapply completed. Reattempting validation."
            continue
        else
            echo "Vault reapply failed for trying to" \
                "fix sealed vault pods." \
                "Unable to ready vault for restore."
            exit 1
        fi
    fi

    # all test passed. exit
    echo "All validation passed. Vault application is ready to be restored."
    exit 0
done

echo "All tries exhausted. Unable to ready vault for restore."
exit 1
