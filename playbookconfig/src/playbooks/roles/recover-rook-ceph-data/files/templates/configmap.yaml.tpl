---
apiVersion: v1
kind: ConfigMap
metadata:
  name: rook-ceph-recovery
  namespace: rook-ceph
data:
  provision.sh: |-
    #!/bin/bash
    set -x

    if [ "${MON_HOST}"x == ""x ]; then
      MON_HOST=$(echo ${ROOK_MONS} | sed 's/[a-z]\+=//g')
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

  common.sh: |-
    #!/bin/bash
    set -x

    TIME_AFTER_SCALE=$([ "${RECOVERY_TYPE}" == "SINGLE_HOST" ] && echo "1s" || echo "10s")
    TIME_WAIT_DELETE=$([ "${RECOVERY_TYPE}" == "SINGLE_HOST" ] && echo "1s" || echo "30s")
    TIME_WAIT_READY=$([ "${RECOVERY_TYPE}" == "SINGLE_HOST" ] && echo "1s" || echo "60s")
    TIME_RETRY=$([ "${RECOVERY_TYPE}" == "SINGLE_HOST" ] && echo "2s" || echo "5s")
    TIME_WAIT_JOB_COMPLETE="120s"
    TIME_WAIT_FOR_STATUS="30s"

    # Checks the k8s API for 15 minutes. After the timeout, rook-ceph recovery will fail.
    check_k8s_health(){
      local cmd_output rc
      for i in {1..180}
      do
        cmd_output=$(kubectl get --raw='/readyz' 2>&1)
        rc=$?
        if [ $rc -eq 0 ] && [ "$cmd_output" == "ok" ]; then
          return 0
        fi
        sleep 5
      done
      fail "Kubernetes health check failed (rc=${rc}): ${cmd_output}"
    }

    exec_k8s_cmd() {
      local cmd_output rc
      # Check if a callback variable is provided
      if [[ -v $1 ]] || ! command -v "$1" &>/dev/null; then
        local -n cmd_output=$1
        shift
      fi

      # Try running the command 3 times
      for i in {1..3}; do
        cmd_output=$("$@" 2>&1)
        rc=$?
        echo "$cmd_output"
        if [ "$rc" -eq 0 ]; then
          return 0
        # If it is a 'kubectl wait' command, the expected behavior is that the command fails,
        # so there is specific handling for that case.
        elif [[ "$@" =~ "wait" ]]; then
          if [[ "$cmd_output" =~ "no matching resources" ]]; then
              return 0
          elif [[ "$cmd_output" =~ "timed out waiting"|"condition not met" ]]; then
              return 1
          fi
        elif [[ "$cmd_output" =~ "no objects passed" ]]; then
          return 0
        fi
        check_k8s_health
      done
      fail "command '$@' failed (rc=${rc}): ${cmd_output}"
    }

    exec_ceph_cmd() {
      local cmd_output rc
      local timeout=60
      # Check if a callback variable is provided
      if [[ -v $1 ]] || ! command -v "$1" &>/dev/null; then
        local -n cmd_output=$1
        shift
      fi

      # Check if the command contains "config", "tool" or "scan" to adjust the timeout
      if [[ "$@" =~ "config" ]]; then
        timeout=30   # Timeout for commands related to "config"
      elif [[ "$@" =~ "tool" ]]; then
        timeout=180  # Timeout for commands related to "tool"
      elif [[ "$@" =~ "scan" ]]; then
        timeout=600  # Timeout for commands related to "scan"
      fi

      # Try running the command 3 times
      for i in {1..3}; do
        cmd_output=$(timeout "$timeout" "$@" 2>&1)
        rc=$?
        echo "$cmd_output"
        if [ "$rc" -eq 0 ]; then
          return 0
        fi
        sleep 5
      done

      # Do not fail recovery if it is config or scan command.
      if [[ "$@" =~ (config|scan) ]]; then
        return $rc
      fi
      fail "command '$@' failed (rc=${rc}): ${cmd_output}"
    }

    # If replicas=1: wait for pods with the given label to become ready.
    # If replicas=0: wait for pods to be deleted; if they are not deleted within the timeout, force their deletion.
    # If wait_label is not provided, it defaults to the label argument.
    kubectl_scale_deployment() {
      local label="$1"
      local wait_label=$([ "$#" -eq 3 ] && echo "$2" || echo "$label")
      local replicas="${!#}"
      exec_k8s_cmd kubectl -n rook-ceph scale deployment -l "${label}" --replicas="${replicas}"
      if [ "$replicas" -eq 0 ]; then
        if [ -n "$wait_label" ]; then
          exec_k8s_cmd kubectl -n rook-ceph wait --for=delete pod -l "${wait_label}" --timeout=${TIME_WAIT_DELETE}
        fi
        exec_k8s_cmd kubectl -n rook-ceph delete pod -l "${label}" --grace-period=0 --force
      elif [ "$replicas" -eq 1 ] && [ -n "$wait_label" ]; then
        sleep "${TIME_AFTER_SCALE}"
        exec_k8s_cmd kubectl -n rook-ceph wait --for=condition=Ready pod -l "${wait_label}" --timeout=${TIME_WAIT_READY}
      fi
    }

    # Checks if the current recovery status is any of the desired statuses
    check_status() {
      local desired_status="$1"
      local status=""
      exec_k8s_cmd status kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.status}'
      for s in $desired_status; do
        if [[ "$status" == "$s" ]]; then
          return 0
        fi
      done
      return 1
    }

    # Wait until the job with the given label is completed. This function is blocking
    # because it needs to complete to advance the recovery to the next step.
    wait_job_complete(){
      local label=$1
      while true
      do
        if exec_k8s_cmd kubectl -n rook-ceph wait --for=condition=complete job -l "${label}" --timeout=${TIME_WAIT_JOB_COMPLETE}; then
          break
        fi
        check_failure
      done
    }

    # It is used inside worker pods to check if the current status is
    # as expected so that execution can be started.
    wait_for_status() {
      local desired_status="$1"
      while true
      do
        # TODO: Instead of sleep, use 'kubectl wait'
        if check_status "$desired_status"; then
          break
        elif [[ ! "$desired_status" =~ "recovery-failed" ]]; then
          check_failure
        fi
        sleep "${TIME_WAIT_FOR_STATUS}"
      done
    }

    # Update the "status" of the rook-ceph-recovery configmap
    update_status() {
      check_failure
      local status="$1"
      local patch=$(printf '{"data": {"status": "%s"}}' "$status")
      exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-recovery --type=merge -p "$patch"
    }

    # When a failure occurs, the status is changed to 'recovery-failed'
    # and the reason is set in the 'failure' field.
    fail() {
      if ! check_status "recovery-failed"; then
        failure="$@"
        json_payload=$(jq -n --arg failure "$failure" --arg status "recovery-failed" '{data: {failure: $failure, status: $status}}')
        exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-recovery --patch "$json_payload"
      fi
      exit 0
    }

    # Checks if the status is 'recovery-failed', if so, the pod is terminated.
    check_failure() {
      if check_status "recovery-failed"; then
        echo "Recovery failed! Exiting.."
        exit 0
      fi
    }

  operator.sh: |-
    #!/bin/bash
    source /tmp/mount/common.sh
    set -x

    # Check if there was any recovery failure
    check_failure

    # Ensures operator is not running during cephfs recovery
    kubectl_scale_deployment operator=rook app=rook-ceph-operator 0

    # Check if the monstore needs to be rebuilt
    if check_status "recovery-pending rebuilding-monstore"; then
      update_status "rebuilding-monstore"
      wait_job_complete app=rook-ceph-recovery-monstore-rebuild

      if [ "${RECOVERY_TYPE}" == "SINGLE_HOST" ]; then
        update_status "cephfs-recovery-pending"
      elif [ "${HAS_OSD_KEYRING_UPDATE_JOB}" == true ]; then
        update_status "osd-keyring-update-pending"
      else
        update_status "mon-cleanup-pending"
      fi
    fi

    # Check if the OSD keyring needs to be updated
    if check_status "osd-keyring-update-pending updating-osd-keyring"; then
      update_status "updating-osd-keyring"
      wait_job_complete app=rook-ceph-recovery-osd-keyring-update
      update_status "mon-cleanup-pending"
    fi

    # Check if the mon needs cleaning
    if check_status "mon-cleanup-pending cleaning-mon"; then
      update_status "cleaning-mon"
      wait_job_complete app=rook-ceph-recovery-mon-cleanup

      if [ "${HAS_MON_FLOAT}" == true ]; then
        kubectl_scale_deployment mon=float 1
      fi

      update_status "cephfs-recovery-pending"
    fi

    # Check if cephfs needs to be recovered
    if check_status "cephfs-recovery-pending recovering-cephfs"; then
      update_status "recovering-cephfs"

      # Ensures required pods are running
      kubectl_scale_deployment app=rook-ceph-mon 1
      kubectl_scale_deployment app=rook-ceph-osd 1
      kubectl_scale_deployment app=rook-ceph-mgr 1

      # Ensures mds is not running during cephfs recovery
      kubectl_scale_deployment app=rook-ceph-mds 0

      exec_ceph_cmd ceph -s

      FS_NAME="kube-cephfs"
      DATA_POOL_NAME="kube-cephfs-data"
      METADATA_POOL_NAME="kube-cephfs-metadata"

      # Use existing metadata/data pools to recover cephfs
      exec_ceph_cmd ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME} --force

      # Recover MDS state from filesystem
      exec_ceph_cmd ceph fs reset ${FS_NAME} --yes-i-really-mean-it

      # Wait to ensure reset propagation
      exec_k8s_cmd MONS kubectl -n rook-ceph get pods -l app=rook-ceph-mon -o name
      MON_COUNT=$(echo "$MONS" | wc -w)
      if [ "$MON_COUNT" -le 3 ]; then
        sleep 15
      else
        sleep 30
      fi

      # Try to recover from some common errors
      exec_ceph_cmd cephfs-journal-tool --rank=${FS_NAME}:0 event recover_dentries summary
      exec_ceph_cmd cephfs-journal-tool --rank=${FS_NAME}:0 journal reset
      exec_ceph_cmd cephfs-table-tool ${FS_NAME}:0 reset session
      exec_ceph_cmd cephfs-table-tool ${FS_NAME}:0 reset snap
      exec_ceph_cmd cephfs-table-tool ${FS_NAME}:0 reset inode

      # Check if there are any VolumeSnapshotContent with cephfs driver
      if exec_k8s_cmd kubectl get volumesnapshotcontents \
            -o custom-columns="DRIVER:spec.driver" | grep -q "cephfs.csi.ceph.com"; then

        # The cephfs-data-scan command needs to be run more than once
        # to ensure that all issues are fixed.
        while true
        do
          exec_ceph_cmd OUTPUT cephfs-data-scan scan_links
          # If the command fails or returns empty, it should exit the loop.
          if [ $? -ne 0 ] || [ -z "$OUTPUT" ]; then
            break
          fi
          sleep 1
        done
      fi

      kubectl_scale_deployment app=rook-ceph-mds 1
      exec_ceph_cmd ceph -s

      if [ "${RECOVERY_TYPE}" == "OSD_ONLY" ]; then
        update_status "mon-rollback-pending"
      else
        update_status "cephfs-recovery-completed"
      fi
    fi

    # Checks if mon needs to be returned to the source host
    if check_status "mon-rollback-pending rolling-back-mon"; then
      # Avoid the warning message 'mon is allowing insecure global_id reclaim'
      exec_ceph_cmd ceph config set mon mon_warn_on_insecure_global_id_reclaim false
      exec_ceph_cmd ceph config set mon mon_warn_on_insecure_global_id_reclaim_allowed false

      # Avoid the message that the daemon recently crashed
      warn_recent_interval=$(exec_ceph_cmd ceph config get mgr mgr/crash/warn_recent_interval || echo 0)
      exec_ceph_cmd ceph config set mgr mgr/crash/warn_recent_interval 0
      exec_ceph_cmd ceph crash archive-all

      # Wait HEALTH_OK for 5 minutes. If the timeout is reached,
      # the process will continue anyway, as this final step is unlikely to cause problems.
      for i in {1..60}
      do
        if exec_ceph_cmd ceph health | grep "HEALTH_OK"; then
          break
        fi
        sleep 5
      done

      update_status "rolling-back-mon"
      wait_job_complete app=rook-ceph-recovery-mon-rollback

      # Delete mon data left on host
      rm -rf /var/lib/rook/mon-*

      # Reset previously changed configs
      exec_ceph_cmd ceph config set mon mon_warn_on_insecure_global_id_reclaim true
      exec_ceph_cmd ceph config set mon mon_warn_on_insecure_global_id_reclaim_allowed true
      exec_ceph_cmd ceph config set mgr mgr/crash/warn_recent_interval $warn_recent_interval

      update_status "mon-rollback-completed"
    fi

    kubectl_scale_deployment operator=rook app=rook-ceph-operator 1
    exec_ceph_cmd ceph -s

    echo "rook-ceph recovery completed successfully."
    update_status "recovery-completed"
    exit 0

  monstore_rebuild.sh: |-
    #!/bin/bash
    set -x

    source /tmp/mount/common.sh

    wait_for_status "rebuilding-monstore"

    if [ "${RECOVERY_TYPE}" != "SINGLE_HOST" ]; then
      kubectl_scale_deployment app=rook-ceph-mon mon=${MON_NAME} 0

      # It takes data from the monitors and stores it so that it can be used at the end of the process.
      # It will always check the data stored in the rook-ceph-recovery configmap first,
      # as the data there will be intact in a situation where this job was previously stopped.

      exec_k8s_cmd DATA_MON_ENDPOINTS kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_endpoints}'
      if [ -z "${DATA_MON_ENDPOINTS}" ]; then
        exec_k8s_cmd DATA_MON_ENDPOINTS kubectl -n rook-ceph get configmap rook-ceph-mon-endpoints -o jsonpath='{.data.data}'
        exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_endpoints": "'"${DATA_MON_ENDPOINTS}"'"}}'
      fi

      exec_k8s_cmd DATA_MON_HOST kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_host}'
      if [ -z "${DATA_MON_HOST}" ]; then
        exec_k8s_cmd DATA_MON_HOST kubectl -n rook-ceph get secret rook-ceph-config -o jsonpath='{.data.mon_host}'
        exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_host": "'"${DATA_MON_HOST}"'"}}'
      fi

      exec_k8s_cmd DATA_MON_INIT kubectl -n rook-ceph get configmap rook-ceph-recovery -o jsonpath='{.data.mon_initial_members}'
      if [ -z "${DATA_MON_INIT}" ]; then
        exec_k8s_cmd DATA_MON_INIT kubectl -n rook-ceph get secret rook-ceph-config -o jsonpath='{.data.mon_initial_members}'
        exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-recovery -p '{"data": {"mon_initial_members": "'"${DATA_MON_INIT}"'"}}'
      fi

      # For IPv4
      exec_k8s_cmd MON_HOST_ADDR kubectl -n rook-ceph get service rook-ceph-mon-${MON_NAME} -o jsonpath='{.spec.clusterIP}'
      mon_host="[v2:${MON_HOST_ADDR}:3300,v1:${MON_HOST_ADDR}:6789]"

      # For IPv6
      exec_k8s_cmd IP_FAMILY kubectl -n rook-ceph get service rook-ceph-mon-${MON_NAME} -o jsonpath='{.spec.ipFamilies[0]}'
      if [ "$IP_FAMILY" == "IPv6" ]; then
        MON_HOST_ADDR="[$MON_HOST_ADDR]"
        mon_host="v2:${MON_HOST_ADDR}:3300,v1:${MON_HOST_ADDR}:6789"
      fi

      # Change the configmap and secret with only the host data to have quorum.
      exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-mon-endpoints -p '{"data": {"data": "'"${MON_NAME}"'='"${MON_HOST_ADDR}"':6789"}}'
      exec_k8s_cmd kubectl -n rook-ceph patch secret rook-ceph-config -p '{"stringData": {"mon_host": "'"${mon_host}"'", "mon_initial_members": "'"${MON_NAME}"'"}}'

      # If the host only has OSD, it means it needs to "steal" the monitor from another host.
      if [ "${RECOVERY_TYPE}" == "OSD_ONLY" ]; then
        exec_k8s_cmd kubectl label nodes ${HOSTNAME} ceph-mgr-placement=enabled --overwrite
        exec_k8s_cmd kubectl label nodes ${HOSTNAME} ceph-mon-placement=enabled --overwrite
        exec_k8s_cmd kubectl label nodes ${MON_HOSTNAME} ceph-mgr-placement-
        exec_k8s_cmd kubectl label nodes ${MON_HOSTNAME} ceph-mon-placement-
        exec_k8s_cmd kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
      fi

      if [ "${HAS_MON_FLOAT}" == true ]; then
        rm -rf /var/lib/rook/mon-float/mon-float
      fi

      kubectl_scale_deployment app=rook-ceph-mon mon=${MON_NAME} 1
    fi

    exec_ceph_cmd ceph -s

    exec_k8s_cmd MDS_NAME kubectl -n rook-ceph get pods -l app=rook-ceph-mds --field-selector spec.nodeName=${HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mds" | tr '\n' ','
    exec_k8s_cmd MGR_NAME kubectl -n rook-ceph get pods -l app=rook-ceph-mgr --field-selector spec.nodeName=${HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mgr"

    if [ -n "${MDS_NAME}" ]; then
      kubectl_scale_deployment app=rook-ceph-mds "mds in (${MDS_NAME})" 0
    else
      kubectl_scale_deployment app=rook-ceph-mds "" 0
    fi

    if [ -n "${MGR_NAME}" ]; then
      kubectl_scale_deployment app=rook-ceph-mgr mgr=${MGR_NAME} 0
    else
      kubectl_scale_deployment app=rook-ceph-mgr "" 0
    fi

    # Ensures mgr and mds keyrings are in ceph auth
    exec_k8s_cmd SECRETS kubectl -n rook-ceph get secrets -o custom-columns=:metadata.name
    for SECRET in $(echo "$SECRETS" | grep -E "rook-ceph-(mgr|mds)"); do
      if exec_ceph_cmd ceph auth ls | grep -vq "$SECRET"; then
        keyring_file="/tmp/${SECRET}"
        exec_k8s_cmd kubectl -n rook-ceph get secret "${SECRET}" -o jsonpath='{.data.keyring}' | base64 -d > ${keyring_file}
        exec_ceph_cmd ceph auth import -i $keyring_file
      fi
    done

    rm -rf /tmp/monstore
    mkdir -p /tmp/monstore

    # Ensures there is the "osd_data" file, which is generated by the init container.
    for i in {1..60}
    do
      if [ -f /tmp/ceph/osd_data ]; then
        break
      elif [ $i -eq 60 ]; then
        fail "Unable to get OSDs data from ${HOSTNAME}."
      fi
      sleep 5
    done

    # If there is no OSD, recovery will fail
    if [ "$(cat /tmp/ceph/osd_data)" == "{}" ]; then
      fail "No OSD found on ${HOSTNAME}."
    fi

    if [ "${HAS_OSD_KEYRING_UPDATE_JOB}" == true ]; then
      kubectl_scale_deployment app=rook-ceph-osd,topology-location-host!=${HOSTNAME} "" 0
    fi

    # Get the cluster fsid
    exec_k8s_cmd FSID_B64 kubectl -n rook-ceph get secret rook-ceph-mon -o jsonpath="{.data.fsid}"
    FSID=$(echo "$FSID_B64" | base64 -d)

    CLUSTER_HAS_OSD=false
    for row in $(cat /tmp/ceph/osd_data | jq -r '.[] | @base64'); do
      _jq() {
        echo "${row}" | base64 -di | jq -r "${1}"
      }
      ceph_fsid=$(_jq '.ceph_fsid')
      osd_id=$(_jq '.osd_id')
      osd_uuid=$(_jq '.osd_uuid')

      # If the ceph_fsid associated with the OSD is different from the cluster, skip that OSD.
      if [ "$FSID" != "$ceph_fsid" ]; then
        echo "ceph_fsid mismatch (osd.${osd_id}): cluster=${FSID} != osd=${ceph_fsid}. Skipping.."
        continue
      fi

      CLUSTER_HAS_OSD=true
      OSD_DIR="/var/lib/rook/data/rook-ceph/${ceph_fsid}_${osd_uuid}"

      for i in {1..60}
      do
        if [ -f ${OSD_DIR}/keyring ]; then
          break
        elif [ $i -eq 60 ]; then
          fail "Unable to get osd.${osd_id} keyring from ${HOSTNAME}."
        fi
        sleep 5
      done

      kubectl_scale_deployment osd=${osd_id} 0

      # Create a file containing the keyring
      OSD_KEYRING=$(cat ${OSD_DIR}/keyring | sed -n -e 's/^.*key = //p')
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      # Ensures ceph has the correct OSD keyring
      while true
      do
        exec_ceph_cmd ceph auth import -i /tmp/osd.${osd_id}.keyring
        exec_ceph_cmd key ceph auth get-key osd.${osd_id}
        if [ "$key" == "${OSD_KEYRING}" ]; then
          break
        fi
        sleep ${TIME_RETRY}
      done

      # Updates the monitor database with OSD data
      exec_ceph_cmd ceph-objectstore-tool --type bluestore --data-path ${OSD_DIR} --op update-mon-db --mon-store-path /tmp/monstore
    done

    # If no OSD with the cluster fsid was found,
    # the recovery process should be stopped.
    if [ "${CLUSTER_HAS_OSD}" == false ]; then
      fail "No OSD belonging to the cluster was found on ${HOSTNAME}."
    fi

    exec_ceph_cmd ceph auth export -o /tmp/export.keyring

    # If the monmap.bin is not found, get the monmap from the env.
    if [ ! -f /tmp/ceph/monmap.bin ]; then
      echo "${MONMAP}" | base64 -d > /tmp/ceph/monmap.bin
    fi

    # Rebuilding monitor data
    exec_ceph_cmd ceph-monstore-tool /tmp/monstore rebuild -- --keyring /tmp/export.keyring --monmap /tmp/ceph/monmap.bin

    exec_ceph_cmd ceph -s

    kubectl_scale_deployment app=rook-ceph-osd 0
    kubectl_scale_deployment app=rook-ceph-mon 0

    # Restore store.db from monstore
    rm -rf /var/lib/rook/data/mon-${MON_NAME}/data/store.db
    cp -ar /tmp/monstore/store.db /var/lib/rook/data/mon-${MON_NAME}/data

    kubectl_scale_deployment mon=${MON_NAME} 1
    kubectl_scale_deployment app=rook-ceph-osd,topology-location-host=${HOSTNAME} 1
    kubectl_scale_deployment app=rook-ceph-mgr 1

    exec_ceph_cmd ceph -s

    for i in {1..10}
    do
      echo "Waiting for rook-ceph-mgr to detect pools..."
      if timeout 30 ceph osd pool stats; then
        echo "Pools detected by rook-ceph-mgr."
        break
      fi
    done

    # Set the original configmap and secret data
    if [ "${RECOVERY_TYPE}" != "SINGLE_HOST" ]; then
      kubectl_scale_deployment app=rook-ceph-mon mon=${MON_NAME} 0
      exec_k8s_cmd kubectl -n rook-ceph patch configmap rook-ceph-mon-endpoints -p '{"data": {"data": "'"${DATA_MON_ENDPOINTS}"'"}}'
      exec_k8s_cmd kubectl -n rook-ceph patch secret rook-ceph-config -p '{"data": {"mon_host": "'"${DATA_MON_HOST}"'"}}'
      exec_k8s_cmd kubectl -n rook-ceph patch secret rook-ceph-config -p '{"data": {"mon_initial_members": "'"${DATA_MON_INIT}"'"}}'
      kubectl_scale_deployment mon=${MON_NAME} 1
    fi

    exec_ceph_cmd ceph -s

    echo "monstore rebuild completed successfully."
    exit 0

  osd_keyring_update.sh: |-
    #!/bin/bash
    set -x

    source /tmp/mount/common.sh

    wait_for_status "updating-osd-keyring"

    # Ensures there is the "osd_data" file, which is generated by the init container.
    for i in {1..60}
    do
      if [ -f /tmp/ceph/osd_data ]; then
        break
      elif [ $i -eq 60 ]; then
        fail "Unable to get OSDs data from ${HOSTNAME}."
      fi
      sleep 5
    done

    # If there is no OSD, recovery will fail
    if [ "$(cat /tmp/ceph/osd_data)" == "{}" ]; then
      fail "No OSD found on ${HOSTNAME}."
    fi

    # Ensures that all OSD deployments on this host are running.
    kubectl_scale_deployment app=rook-ceph-osd,topology-location-host=${HOSTNAME} "" 1

    # Get the cluster fsid
    exec_k8s_cmd FSID_B64 kubectl -n rook-ceph get secret rook-ceph-mon -o jsonpath="{.data.fsid}"
    FSID=$(echo "$FSID_B64" | base64 -d)

    CLUSTER_HAS_OSD=false
    for row in $(cat /tmp/ceph/osd_data | jq -r '.[] | @base64'); do
      _jq() {
        echo "${row}" | base64 -di | jq -r "${1}"
      }
      ceph_fsid=$(_jq '.ceph_fsid')
      osd_id=$(_jq '.osd_id')
      osd_uuid=$(_jq '.osd_uuid')

      # If the ceph_fsid associated with the OSD is different from the cluster, skip that OSD.
      if [ "$FSID" != "$ceph_fsid" ]; then
        echo "ceph_fsid mismatch (osd.${osd_id}): cluster=${FSID} != osd=${ceph_fsid}. Skipping.."
        continue
      fi

      # This means this cluster has OSD
      CLUSTER_HAS_OSD=true
      OSD_DIR="/var/lib/rook/rook-ceph/${ceph_fsid}_${osd_uuid}"

      # Wait until the OSD keyring is available
      for i in {1..60}
      do
        if [ -f ${OSD_DIR}/keyring ]; then
          break
        elif [ $i -eq 60 ]; then
          fail "Unable to get osd.${osd_id} keyring from ${HOSTNAME}."
        fi
        sleep 5
      done

      kubectl_scale_deployment osd=${osd_id} 0

      # Create a file containing the keyring
      OSD_KEYRING=$(cat ${OSD_DIR}/keyring | sed -n -e 's/^.*key = //p')
      cat > /tmp/osd.${osd_id}.keyring << EOF
    [osd.${osd_id}]
            key = ${OSD_KEYRING}
            caps mgr = "allow profile osd"
            caps mon = "allow profile osd"
            caps osd = "allow *"
    EOF

      # Ensures ceph has the correct OSD keyring
      while true
      do
        exec_ceph_cmd ceph auth import -i /tmp/osd.${osd_id}.keyring
        exec_ceph_cmd key ceph auth get-key osd.${osd_id}
        if [ "$key" == "${OSD_KEYRING}" ]; then
          break
        fi
        sleep ${TIME_RETRY}
      done

      kubectl_scale_deployment osd=${osd_id} 1
    done

    # If no OSD with the cluster fsid was found,
    # the recovery process should be stopped.
    if [ "${CLUSTER_HAS_OSD}" == false ]; then
      fail "No OSD belonging to the cluster was found on ${HOSTNAME}."
    fi

    echo "osd keyring updated completed successfully."
    exit 0

  mon_cleanup.sh: |-
    #!/bin/bash
    set -x

    source /tmp/mount/common.sh

    wait_for_status "cleaning-mon"

    kubectl_scale_deployment mon=${MON_NAME} 0

    rm -rf /var/lib/rook/data/mon-${MON_NAME}
    if [ "${HAS_MON_FLOAT}" == true ]; then
      rm -rf /var/lib/rook/mon-float/mon-float
    fi

    kubectl_scale_deployment mon=${MON_NAME} 1

    echo "mon cleaning completed successfully."
    exit 0

  mon_rollback.sh: |-
    #!/bin/bash
    set -x

    source /tmp/mount/common.sh

    wait_for_status "rolling-back-mon"

    # Get the names of the "stolen" mds and mgr
    exec_k8s_cmd MDS_NAME kubectl -n rook-ceph get pods -l app=rook-ceph-mds --field-selector spec.nodeName=${RECOVERY_HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mds"
    exec_k8s_cmd MGR_NAME kubectl -n rook-ceph get pods -l app=rook-ceph-mgr --field-selector spec.nodeName=${RECOVERY_HOSTNAME} --no-headers -o custom-columns=":metadata.labels.mgr"

    kubectl_scale_deployment mds=${MDS_NAME} 0
    kubectl_scale_deployment mgr=${MGR_NAME} 0
    kubectl_scale_deployment mon=${MON_NAME} 0

    rm -rf /var/lib/rook/mon-${MON_NAME}

    # Undo what was done in the monstore rebuild
    exec_k8s_cmd kubectl -n rook-ceph patch deployment rook-ceph-mon-${MON_NAME} -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "'"${HOSTNAME}"'"}}}}}'
    exec_k8s_cmd kubectl label nodes ${HOSTNAME} ceph-mgr-placement=enabled --overwrite
    exec_k8s_cmd kubectl label nodes ${HOSTNAME} ceph-mon-placement=enabled --overwrite
    exec_k8s_cmd kubectl label nodes ${RECOVERY_HOSTNAME} ceph-mgr-placement-
    exec_k8s_cmd kubectl label nodes ${RECOVERY_HOSTNAME} ceph-mon-placement-

    kubectl_scale_deployment mon=${MON_NAME} 1
    kubectl_scale_deployment mgr=${MGR_NAME} 1
    kubectl_scale_deployment mds=${MDS_NAME} 1

    echo "mon rollback completed successfully."
    exit 0

  log_collector.sh: |-
    #!/bin/bash
    set -x

    LOG_FILE="/var/log/ceph/restore.log"
    source /tmp/mount/common.sh

    wait_for_status "recovery-completed recovery-failed"

    # Wait for all jobs to complete.
    exec_k8s_cmd kubectl -n rook-ceph wait --for=condition=complete job -l app.kubernetes.io/part-of=rook-ceph-recovery --timeout=${TIME_WAIT_JOB_COMPLETE}

    rm -rf ${LOG_FILE}
    exec_k8s_cmd PODS_NAME kubectl -n rook-ceph get pods -l app.kubernetes.io/part-of=rook-ceph-recovery --no-headers -o custom-columns=":metadata.name"
    for POD_NAME in $PODS_NAME; do
      exec_k8s_cmd POD_STATUS kubectl -n rook-ceph get pod "$POD_NAME" -o=jsonpath='{.status.phase}'
      if [[ "$POD_STATUS" == "Running" || "$POD_STATUS" == "Succeeded" || "$POD_STATUS" == "Failed" ]]; then
        set +x
        echo -e "\n##############################\n${POD_NAME}\n##############################" >> ${LOG_FILE}
        exec_k8s_cmd kubectl -n rook-ceph logs $POD_NAME >> ${LOG_FILE}
        set -x
      fi
    done

    # If the recovery is complete, there is no need to keep the jobs.
    if check_status "recovery-completed"; then
      exec_k8s_cmd kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery
      exec_k8s_cmd kubectl -n rook-ceph wait --for=delete job -l app.kubernetes.io/part-of=rook-ceph-recovery --timeout=60s
      if [ $? -ne 0 ]; then
        exec_k8s_cmd kubectl -n rook-ceph delete jobs -l app.kubernetes.io/part-of=rook-ceph-recovery --grace-period=0 --force
      fi
      exec_k8s_cmd kubectl -n rook-ceph delete pods -l app.kubernetes.io/part-of=rook-ceph-recovery --grace-period=0 --force
    fi

    echo "logs collected successfully."

    set +x
    echo -e "\n##############################\nrook-ceph-recovery-log-collector\n##############################" >> ${LOG_FILE}
    exec_k8s_cmd kubectl -n rook-ceph logs -l app=rook-ceph-recovery-log-collector --tail=-1 >> ${LOG_FILE}
    exit 0

  status: "recovery-pending"

  failure: ""
