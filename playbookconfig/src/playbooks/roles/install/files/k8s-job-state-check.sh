#!/bin/bash
#
# Copyright (c) 2022-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to check the existence and state of a Kubernetes job
# within a specified time period. The script's standard output will indicate
# one of the following results: "timeout", "not found", "complete", or "failed".
# The script exits with the status code 1 only when "timeout" occurs, while
# for other results, it exits with status code 0. The "failed" result code
# is utilized by the `apply-rvmc-job` role in the installation playbook to
# determine whether a retry is needed.

JOB_NAME=$1
NAMESPACE=$2
JOB_WAIT_TIME=$3

KUBE_CONFIG="/etc/kubernetes/admin.conf"

# The amount of time checking the existence/state of the job
JOB_EXISTENCE_MAX_WAIT=10
JOB_STATE_MAX_WAIT=$(($JOB_WAIT_TIME-$JOB_EXISTENCE_MAX_WAIT))

# Sleep time
CHECK_JOB_EXISTENCE_INTERVAL=1
CHECK_JOB_STATE_INTERVAL=2

# Results to be returned
TIME_OUT="timeout"
NOT_FOUND="not found"
COMPLETE_STATE="complete"
FAILED_STATE="failed"

# The first step: ensure the existence of the job
elapsed_seconds=0
job_exists=0
while [ ${elapsed_seconds} -lt ${JOB_EXISTENCE_MAX_WAIT} ]; do
    if kubectl --kubeconfig=${KUBE_CONFIG} -n ${NAMESPACE} \
        get job/${JOB_NAME} >/dev/null 2>&1; then
        job_exists=1
        break
    fi

    sleep ${CHECK_JOB_EXISTENCE_INTERVAL}
    $((elapsed_seconds+=CHECK_JOB_EXISTENCE_INTERVAL))
done

if [ ${job_exists} -eq 0 ]; then
    echo -ne ${NOT_FOUND}
    exit 0
fi

# Then checking the state of the job
elapsed_seconds=0
while [ ${elapsed_seconds} -lt ${JOB_STATE_MAX_WAIT} ]; do
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

    if ! $(kubectl --kubeconfig=${KUBE_CONFIG} -n ${NAMESPACE} \
        get job/${JOB_NAME} >/dev/null 2>&1); then
        echo -ne ${NOT_FOUND}
        exit 0
    fi

    sleep ${CHECK_JOB_STATE_INTERVAL}
    $((elapsed_seconds+=CHECK_JOB_STATE_INTERVAL))
done

# Return timeout if above job state conditions were not met
echo -ne ${TIME_OUT}
exit 1

