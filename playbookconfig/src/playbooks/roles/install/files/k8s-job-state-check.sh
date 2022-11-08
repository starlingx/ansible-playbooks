#!/bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to check the k8s job state within a period of time.
#

JOB_NAME=$1
NAMESPACE=$2
JOB_WAIT_TIME=$3

KUBE_CONFIG="/etc/kubernetes/admin.conf"

# Check state every 2 seconds
CHECK_INTERVAL=2

# Results to be returned
TIME_OUT="timeout"
NOT_FOUND="not found"
COMPLETE_STATE="complete"
FAILED_STATE="failed"

wait_period=0
while [ ${wait_period} -lt ${JOB_WAIT_TIME} ]; do
    if ! $(kubectl --kubeconfig=${KUBE_CONFIG} -n ${NAMESPACE} get \
        job/${JOB_NAME} >/dev/null 2>&1); then
        echo -ne ${NOT_FOUND}
        exit 0
    fi

    if kubectl --kubeconfig=${KUBE_CONFIG} -n ${NAMESPACE} wait \
        --for=condition=${COMPLETE_STATE} --timeout=0 job/${JOB_NAME} \
            >/dev/null 2>&1; then
        echo -ne ${COMPLETE_STATE}
        exit 0
    fi

    if kubectl --kubeconfig=${KUBE_CONFIG} -n ${NAMESPACE} wait \
        --for=condition=${FAILED_STATE} --timeout=0 job/${JOB_NAME} \
            >/dev/null 2>&1; then
        echo -ne ${FAILED_STATE}
        exit 0
    fi

    sleep ${CHECK_INTERVAL}
    wait_period=$((${wait_period}+${CHECK_INTERVAL}))
done

echo -ne ${TIME_OUT}
exit 1

