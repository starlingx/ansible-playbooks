#!/usr/bin/python
#
# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import ast
import sys
import json
import base64
import subprocess
from shutil import copy
from string import Template

CEPH_TMP_DIR = "/tmp/ceph"
TEMPLATES_DIR = "/usr/share/ansible/stx-ansible/playbooks/roles/recover-rook-ceph-data/files/templates"

CLUSTERROLE_TEMPLATE_FILENAME = "clusterrole.yaml.tpl"
CLUSTERROLE_BINDING_TEMPLATE_FILENAME = "clusterrolebinding.yaml.tpl"
CONFIGMAP_TEMPLATE_FILENAME = "configmap.yaml.tpl"
SERVICEACCOUNT_TEMPLATE_FILENAME = "serviceaccount.yaml.tpl"
MON_CLEANUP_JOB_TEMPLATE_FILENAME = "job-mon-cleanup.yaml.tpl"
LOG_COLLECTOR_JOB_TEMPLATE_FILENAME = "job-log-collector.yaml.tpl"
MON_ROLLBACK_JOB_TEMPLATE_FILENAME = "job-mon-rollback.yaml.tpl"
OPERATOR_JOB_TEMPLATE_FILENAME = "job-operator.yaml.tpl"
MONSTORE_REBUILD_JOB_TEMPLATE_FILENAME = "job-monstore-rebuild.yaml.tpl"
OSD_KEYRING_UPDATE_TEMPLATE_FILENAME = "job-osd-keyring-update.yaml.tpl"

CLUSTERROLE_RESOURCE_FILENAME = "clusterrole.yaml"
CLUSTERROLE_BINDING_RESOURCE_FILENAME = "clusterrolebinding.yaml"
CONFIGMAP_RESOURCE_FILENAME = "configmap.yaml"
SERVICEACCOUNT_RESOURCE_FILENAME = "serviceaccount.yaml"
MON_CLEANUP_JOB_RESOURCE_FILENAME = "job-mon-cleanup-{}.yaml"
LOG_COLLECTOR_JOB_RESOURCE_FILENAME = "job-log-collector.yaml"
MON_ROLLBACK_JOB_RESOURCE_FILENAME = "job-mon-rollback-{}.yaml"
OPERATOR_JOB_RESOURCE_FILENAME = "job-operator.yaml"
MONSTORE_REBUILD_JOB_RESOURCE_FILENAME = "job-monstore-rebuild.yaml"
OSD_KEYRING_UPDATE_JOB_RESOURCE_FILENAME = "job-osd-keyring-update-{}.yaml"

REGISTRY = "registry.local:9001"
CEPH_IMAGE = "/".join([REGISTRY, "quay.io/ceph/ceph:v18.2.5"])
CEPH_CONFIG_HELPER_IMAGE = "/".join([REGISTRY, "docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312"])

os.environ["KUBECONFIG"] = "/etc/kubernetes/admin.conf"


# TODO: Use the Kubernetes lib instead of subprocess functions.
def recover():
    # Temporarily stop the Rook Ceph operator to prevent interference during cluster recovery
    result = subprocess.run(["kubectl", "-n", "rook-ceph", "scale", "deployment", "rook-ceph-operator", "--replicas=0"])
    if result.returncode == 0:
        result = subprocess.run(["kubectl", "-n", "rook-ceph", "wait", "--for=delete", "pod", "-l", "app=rook-ceph-operator", "--timeout=30s"])
        if result.returncode != 0:
            subprocess.run(["kubectl", "-n", "rook-ceph", "delete", "pod", "-l", "app=rook-ceph-operator", "--grace-period=0", "--force"])
    else:
        print("Unable to scale rook-ceph-operator.", file=sys.stderr)
        sys.exit(result.returncode)

    hosts_data = ast.literal_eval(sys.argv[1])
    recovery_target_host = hosts_data["recovery_target_host"]
    recovery_type = hosts_data["recovery_type"]
    hosts_with_osd = hosts_data["hosts_with_osd"].split(" ")
    hosts_with_osd.remove(recovery_target_host)

    mons_to_clean = {}
    target_mon_name = None
    has_mon_float = False

    # Gets monitor data via the rook-ceph-mon-endpoint configmap
    cmd = ["kubectl", "-n", "rook-ceph", "get", "configmap",
           "rook-ceph-mon-endpoints", "-o", "jsonpath=\'{.data.mapping}\'"]
    cmd_output = subprocess.check_output(cmd).decode("UTF-8")

    # It takes the monitors and their respective hosts to be cleaned, in addition to
    # identifying the existence of the floating monitor.
    mons = json.loads(ast.literal_eval(cmd_output))
    for mon_name, data in mons["node"].items():
        hostname = data["Hostname"]
        if mon_name == "float":
            continue
        elif hostname == recovery_target_host:
            target_mon_name = mon_name
        elif not target_mon_name and recovery_type == "OSD_ONLY":
            target_mon_name = mon_name
        mons_to_clean[mon_name] = hostname

    target_mon_hostname = mons_to_clean.pop(target_mon_name)

    # Check if there is a floating monitor
    result = subprocess.run(["kubectl", "-n", "rook-ceph", "get", "deployment", "rook-ceph-mon-float"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        has_mon_float = True
    elif "not found" not in result.stderr:
        print("Unexpected error while checking floating monitor.", file=sys.stderr)
        sys.exit(result.returncode)

    # Read the configmap.bin that was in the backup to be stored in the rook-ceph-recovery configmap.
    monmap_path = os.path.join(CEPH_TMP_DIR, "monmap.bin")
    if os.path.exists(monmap_path):
        with open(monmap_path, "rb") as monmap_file:
            monmap_b64 = base64.b64encode(monmap_file.read()).decode()
    else:
        print("monmap.bin file not found.", file=sys.stderr)
        sys.exit(1)

    copy_and_apply_k8s_resource(CLUSTERROLE_TEMPLATE_FILENAME, CLUSTERROLE_RESOURCE_FILENAME)
    copy_and_apply_k8s_resource(CLUSTERROLE_BINDING_TEMPLATE_FILENAME, CLUSTERROLE_BINDING_RESOURCE_FILENAME)
    copy_and_apply_k8s_resource(CONFIGMAP_TEMPLATE_FILENAME, CONFIGMAP_RESOURCE_FILENAME)
    copy_and_apply_k8s_resource(SERVICEACCOUNT_TEMPLATE_FILENAME, SERVICEACCOUNT_RESOURCE_FILENAME)

    has_mon_float_str = str(has_mon_float).lower()
    has_osd_keyring_update_job_str = str(len(hosts_with_osd) > 0).lower()

    operator_job_template = get_template(OPERATOR_JOB_TEMPLATE_FILENAME)
    operator_job_resource = operator_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                   "TARGET_HOSTNAME": recovery_target_host,
                                                                   "RECOVERY_TYPE": recovery_type,
                                                                   "HAS_MON_FLOAT": has_mon_float_str,
                                                                   "HAS_OSD_KEYRING_UPDATE": has_osd_keyring_update_job_str})
    create_and_apply_k8s_resource(operator_job_resource, OPERATOR_JOB_RESOURCE_FILENAME)

    monstore_rebuild_job_template = get_template(MONSTORE_REBUILD_JOB_TEMPLATE_FILENAME)
    monstore_rebuild_job_resource = monstore_rebuild_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                                   "CEPH_IMAGE": CEPH_IMAGE,
                                                                                   "TARGET_HOSTNAME": recovery_target_host,
                                                                                   "RECOVERY_TYPE": recovery_type,
                                                                                   "TARGET_MON_HOSTNAME": target_mon_hostname,
                                                                                   "TARGET_MON_NAME": target_mon_name,
                                                                                   "HAS_MON_FLOAT": has_mon_float_str,
                                                                                   "HAS_OSD_KEYRING_UPDATE": has_osd_keyring_update_job_str,
                                                                                   "MONMAP_BINARY": monmap_b64})
    create_and_apply_k8s_resource(monstore_rebuild_job_resource, MONSTORE_REBUILD_JOB_RESOURCE_FILENAME)

    log_collector_job_template = get_template(LOG_COLLECTOR_JOB_TEMPLATE_FILENAME)
    log_collector_job_resource = log_collector_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                             "TARGET_HOSTNAME": recovery_target_host})
    create_and_apply_k8s_resource(log_collector_job_resource, LOG_COLLECTOR_JOB_RESOURCE_FILENAME)

    if recovery_type != "SINGLE_HOST":
        for target_host in hosts_with_osd:
            osd_keyring_update_job_template = get_template(OSD_KEYRING_UPDATE_TEMPLATE_FILENAME)
            osd_keyring_update_job_resource = osd_keyring_update_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                                               "CEPH_IMAGE": CEPH_IMAGE,
                                                                                               "TARGET_HOSTNAME": target_host})
            create_and_apply_k8s_resource(osd_keyring_update_job_resource,
                                          OSD_KEYRING_UPDATE_JOB_RESOURCE_FILENAME.format(target_host))

        for mon_name, target_host in mons_to_clean.items():
            mon_cleanup_job_template = get_template(MON_CLEANUP_JOB_TEMPLATE_FILENAME)
            mon_cleanup_job_resource = mon_cleanup_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                                 "TARGET_HOSTNAME": target_host,
                                                                                 "TARGET_MON_NAME": mon_name,
                                                                                 "HAS_MON_FLOAT": has_mon_float_str})
            create_and_apply_k8s_resource(mon_cleanup_job_resource,
                                          MON_CLEANUP_JOB_RESOURCE_FILENAME.format(mon_name))

        if recovery_type == "OSD_ONLY":
            mon_rollback_job_template = get_template(MON_ROLLBACK_JOB_TEMPLATE_FILENAME)
            mon_rollback_job_resource = mon_rollback_job_template.safe_substitute({"CEPH_CONFIG_HELPER_IMAGE": CEPH_CONFIG_HELPER_IMAGE,
                                                                                   "TARGET_HOSTNAME": target_mon_hostname,
                                                                                   "TARGET_MON_NAME": target_mon_name,
                                                                                   "TARGET_RECOVERY_HOSTNAME": recovery_target_host})
            create_and_apply_k8s_resource(mon_rollback_job_resource,
                                          MON_ROLLBACK_JOB_RESOURCE_FILENAME.format(target_mon_name))

    # If the recovery target host is controller-0, it means the playbook is running, so we need to wait for the process to complete.
    if recovery_target_host == "controller-0":
        # When it is SINGLE_HOST, the operator job needs to be completed.
        job_label = "rook-ceph-recovery-operator"
        # When it is OSD_AND_MON or OSD_ONLY, wait for the monstore to rebuild, which is the job to be done in this first step.
        if recovery_type != "SINGLE_HOST":
            job_label = "rook-ceph-recovery-monstore-rebuild"
        result = subprocess.run(["kubectl", "wait", "--for=condition=complete", "job", "--all=true",
                                 "-n", "rook-ceph", "-l", f"app={job_label}", "--timeout=30m"])
        # Check if there were any failures during the recovery process.
        check_failure()
        sys.exit(result.returncode)


def get_rook_ceph_recovery_data(name):
    cmd = ["kubectl", "-n", "rook-ceph", "get", "configmap", "rook-ceph-recovery",
           "-o", f"jsonpath='{{.data.{name}}}'", "--request-timeout=30s"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Unexpected error while getting data from rook-ceph-recovery configmap.", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.replace("'", "")


def check_failure():
    status = get_rook_ceph_recovery_data("status")
    print(f"status={status}")
    if status == "recovery-failed":
        failure = get_rook_ceph_recovery_data("failure")
        print(failure, file=sys.stderr)
        sys.exit(1)


def apply_k8s_resource(resource):
    result = subprocess.run(["kubectl", "apply", "-f", resource])
    if result.returncode != 0:
        print("Unexpected error while applying k8s resources.", file=sys.stderr)
        sys.exit(result.returncode)


def create_and_apply_k8s_resource(content, filename):
    output_path = os.path.join(CEPH_TMP_DIR, filename)
    output_file = open(output_path, "w")
    output_file.write(content)
    output_file.close()
    apply_k8s_resource(output_path)


def copy_and_apply_k8s_resource(src_filename, dst_filename):
    src_path = os.path.join(TEMPLATES_DIR, src_filename)
    dst_path = os.path.join(CEPH_TMP_DIR, dst_filename)
    copy(src_path, dst_path)
    apply_k8s_resource(dst_path)


# TODO: Use Jinja2 instead of Template?
def get_template(file_name):
    file_path = os.path.join(TEMPLATES_DIR, file_name)
    with open(file_path, "r") as file:
        return Template(file.read())


if __name__ == "__main__":
    try:
        recover()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
