#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import ast
import sys
import json
import base64
import subprocess
from string import Template

CEPH_TMP = '/tmp/ceph'
MONMAP_FILENAME = 'monmap.bin'
RECOVERY_JOB_RESOURCE_FILENAME = 'recovery-job.yaml'
KEYRING_JOB_RESOURCE_FILENAME = 'keyring-update-{}-job.yaml'
MOVE_MON_JOB_RESOURCE_FILENAME = 'move-mon-{}-job.yaml'
CLEAN_MON_JOB_RESOURCE_FILENAME = 'clean-mon-{}-job.yaml'
MONITOR_JOB_RESOURCE_FILENAME = 'monitor-job.yaml'
KUBE_CONFIG_FILENAME = "/etc/kubernetes/admin.conf"

os.environ["KUBECONFIG"] = KUBE_CONFIG_FILENAME


def recover_cluster():
    if not os.path.exists(CEPH_TMP):
        os.mkdir(CEPH_TMP, 0o751)

    hosts_data = ast.literal_eval(sys.argv[1])
    target_hostname = hosts_data['target_hostname']
    structure = hosts_data['structure']
    hosts_to_update_keyring = hosts_data['hosts_with_osd'].split(' ')
    hosts_to_update_keyring.remove(target_hostname)

    target_mon = None
    mon_float = "false"
    mons_to_clean = {}

    cmd = ["kubectl", "-n", "rook-ceph", "get", "configmap",
           "rook-ceph-mon-endpoints", "-o", "jsonpath=\'{.data.mapping}\'"]
    with open(os.devnull, "w") as fnull:
        cmd_output = subprocess.check_output(cmd, stderr=fnull).decode('UTF-8')

    mons = json.loads(ast.literal_eval(cmd_output))
    for name, data in mons['node'].items():
        hostname = data['Hostname']

        if name == "float":
            mon_float = "true"
        elif hostname == target_hostname:
            target_mon = name
        elif structure == "ONLY_OSD" and not target_mon:
            target_mon = name

        mons_to_clean[name] = hostname

    target_mon_hostname = mons_to_clean.pop(target_mon)

    if mon_float == "false":
        cmd = ["kubectl", "-n", "rook-ceph", "get", "pod",
               "-l", "mon=float", "-o", "custom-columns=:spec.nodeName"]
        with open(os.devnull, "w") as fnull:
            hostname = subprocess.check_output(cmd, stderr=fnull).decode('UTF-8').strip()

        if hostname:
            mons_to_clean['float'] = hostname
            mon_float = "true"

    with open(os.path.join(CEPH_TMP, MONMAP_FILENAME), "rb") as monmap_file:
        monmap_b64 = base64.b64encode(monmap_file.read()).decode()

    recovery_job_template = get_recovery_job_template()
    recovery_job_resource = recovery_job_template.safe_substitute({'STRUCTURE': structure,
                                                                   'TARGET_HOSTNAME': target_hostname,
                                                                   'TARGET_MON': target_mon,
                                                                   'MON_FLOAT_ENABLED': mon_float,
                                                                   'MONMAP_BINARY': monmap_b64})
    recovery_job_resource_path = create_job_resource(recovery_job_resource, RECOVERY_JOB_RESOURCE_FILENAME)

    subprocess.run(["kubectl", "apply", "-f", recovery_job_resource_path])
    if target_hostname == "controller-0":
        subprocess.run(["kubectl", "wait", "--for=condition=complete", "job", "--all=true",
                        "-n", "rook-ceph", "-l", "app=rook-ceph-recovery", "--timeout=30m"])

    if structure != "ONE_HOST":
        subprocess.run(["kubectl", "label", "deployment", "-n", "rook-ceph",
                        "-l", "app=rook-ceph-mon", "ceph.rook.io/do-not-reconcile="])

        if structure == "ONLY_OSD":
            move_mon_job_template = get_move_mon_job_template()
            move_mon_job_resource = move_mon_job_template.safe_substitute({'TARGET_HOSTNAME': target_mon_hostname,
                                                                           'TARGET_MON': target_mon})
            move_mon_job_resource_path = create_job_resource(move_mon_job_resource,
                                                             MOVE_MON_JOB_RESOURCE_FILENAME.format(target_mon))
            subprocess.run(["kubectl", "apply", "-f", move_mon_job_resource_path])

        for hostname in hosts_to_update_keyring:
            keyring_job_template = get_keyring_job_template()
            keyring_job_resource = keyring_job_template.safe_substitute({'TARGET_HOSTNAME': hostname})
            keyring_job_resource_path = create_job_resource(keyring_job_resource,
                                                            KEYRING_JOB_RESOURCE_FILENAME.format(hostname))
            subprocess.run(["kubectl", "apply", "-f", keyring_job_resource_path])

        for name, hostname in mons_to_clean.items():
            clean_mon_job_template = get_clean_mon_job_template()
            clean_mon_job_resource = clean_mon_job_template.safe_substitute({'TARGET_HOSTNAME': hostname,
                                                                             'TARGET_MON': name})
            clean_mon_job_resource_path = create_job_resource(clean_mon_job_resource,
                                                              CLEAN_MON_JOB_RESOURCE_FILENAME.format(name))
            subprocess.run(["kubectl", "apply", "-f", clean_mon_job_resource_path])

        monitor_job_template = get_monitor_job_template()
        monitor_job_resource = monitor_job_template.safe_substitute({'MON_FLOAT_ENABLED': mon_float})
        monitor_job_resource_path = create_job_resource(monitor_job_resource,
                                                        MONITOR_JOB_RESOURCE_FILENAME)
        subprocess.run(["kubectl", "apply", "-f", monitor_job_resource_path])


def create_job_resource(content, filename):
    output_path = os.path.join(CEPH_TMP, filename)
    output_file = open(output_path, 'w')
    output_file.write(content)
    output_file.close()
    return output_path


def get_recovery_job_template():
    return Template(
        """
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: rook-ceph-recovery
  namespace: rook-ceph

data:
  recover.sh: |-
    #!/bin/bash

    set -x

    TIME_AFTER_SCALE=$([ "$STRUCT" == "ONE_HOST" ] && echo "0s" || echo "10s")
    TIME_WAIT_DELETE=$([ "$STRUCT" == "ONE_HOST" ] && echo "0s" || echo "30s")
    TIME_WAIT_READY=$([ "$STRUCT" == "ONE_HOST" ] && echo "0s" || echo "60s")
    TIME_RETRY=$([ "$STRUCT" == "ONE_HOST" ] && echo "0s" || echo "5s")

    if [ "${MON_HOST}"x == ""x ]; then
        MON_HOST=$(echo ${ROOK_MONS} | sed 's/[a-z]\\+=//g')
    fi

    cat > /etc/ceph/ceph.conf << EOF
    [global]
    mon_host = ${MON_HOST}
    EOF

    admin_keyring=$(echo ${ADMIN_KEYRING} | cut -f4 -d' ')
    cat >  /etc/ceph/ceph.client.admin.keyring << EOF
    [client.admin]
    key = $admin_keyring
    EOF

    kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"status": "running"}}'
    if [ $? -ne 0 ]; then
      echo "unexpected kubernetes error, exit"
      exit 1
    fi

    if [ $STRUCT != 'ONE_HOST' ]; then
      kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-operator --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-operator --grace-period=0 --force
      fi

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mon --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-mon --grace-period=0 --force
      fi

      DATA_MON_ENDPOINTS=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_endpoints}')
      if [ -z "${DATA_MON_ENDPOINTS}" ]; then
        DATA_MON_ENDPOINTS=$(kubectl -n rook-ceph get configmap rook-ceph-mon-endpoints -o jsonpath='{.data.data}')
        kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_endpoints": "'"${DATA_MON_ENDPOINTS}"'"}}'
      fi

      DATA_MON_HOST=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_host}')
      if [ -z "${DATA_MON_HOST}" ]; then
        DATA_MON_HOST=$(kubectl -n rook-ceph get secret rook-ceph-config -o jsonpath='{.data.mon_host}')
        kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_host": "'"${DATA_MON_HOST}"'"}}'
      fi

      DATA_MON_INIT=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_initial_members}')
      if [ -z "${DATA_MON_INIT}" ]; then
        DATA_MON_INIT=$(kubectl -n rook-ceph get secret rook-ceph-config -o jsonpath='{.data.mon_initial_members}')
        kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_initial_members": "'"${DATA_MON_INIT}"'"}}'
      fi

      mon_host_addr=$(kubectl -n rook-ceph get service rook-ceph-mon-${MON_NAME} -o jsonpath='{.spec.clusterIP}')

      kubectl -n rook-ceph patch configmap rook-ceph-mon-endpoints -p '{"data": {"data": "'"${MON_NAME}"'='"${mon_host_addr}"':6789"}}'
      kubectl -n rook-ceph patch secret rook-ceph-config -p '{"stringData": {"mon_host": "[v2:'"${mon_host_addr}"':3300,v1:'"${mon_host_addr}"':6789]", "mon_initial_members": "'"${MON_NAME}"'"}}'

      kubectl -n rook-ceph label deployment -l app=rook-ceph-mon ceph.rook.io/do-not-reconcile=""

      if [ $STRUCT == 'ONLY_OSD' ]; then
        kubectl label nodes ${HOSTNAME} ceph-mgr-placement=enabled
        kubectl label nodes ${HOSTNAME} ceph-mon-placement=enabled
        kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
      fi

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 1
      kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-mon --timeout=${TIME_WAIT_READY}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-operator --timeout=${TIME_WAIT_READY}
    fi

    ceph -s
    if [ $? -ne 0 ]; then
      echo "ceph timeout exceeded, exit"
      exit 1
    fi

    if [ $STRUCT == 'ONLY_OSD' ]; then
      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mgr --replicas 0
      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 0

      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mgr --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-mgr --grace-period=0 --force
      fi

      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mds --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-mds --grace-period=0 --force
      fi

      SECRETS=$(kubectl -n rook-ceph get secrets -o custom-columns=:metadata.name)

      for secret in $(echo "$SECRETS" | grep "rook-ceph-mgr\\|rook-ceph-mds"); do
        keyring="/tmp/${secret}"
        kubectl -n rook-ceph get secret "${secret}" -o jsonpath='{.data.keyring}' | base64 -d > ${keyring}
        ceph auth import -i $keyring
      done

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mgr --replicas 1
      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-mgr --timeout=${TIME_WAIT_READY}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-mds --timeout=${TIME_WAIT_READY}
    fi

    kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 0
    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-operator --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-operator --grace-period=0 --force
    fi

    rm -rf /tmp/monstore
    mkdir -p /tmp/monstore

    while [ ! -f /tmp/ceph/osd_data ]
    do
      sleep ${TIME_RETRY}
    done

    OWN_OSDS=()

    for row in $(cat /tmp/ceph/osd_data | jq -r '.[] | @base64'); do
      _jq() {
        echo "${row}" | base64 -di | jq -r "${1}"
      }
      ceph_fsid=$(_jq '.ceph_fsid')
      osd_id=$(_jq '.osd_id')
      osd_uuid=$(_jq '.osd_uuid')

      OWN_OSDS+=($osd_id)

      while [ ! -f /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring ]
      do
        sleep ${TIME_RETRY}
      done

      kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l osd=${osd_id} --grace-period=0 --force
      fi

      NEW_OSD_KEYRING=(`cat /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring | sed -n -e 's/^.*key = //p'`)
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${NEW_OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      ceph auth import -i /tmp/osd.${osd_id}.keyring
      if [ $? -ne 0 ]; then
        echo "ceph timeout exceeded, exit"
        exit 1
      fi

      ceph-objectstore-tool --type bluestore --data-path /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid} --op update-mon-db --mon-store-path /tmp/monstore
      if [ $? -ne 0 ]; then
        echo "Error updating mon db, exit"
        exit 1
      fi

      kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_READY}
    done

    if [ -z "$OWN_OSDS" ]; then
      echo "no osd found, exit"
      exit 1
    fi

    ceph auth export -o /tmp/export.keyring
    if [ $? -ne 0 ]; then
      echo "ceph timeout exceeded, exit"
      exit 1
    fi

    if [ ! -f /tmp/ceph/monmap.bin ]; then
      echo "monmap.bin not found in /tmp/ceph.. Getting from rook-ceph-recovery configmap."
      kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.monmap_b64}' | base64 -d > /tmp/ceph/monmap.bin
      if [ $? -ne 0 ]; then
        echo "Error getting monmap from configmap, exit"
        exit 1
      fi
    fi

    ceph-monstore-tool /tmp/monstore rebuild -- --keyring /tmp/export.keyring --monmap /tmp/ceph/monmap.bin
    if [ $? -ne 0 ]; then
      echo "Error rebuilding monstore, exit"
      exit 1
    fi

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 0
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 0

    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mon --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-mon --grace-period=0 --force
    fi

    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-osd --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-osd --grace-period=0 --force
    fi

    rm -rf /var/lib/rook/mon-${MON_NAME}/data/store.db
    cp -ar /tmp/monstore/store.db /var/lib/rook/mon-${MON_NAME}/data

    kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 1
    sleep ${TIME_AFTER_SCALE}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=${TIME_WAIT_READY}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-osd --timeout=${TIME_WAIT_READY}

    ceph -s
    if [ $? -ne 0 ]; then
      echo "ceph timeout exceeded, exit"
      exit 1
    fi

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 0
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mgr --replicas 0

    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mds --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-mds --grace-period=0 --force
    fi

    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mgr --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-mgr --grace-period=0 --force
    fi

    FS_NAME=kube-cephfs
    DATA_POOL_NAME=kube-cephfs-data
    METADATA_POOL_NAME=kube-cephfs-metadata

    # Check if the filesystem for the system RWX provisioner is present
    ceph fs ls | grep ${FS_NAME}
    if [ $? -ne 0 ]; then

        for osd_id in $(ceph osd ls); do
          if ! [[ ${OWN_OSDS[*]} =~ "$osd_id" ]]; then
              kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 0
              kubectl -n rook-ceph wait --for=delete pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_DELETE}
              if [ $? -ne 0 ]; then
                kubectl -n rook-ceph delete pod -l osd=${osd_id} --grace-period=0 --force
              fi
              ceph osd down $osd_id
          fi
        done

        # Use existing metadata/data pools to recover cephfs
        ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME} --force

        # Recover MDS state from filesystem
        ceph fs reset ${FS_NAME} --yes-i-really-mean-it

        # Try to recover from some common errors
        cephfs-journal-tool --rank=${FS_NAME}:0 event recover_dentries summary
        cephfs-journal-tool --rank=${FS_NAME}:0 journal reset
        cephfs-table-tool ${FS_NAME}:0 reset session
        cephfs-table-tool ${FS_NAME}:0 reset snap
        cephfs-table-tool ${FS_NAME}:0 reset inode
    fi

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 1
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 1
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mgr --replicas 1
    kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 1

    if [ $STRUCT != 'ONE_HOST' ]; then
      until ceph osd pool stats; do
        echo "Waiting for cluster recovery"
      done

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mon --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-mon --grace-period=0 --force
      fi

      kubectl -n rook-ceph patch configmap rook-ceph-mon-endpoints -p '{"data": {"data": "'"${DATA_MON_ENDPOINTS}"'"}}'
      kubectl -n rook-ceph patch secret rook-ceph-config -p '{"data": {"mon_host": "'"${DATA_MON_HOST}"'"}}'
      kubectl -n rook-ceph patch secret rook-ceph-config -p '{"data": {"mon_initial_members": "'"${DATA_MON_INIT}"'"}}'

      kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=${TIME_WAIT_READY}
    fi

    kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"status": "completed"}}'

    exit 0

  update_keyring.sh: |-
    #!/bin/bash

    set -x

    while true
    do
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        break
      else
        sleep 10
      fi
    done

    if [ "${MON_HOST}"x == ""x ]; then
        MON_HOST=$(echo ${ROOK_MONS} | sed 's/[a-z]\\+=//g')
    fi

    cat > /etc/ceph/ceph.conf << EOF
    [global]
    mon_host = ${MON_HOST}
    EOF

    admin_keyring=$(echo ${ADMIN_KEYRING} | cut -f4 -d' ')
    cat >  /etc/ceph/ceph.client.admin.keyring << EOF
    [client.admin]
    key = $admin_keyring
    EOF

    while [ ! -f /tmp/ceph/osd_data ]
    do
      sleep 5
    done

    until ceph -s; do
      sleep 60
    done

    for row in $(cat /tmp/ceph/osd_data | jq -r '.[] | @base64'); do
      _jq() {
        echo "${row}" | base64 -di | jq -r "${1}"
      }
      ceph_fsid=$(_jq '.ceph_fsid')
      osd_id=$(_jq '.osd_id')
      osd_uuid=$(_jq '.osd_uuid')

      while [ ! -f /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring ]
      do
        sleep 5
      done

      until ceph -s; do
        sleep 60
      done

      NEW_OSD_KEYRING=(`cat /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring | sed -n -e 's/^.*key = //p'`)
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${NEW_OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      until ceph -s; do
        sleep 60
      done

      ceph auth import -i /tmp/osd.${osd_id}.keyring
      if [ $? -ne 0 ]; then
        echo "ceph timeout exceeded, exit"
        exit 1
      fi
    done

    exit 0

  clean_mon.sh: |-
    #!/bin/bash

    set -x

    if [ ${MON_NAME} == "float" ]; then
      data_dir"/var/lib/rook/mon-${MON_NAME}/mon-${MON_NAME}"
    else
      data_dir="/var/lib/rook/data/mon-${MON_NAME}"
    fi

    while true
    do
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 0
        kubectl -n rook-ceph wait --for=delete pod --all=true -l mon=${MON_NAME} --timeout=30s
        if [ $? -ne 0 ]; then
          kubectl -n rook-ceph delete pod -l mon=${MON_NAME} --grace-period=0 --force
        fi

        rm -rf $data_dir

        kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1

        break
      else
        sleep 10
      fi
    done

    exit 0

  move_mon.sh: |-
    #!/bin/bash

    set -x

    if [ "${MON_HOST}"x == ""x ]; then
        MON_HOST=$(echo ${ROOK_MONS} | sed 's/[a-z]\\+=//g')
    fi

    cat > /etc/ceph/ceph.conf << EOF
    [global]
    mon_host = ${MON_HOST}
    EOF

    admin_keyring=$(echo ${ADMIN_KEYRING} | cut -f4 -d' ')
    cat >  /etc/ceph/ceph.client.admin.keyring << EOF
    [client.admin]
    key = $admin_keyring
    EOF

    while true
    do
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        if [ "$(ceph health)" == "HEALTH_OK" ]; then
          PODS=$(kubectl -n rook-ceph get pods -l app=rook-ceph-clean-mon)
          if echo "$PODS" | grep rook-ceph-clean; then
            kubectl -n rook-ceph wait --for=condition=complete job --all=true -l app=rook-ceph-clean-mon --timeout=30s
            if [ $? -ne 0 ]; then
                continue
            fi
          fi

          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 0
          kubectl -n rook-ceph wait --for=delete pod --all=true -l mon=${MON_NAME} --timeout=30s
          if [ $? -ne 0 ]; then
            kubectl -n rook-ceph delete pod -l mon=${MON_NAME} --grace-period=0 --force
          fi

          rm -rf /var/lib/rook/mon-${MON_NAME}

          kubectl -n rook-ceph label deployment -l app=rook-ceph-mon ceph.rook.io/do-not-reconcile=""

          kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
          kubectl label nodes ${HOSTNAME} ceph-mgr-placement-
          kubectl label nodes ${HOSTNAME} ceph-mon-placement-

          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
          sleep 10
          kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=60s

          echo "rook-ceph mon moved successfully."
          break
        fi
      fi
      sleep 30
    done

    exit 0

  monitor.sh: |-
    #!/bin/bash

    set -x

    while true
    do
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        kubectl -n rook-ceph wait --for=condition=complete job --all=true -l app.kubernetes.io/part-of=rook-ceph-recovery --timeout=30s
        if [ $? -eq 0 ]; then
          if [ "${HAS_MON_FLOAT}" == false ]; then
            kubectl -n rook-ceph label deployment -l app=rook-ceph-mon ceph.rook.io/do-not-reconcile-
          fi
          break
        fi
      else
        sleep 5m
      fi
    done

    kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery
    kubectl -n rook-ceph wait --for=delete job --all=true -l app.kubernetes.io/part-of=rook-ceph-recovery --timeout=30s
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery --grace-period=0 --force
    fi

    exit 0

  monmap_b64: |-
    $MONMAP_BINARY

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: rook-ceph-recovery
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["list", "get", "watch", "delete"]
- apiGroups: [""]
  resources: ["services"]
  verbs: ["get"]
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "patch"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["list", "get", "patch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["list", "get", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["list", "patch", "get"]
- apiGroups: ["apps"]
  resources: ["deployments/scale"]
  verbs: ["patch"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["list", "watch", "get", "delete"]
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rook-ceph-recovery
  namespace: rook-ceph
imagePullSecrets:
  - name: default-registry-key
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: rook-ceph-recovery
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: rook-ceph-recovery
subjects:
- kind: ServiceAccount
  name:  rook-ceph-recovery
  namespace: rook-ceph
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery
  namespace: rook-ceph
  labels:
   app: rook-ceph-recovery
   app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery
      namespace: rook-ceph
    spec:
      serviceAccountName: rook-ceph-recovery
      nodeSelector:
        kubernetes.io/hostname: $TARGET_HOSTNAME
      tolerations:
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/master
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/control-plane
      restartPolicy: OnFailure
      volumes:
        - hostPath:
            path: /var/lib/ceph/data
            type: ""
          name: rook-data
        - hostPath:
            path: /dev
            type: ""
          name: devices
        - hostPath:
            path: /run/udev
            type: ""
          name: run-udev
        - hostPath:
            path: /tmp/ceph
            type: ""
          name: tmp
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      initContainers:
        - name: osd-data
          image: registry.local:9001/quay.io/ceph/ceph:v18.2.2
          command: [ "/bin/bash", "-c", "/usr/sbin/ceph-volume raw list > /tmp/ceph/osd_data" ]
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /dev
            name: devices
          - mountPath: /run/udev
            name: run-udev
          - mountPath: /tmp/ceph
            name: tmp
      containers:
        - name: recovery
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/recover.sh" ]
          env:
          - name: ROOK_MONS
            valueFrom:
              configMapKeyRef:
                key: data
                name: rook-ceph-mon-endpoints
          - name: ADMIN_KEYRING
            valueFrom:
              secretKeyRef:
                name: rook-ceph-admin-keyring
                key: keyring
          - name: STRUCT
            value: $STRUCTURE
          - name: HOSTNAME
            value: $TARGET_HOSTNAME
          - name: MON_NAME
            value: $TARGET_MON
          - name: HAS_MON_FLOAT
            value: "$MON_FLOAT_ENABLED"
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /dev
            name: devices
          - mountPath: /run/udev
            name: run-udev
          - mountPath: /tmp/ceph
            name: tmp
          - mountPath: /tmp/mount
            name: rook-ceph-recovery
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
        """)


def get_keyring_job_template():
    return Template(
        """
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-keyring-update-$TARGET_HOSTNAME
  namespace: rook-ceph
  labels:
   app: rook-ceph-keyring-update
   app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-keyring-update-$TARGET_HOSTNAME
      namespace: rook-ceph
    spec:
      serviceAccountName: rook-ceph-recovery
      nodeSelector:
        kubernetes.io/hostname: $TARGET_HOSTNAME
      tolerations:
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/master
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/control-plane
      restartPolicy: OnFailure
      volumes:
        - hostPath:
            path: /var/lib/ceph/data
            type: ""
          name: rook-data
        - hostPath:
            path: /tmp/ceph
            type: ""
          name: tmp
        - hostPath:
            path: /dev
            type: ""
          name: devices
        - hostPath:
            path: /run/udev
            type: ""
          name: run-udev
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      initContainers:
        - name: osd-data
          image: registry.local:9001/quay.io/ceph/ceph:v18.2.2
          command: [ "/bin/bash", "-c", "/usr/sbin/ceph-volume raw list > /tmp/ceph/osd_data" ]
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /tmp/ceph
            name: tmp
          - mountPath: /dev
            name: devices
          - mountPath: /run/udev
            name: run-udev
      containers:
        - name: update
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/update_keyring.sh" ]
          env:
          - name: ROOK_MONS
            valueFrom:
              configMapKeyRef:
                key: data
                name: rook-ceph-mon-endpoints
          - name: ADMIN_KEYRING
            valueFrom:
              secretKeyRef:
                name: rook-ceph-admin-keyring
                key: keyring
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /tmp/ceph
            name: tmp
          - mountPath: /dev
            name: devices
          - mountPath: /run/udev
            name: run-udev
          - mountPath: /tmp/mount
            name: rook-ceph-recovery
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
        """)


def get_clean_mon_job_template():
    return Template(
        """
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-clean-mon-$TARGET_MON
  namespace: rook-ceph
  labels:
   app: rook-ceph-clean-mon
   app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-clean-mon-$TARGET_MON
      namespace: rook-ceph
    spec:
      serviceAccountName: rook-ceph-recovery
      nodeSelector:
        kubernetes.io/hostname: $TARGET_HOSTNAME
      tolerations:
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/master
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/control-plane
      restartPolicy: OnFailure
      volumes:
        - hostPath:
            path: /var/lib/ceph
            type: ""
          name: rook-data
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      containers:
        - name: clean
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/clean_mon.sh" ]
          env:
          - name: MON_NAME
            value: $TARGET_MON
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /tmp/mount
            name: rook-ceph-recovery
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
        """)


def get_move_mon_job_template():
    return Template(
        """
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-move-mon-$TARGET_MON
  namespace: rook-ceph
  labels:
   app: rook-ceph-move-mon
   app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-move-mon-$TARGET_MON
      namespace: rook-ceph
    spec:
      serviceAccountName: rook-ceph-recovery
      nodeSelector:
        kubernetes.io/hostname: $TARGET_HOSTNAME
      tolerations:
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/master
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/control-plane
      restartPolicy: OnFailure
      volumes:
        - hostPath:
            path: /var/lib/ceph/data
            type: ""
          name: rook-data
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      containers:
        - name: update
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/move_mon.sh" ]
          env:
          - name: ROOK_MONS
            valueFrom:
              configMapKeyRef:
                key: data
                name: rook-ceph-mon-endpoints
          - name: ADMIN_KEYRING
            valueFrom:
              secretKeyRef:
                name: rook-ceph-admin-keyring
                key: keyring
          - name: HOSTNAME
            value: $TARGET_HOSTNAME
          - name: MON_NAME
            value: $TARGET_MON
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /tmp/mount
            name: rook-ceph-recovery
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
        """)


def get_monitor_job_template():
    return Template(
        """
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-monitor
  namespace: rook-ceph
  labels:
   app: rook-ceph-recovery-monitor
spec:
  ttlSecondsAfterFinished: 300
  template:
    metadata:
      name: rook-ceph-recovery-monitor
      namespace: rook-ceph
    spec:
      serviceAccountName: rook-ceph-recovery
      tolerations:
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/master
      - effect: NoSchedule
        operator: Exists
        key: node-role.kubernetes.io/control-plane
      restartPolicy: OnFailure
      volumes:
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      containers:
        - name: monitor
          image: registry.local:9001/docker.io/bitnami/kubectl:1.29
          command: [ "/bin/bash", "/tmp/mount/monitor.sh" ]
          env:
          - name: HAS_MON_FLOAT
            value: "$MON_FLOAT_ENABLED"
          volumeMounts:
          - mountPath: /tmp/mount
            name: rook-ceph-recovery
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
        """)


if __name__ == '__main__':
    try:
        recover_cluster()
    except subprocess.CalledProcessError as e:
        print("Error: Running command \"{}\" exited with {}. Output: {}".format(e.cmd, e.returncode, e.output))
        sys.exit(e.returncode)
