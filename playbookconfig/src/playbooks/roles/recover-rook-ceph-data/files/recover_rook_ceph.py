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
from string import Template

CEPH_TMP = '/tmp/ceph'
MONMAP_FILENAME = 'monmap.bin'
RECOVERY_JOB_RESOURCE_FILENAME = 'recovery-job.yaml'
UPDATE_OSD_KEYRING_JOB_RESOURCE_FILENAME = 'update-osd-keyring-{}-job.yaml'
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
    has_mon_float = False
    mons_to_clean = {}

    if structure != "ONE_HOST":
        subprocess.run(["kubectl", "label", "deployment", "-n", "rook-ceph",
                        "-l", "app=rook-ceph-mon", "ceph.rook.io/do-not-reconcile="])

    cmd = ["kubectl", "-n", "rook-ceph", "get", "configmap",
           "rook-ceph-mon-endpoints", "-o", "jsonpath=\'{.data.mapping}\'"]
    with open(os.devnull, "w") as fnull:
        cmd_output = subprocess.check_output(cmd, stderr=fnull).decode('UTF-8')

    mons = json.loads(ast.literal_eval(cmd_output))
    for name, data in mons['node'].items():
        hostname = data['Hostname']

        if name == "float":
            has_mon_float = True
            continue
        elif hostname == target_hostname:
            target_mon = name
        elif structure == "ONLY_OSD" and not target_mon:
            target_mon = name

        mons_to_clean[name] = hostname

    target_mon_hostname = mons_to_clean.pop(target_mon)

    if not has_mon_float:
        with open(os.devnull, "w") as fnull:
            result = subprocess.run(["kubectl", "-n", "rook-ceph", "get", "deployment", "rook-ceph-mon-float"],
                                    stderr=fnull, stdout=fnull)
        if result.returncode == 0:
            has_mon_float = True

    with open(os.path.join(CEPH_TMP, MONMAP_FILENAME), "rb") as monmap_file:
        monmap_b64 = base64.b64encode(monmap_file.read()).decode()

    recovery_job_template = get_recovery_job_template()
    recovery_job_resource = recovery_job_template.safe_substitute({'STRUCTURE': structure,
                                                                   'TARGET_HOSTNAME': target_hostname,
                                                                   'TARGET_MON': target_mon,
                                                                   'TARGET_MON_HOSTNAME': target_mon_hostname,
                                                                   'MON_FLOAT_ENABLED': str(has_mon_float).lower(),
                                                                   'MONMAP_BINARY': monmap_b64})
    recovery_job_resource_path = create_job_resource(recovery_job_resource, RECOVERY_JOB_RESOURCE_FILENAME)

    subprocess.run(["kubectl", "apply", "-f", recovery_job_resource_path])
    if target_hostname == "controller-0":
        result = subprocess.run(["kubectl", "wait", "--for=condition=complete", "job", "--all=true",
                                 "-n", "rook-ceph", "-l", "app=rook-ceph-recovery", "--timeout=30m"])
        if result.returncode != 0:
            sys.exit(result.returncode)

    if structure != "ONE_HOST":
        if structure == "ONLY_OSD":
            move_mon_job_template = get_move_mon_job_template()
            move_mon_job_resource = move_mon_job_template.safe_substitute({'TARGET_HOSTNAME': target_mon_hostname,
                                                                           'TARGET_MON': target_mon,
                                                                           'RECOVERY_HOSTNAME': target_hostname})
            move_mon_job_resource_path = create_job_resource(move_mon_job_resource,
                                                             MOVE_MON_JOB_RESOURCE_FILENAME.format(target_mon))
            subprocess.run(["kubectl", "apply", "-f", move_mon_job_resource_path])

        for hostname in hosts_to_update_keyring:
            update_osd_keyring_job_template = get_update_osd_keyring_job_template()
            update_osd_keyring_job_resource = update_osd_keyring_job_template.safe_substitute({'TARGET_HOSTNAME': hostname})
            update_osd_keyring_job_resource_path = create_job_resource(update_osd_keyring_job_resource,
                                                                       UPDATE_OSD_KEYRING_JOB_RESOURCE_FILENAME.format(hostname))
            subprocess.run(["kubectl", "apply", "-f", update_osd_keyring_job_resource_path])

        for name, hostname in mons_to_clean.items():
            clean_mon_job_template = get_clean_mon_job_template()
            clean_mon_job_resource = clean_mon_job_template.safe_substitute({'TARGET_HOSTNAME': hostname,
                                                                             'TARGET_MON': name,
                                                                             'MON_FLOAT_ENABLED': str(has_mon_float).lower()})
            clean_mon_job_resource_path = create_job_resource(clean_mon_job_resource,
                                                              CLEAN_MON_JOB_RESOURCE_FILENAME.format(name))
            subprocess.run(["kubectl", "apply", "-f", clean_mon_job_resource_path])

    monitor_job_template = get_monitor_job_template()
    monitor_job_resource = monitor_job_template.safe_substitute({'TARGET_HOSTNAME': target_hostname,
                                                                 'MON_FLOAT_ENABLED': str(has_mon_float).lower(),
                                                                 'STRUCTURE': structure})
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

    check_command_rc() {
      rc=$1
      message="$2"
      if [ $rc -eq 0 ]; then
        return
      elif [ $rc -eq 124 ]; then
        echo "command timeout exceeded, exit"
      else
        if [ -z "$message" ]; then
          echo "command failed, exit"
        else
          echo "$message"
        fi
      fi
      exit $rc
    }

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
    check_command_rc $? "unexpected kubernetes error, exit"

    kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 0
    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-operator --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-operator --grace-period=0 --force
    fi

    if [ $STRUCT != 'ONE_HOST' ]; then
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

      # For IPv4
      mon_host_addr=$(kubectl -n rook-ceph get service rook-ceph-mon-${MON_NAME} -o jsonpath='{.spec.clusterIP}')
      mon_host="[v2:${mon_host_addr}:3300,v1:${mon_host_addr}:6789]"

      # For IPv6
      ip_family=$(kubectl -n rook-ceph get service rook-ceph-mon-${MON_NAME} -o jsonpath='{.spec.ipFamilies[0]}')
      if [ $ip_family == 'IPv6' ]; then
        mon_host_addr="[$mon_host_addr]"
        mon_host="v2:${mon_host_addr}:3300,v1:${mon_host_addr}:6789"
      fi

      kubectl -n rook-ceph patch configmap rook-ceph-mon-endpoints -p '{"data": {"data": "'"${MON_NAME}"'='"${mon_host_addr}"':6789"}}'
      kubectl -n rook-ceph patch secret rook-ceph-config -p '{"stringData": {"mon_host": "'"${mon_host}"'", "mon_initial_members": "'"${MON_NAME}"'"}}'

      if [ $STRUCT == 'ONLY_OSD' ]; then
        kubectl label nodes ${HOSTNAME} ceph-mgr-placement=enabled
        kubectl label nodes ${HOSTNAME} ceph-mon-placement=enabled
        kubectl label nodes ${MON_HOSTNAME} ceph-mgr-placement-
        kubectl label nodes ${MON_HOSTNAME} ceph-mon-placement-
        kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
      fi

      if [ "${HAS_MON_FLOAT}" == true ]; then
        rm -rf /var/lib/rook/mon-float/mon-float
      fi

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=${TIME_WAIT_READY}
    fi

    ceph -s
    check_command_rc $?

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
      check_command_rc $?
    done

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

      while [ ! -f /var/lib/rook/data/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring ]
      do
        sleep ${TIME_RETRY}
      done

      kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_DELETE}
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l osd=${osd_id} --grace-period=0 --force
      fi

      OSD_KEYRING=(`cat /var/lib/rook/data/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring | sed -n -e 's/^.*key = //p'`)
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      while [ "$key" != "${OSD_KEYRING}" ]
      do
        key=$(ceph auth get-key osd.${osd_id})
        check_command_rc $?
        ceph auth import -i /tmp/osd.${osd_id}.keyring
        check_command_rc $?
        sleep ${TIME_RETRY}
      done

      ceph-objectstore-tool --type bluestore --data-path /var/lib/rook/data/rook-ceph/${ceph_fsid}_${osd_uuid} --op update-mon-db --mon-store-path /tmp/monstore
      check_command_rc $? "Error updating mon db, exit"

      kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 1
      sleep ${TIME_AFTER_SCALE}
      kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_READY}
    done

    if [ -z "$OWN_OSDS" ]; then
      echo "no osd found, exit"
      exit 1
    fi

    ceph auth export -o /tmp/export.keyring
    check_command_rc $?

    if [ ! -f /tmp/ceph/monmap.bin ]; then
      echo "monmap.bin not found in /tmp/ceph.. Getting from rook-ceph-recovery configmap."
      kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.monmap_b64}' | base64 -d > /tmp/ceph/monmap.bin
      check_command_rc $? "Error getting monmap from configmap, exit"
    fi

    ceph-monstore-tool /tmp/monstore rebuild -- --keyring /tmp/export.keyring --monmap /tmp/ceph/monmap.bin
    check_command_rc $? "Error rebuilding monstore, exit"

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 0
    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-osd --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-osd --grace-period=0 --force
    fi

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 0
    kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mon --timeout=${TIME_WAIT_DELETE}
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete pod -l app=rook-ceph-mon --grace-period=0 --force
    fi

    rm -rf /var/lib/rook/data/mon-${MON_NAME}/data/store.db
    cp -ar /tmp/monstore/store.db /var/lib/rook/data/mon-${MON_NAME}/data

    kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
    sleep ${TIME_AFTER_SCALE}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=${TIME_WAIT_READY}

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 1
    sleep ${TIME_AFTER_SCALE}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l "app=rook-ceph-osd,topology-location-host=${HOSTNAME}" --timeout=${TIME_WAIT_READY}

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mgr --replicas 1
    sleep ${TIME_AFTER_SCALE}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-mgr --timeout=${TIME_WAIT_READY}

    ceph -s
    check_command_rc $?

    FS_NAME=kube-cephfs
    DATA_POOL_NAME=kube-cephfs-data
    METADATA_POOL_NAME=kube-cephfs-metadata

    # Check if the filesystem for the system RWX provisioner is present
    ceph fs get ${FS_NAME}
    rc=$?
    if [ $rc -eq 124 ]; then
        echo "ceph timeout exceeded, exit"
        exit 1
    elif [ $rc -ne 0 ]; then
        osds=$(ceph osd ls)
        check_command_rc $?
        for osd_id in $osds; do
          if ! [[ ${OWN_OSDS[*]} =~ "$osd_id" ]]; then
              kubectl -n rook-ceph scale deployment rook-ceph-osd-${osd_id} --replicas 0
              kubectl -n rook-ceph wait --for=delete pod --all=true -l osd=${osd_id} --timeout=${TIME_WAIT_DELETE}
              if [ $? -ne 0 ]; then
                kubectl -n rook-ceph delete pod -l osd=${osd_id} --grace-period=0 --force
              fi
              ceph osd down $osd_id
              check_command_rc $?
          fi
        done

        # Use existing metadata/data pools to recover cephfs
        ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME} --force
        check_command_rc $?

        # Recover MDS state from filesystem
        ceph fs reset ${FS_NAME} --yes-i-really-mean-it
        check_command_rc $?

        # Try to recover from some common errors
        # The timeout command was used because depending on the status of the cluster, it can get stuck
        # on "cephfs" commands. But this will not cause any problems in recovery.
        CEPHFS_CMD_TIMEOUT=180
        timeout ${CEPHFS_CMD_TIMEOUT} cephfs-journal-tool --rank=${FS_NAME}:0 event recover_dentries summary
        if [ $? -eq 0 ]; then
          timeout ${CEPHFS_CMD_TIMEOUT} cephfs-journal-tool --rank=${FS_NAME}:0 journal reset
          timeout ${CEPHFS_CMD_TIMEOUT} cephfs-table-tool ${FS_NAME}:0 reset session
          timeout ${CEPHFS_CMD_TIMEOUT} cephfs-table-tool ${FS_NAME}:0 reset snap
          timeout ${CEPHFS_CMD_TIMEOUT} cephfs-table-tool ${FS_NAME}:0 reset inode
        fi
    fi

    kubectl -n rook-ceph scale deployment -l app=rook-ceph-osd --replicas 1
    kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 1

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

    kubectl -n rook-ceph scale deployment rook-ceph-operator --replicas 1
    sleep ${TIME_AFTER_SCALE}
    kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l app=rook-ceph-operator --timeout=${TIME_WAIT_READY}

    ceph config set mgr mgr/crash/warn_recent_interval 0

    kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"status": "completed"}}'
    exit 0

  update_osd_keyring.sh: |-
    #!/bin/bash

    set -x

    while [ "$status" != "completed" ]
    do
      # TODO: Instead of sleep, use 'kubectl wait'
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      sleep 10
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

      OSD_KEYRING=(`cat /var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}/keyring | sed -n -e 's/^.*key = //p'`)
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      until ceph -s; do
        sleep 60
      done

      while [ "$(ceph auth get-key osd.${osd_id})" != "${OSD_KEYRING}" ]
      do
        ceph auth import -i /tmp/osd.${osd_id}.keyring
        rc=$?
        if [ $rc -eq 124 ]; then
          echo "ceph timeout exceeded, exit"
          exit 1
        elif [ $rc -ne 0 ]; then
          echo "ceph command failed, exit"
          exit 1
        fi
      done
    done

    exit 0

  clean_mon.sh: |-
    #!/bin/bash
    set -x
    while true
    do
      # TODO: Instead of sleep, use 'kubectl wait'
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        kubectl -n rook-ceph wait --for=condition=complete job --all=true -l app=rook-ceph-recovery-update-osd-keyring --timeout=30s
        if [ $? -eq 0 ]; then
          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 0
          kubectl -n rook-ceph wait --for=delete pod --all=true -l mon=${MON_NAME} --timeout=30s
          if [ $? -ne 0 ]; then
            kubectl -n rook-ceph delete pod -l mon=${MON_NAME} --grace-period=0 --force
          fi

          rm -rf /var/lib/rook/data/mon-${MON_NAME}
          if [ "${HAS_MON_FLOAT}" == true ]; then
            rm -rf /var/lib/rook/mon-float/mon-float
          fi

          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
          sleep 10
          kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=60s

          break
        fi
      fi
      sleep 10
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
      # TODO: Instead of sleep, use 'kubectl wait'
      sleep 10
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        if [ "$(ceph health)" == "HEALTH_OK" ]; then
          kubectl -n rook-ceph wait --for=condition=complete job --all=true -l app=rook-ceph-recovery-clean-mon --timeout=30s
          if [ $? -ne 0 ]; then
            continue
          fi

          MDS_NAME=$(kubectl -n rook-ceph get pods -l app=rook-ceph-mds --field-selector spec.nodeName=${RECOVERY_HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mds")
          MGR_NAME=$(kubectl -n rook-ceph get pods -l app=rook-ceph-mgr --field-selector spec.nodeName=${RECOVERY_HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mgr")

          kubectl -n rook-ceph scale deployment rook-ceph-mds-${MDS_NAME} --replicas 0
          kubectl -n rook-ceph wait --for=delete pod --all=true -l mds=${MDS_NAME} --timeout=30s
          if [ $? -ne 0 ]; then
            kubectl -n rook-ceph delete pod -l mds=${MDS_NAME} --grace-period=0 --force
          fi

          kubectl -n rook-ceph scale deployment rook-ceph-mgr-${MGR_NAME} --replicas 0
          kubectl -n rook-ceph wait --for=delete pod --all=true -l mgr=${MGR_NAME} --timeout=30s
          if [ $? -ne 0 ]; then
            kubectl -n rook-ceph delete pod -l mgr=${MGR_NAME} --grace-period=0 --force
          fi

          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 0
          kubectl -n rook-ceph wait --for=delete pod --all=true -l mon=${MON_NAME} --timeout=30s
          if [ $? -ne 0 ]; then
            kubectl -n rook-ceph delete pod -l mon=${MON_NAME} --grace-period=0 --force
          fi

          rm -rf /var/lib/rook/mon-${MON_NAME}

          kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
          kubectl label nodes ${HOSTNAME} ceph-mgr-placement=enabled
          kubectl label nodes ${HOSTNAME} ceph-mon-placement=enabled
          kubectl label nodes ${RECOVERY_HOSTNAME} ceph-mgr-placement-
          kubectl label nodes ${RECOVERY_HOSTNAME} ceph-mon-placement-

          kubectl -n rook-ceph scale deployment rook-ceph-mon-${MON_NAME} --replicas 1
          sleep 10
          kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mon=${MON_NAME} --timeout=60s

          kubectl -n rook-ceph scale deployment rook-ceph-mgr-${MGR_NAME} --replicas 1
          kubectl -n rook-ceph scale deployment rook-ceph-mds-${MDS_NAME} --replicas 1
          kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mgr=${MGR_NAME} --timeout=60s
          kubectl -n rook-ceph wait --for=condition=Ready pod --all=true -l mds=${MDS_NAME} --timeout=60s

          echo "rook-ceph mon moved successfully."
          break
        fi
      fi
    done
    exit 0

  monitor.sh: |-
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
      # TODO: Instead of sleep, use 'kubectl wait'
      sleep 30
      status=$(kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}')
      if [ "$status" == "completed" ]; then
        if [ "${STRUCT}" == 'ONE_HOST' ]; then
          break
        fi

        kubectl -n rook-ceph wait --for=condition=complete job --all=true -l app.kubernetes.io/part-of=rook-ceph-recovery
        if [ $? -ne 0 ]; then
          continue
        fi

        if [ "${HAS_MON_FLOAT}" == false ]; then
          kubectl -n rook-ceph label deployment -l app=rook-ceph-mon ceph.rook.io/do-not-reconcile-
        fi
        kubectl -n rook-ceph scale deployment -l app=rook-ceph-mon --replicas 1

        if [ "${STRUCT}" == 'ONLY_OSD' ]; then
          rm -rf /var/lib/rook/mon-*
        fi

        break
      fi
    done

    if ceph health | grep "mds daemon damaged\\|filesystem is degraded"; then
      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 0
      kubectl -n rook-ceph wait --for=delete pod --all=true -l app=rook-ceph-mds --timeout=30s
      if [ $? -ne 0 ]; then
        kubectl -n rook-ceph delete pod -l app=rook-ceph-mds --grace-period=0 --force
      fi

      FS_NAME=kube-cephfs
      DATA_POOL_NAME=kube-cephfs-data
      METADATA_POOL_NAME=kube-cephfs-metadata

      ceph fs reset ${FS_NAME} --yes-i-really-mean-it
      cephfs-journal-tool --rank=${FS_NAME}:0 event recover_dentries summary
      cephfs-journal-tool --rank=${FS_NAME}:0 journal reset
      cephfs-table-tool ${FS_NAME}:0 reset session
      cephfs-table-tool ${FS_NAME}:0 reset snap
      cephfs-table-tool ${FS_NAME}:0 reset inode

      kubectl -n rook-ceph scale deployment -l app=rook-ceph-mds --replicas 1
    fi

    set +x
    PODS=$(kubectl -n rook-ceph get pods -l app.kubernetes.io/part-of=rook-ceph-recovery --no-headers -o custom-columns=":metadata.name")
    for pod in $PODS; do
      echo -e "\\n##############################\\n$pod\\n##############################" >> /var/log/ceph/restore.log
      kubectl -n rook-ceph logs $pod >> /var/log/ceph/restore.log
    done

    set -x
    kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery
    kubectl -n rook-ceph wait --for=delete job --all=true -l app.kubernetes.io/part-of=rook-ceph-recovery --timeout=30s
    if [ $? -ne 0 ]; then
      kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery --grace-period=0 --force
    fi

    set +x
    echo -e "\\n##############################\\nrook-ceph-recovery-monitor\\n##############################" >> /var/log/ceph/restore.log
    kubectl -n rook-ceph logs $(kubectl get pod -n rook-ceph -l app=rook-ceph-recovery-monitor -o name) >> /var/log/ceph/restore.log

    set -x
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
  resources: ["pods/log"]
  verbs: ["get"]
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
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
      labels:
        app: rook-ceph-recovery
        app.kubernetes.io/part-of: rook-ceph-recovery
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
          - name: MON_HOSTNAME
            value: $TARGET_MON_HOSTNAME
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


def get_update_osd_keyring_job_template():
    return Template(
        """
---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-update-osd-keyring-$TARGET_HOSTNAME
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-update-osd-keyring
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-update-osd-keyring-$TARGET_HOSTNAME
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-update-osd-keyring
        app.kubernetes.io/part-of: rook-ceph-recovery
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
        - name: update-osd-keyring
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/update_osd_keyring.sh" ]
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
  name: rook-ceph-recovery-clean-mon-$TARGET_MON
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-clean-mon
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-clean-mon-$TARGET_MON
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-clean-mon
        app.kubernetes.io/part-of: rook-ceph-recovery
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
        - name: clean-mon
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/clean_mon.sh" ]
          env:
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
  name: rook-ceph-recovery-move-mon-$TARGET_MON
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-move-mon
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-move-mon-$TARGET_MON
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-move-mon
        app.kubernetes.io/part-of: rook-ceph-recovery
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
        - name: move-mon
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
          - name: RECOVERY_HOSTNAME
            value: $RECOVERY_HOSTNAME
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
  ttlSecondsAfterFinished: 30
  template:
    metadata:
      name: rook-ceph-recovery-monitor
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-monitor
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
            path: /var/log/ceph
            type: ""
          name: ceph-log
        - name: rook-ceph-recovery
          configMap:
            name: rook-ceph-recovery
            defaultMode: 0555
        - name: kube-config
          hostPath:
            path: /etc/kubernetes/admin.conf
      containers:
        - name: monitor
          image: registry.local:9001/docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312
          command: [ "/bin/bash", "/tmp/mount/monitor.sh" ]
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
          - name: HAS_MON_FLOAT
            value: "$MON_FLOAT_ENABLED"
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - mountPath: /var/lib/rook
            name: rook-data
          - mountPath: /var/log/ceph
            name: ceph-log
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
