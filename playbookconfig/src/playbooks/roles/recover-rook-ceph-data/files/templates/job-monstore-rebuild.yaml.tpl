---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-monstore-rebuild-$TARGET_HOSTNAME
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-monstore-rebuild
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-monstore-rebuild-$TARGET_HOSTNAME
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-monstore-rebuild
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
      - name: rook-data
        hostPath:
          path: /var/lib/ceph
          type: ""
      - name: devices
        hostPath:
          path: /dev
          type: ""
      - name: run-udev
        hostPath:
          path: /run/udev
          type: ""
      - name: tmp
        hostPath:
          path: /tmp/ceph
          type: ""
      - name: rook-ceph-recovery
        configMap:
          name: rook-ceph-recovery
          defaultMode: 0555
      - name: ceph-config
        emptyDir: {}
      - name: kube-config
        hostPath:
          path: /etc/kubernetes/admin.conf
      - name: rook-ceph-log
        hostPath:
          path: /var/lib/ceph/data/rook-ceph/log/
          type: DirectoryOrCreate
      initContainers:
        - name: provision
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -o pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              /bin/bash /tmp/mount/provision.sh 2>&1 \
                | tee -a /var/log/rook-ceph/recovery-monstore-rebuild-provision-${TIMESTAMP}.log
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
          volumeMounts:
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: ceph-config
            mountPath: /etc/ceph
          - name: rook-ceph-log
            mountPath: /var/log/rook-ceph
        - name: osd-data
          image: $CEPH_IMAGE
          command: ["/bin/bash", "-c", "/usr/sbin/ceph-volume raw list > /tmp/ceph/osd_data"]
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - name: rook-data
            mountPath: /var/lib/rook
          - name: devices
            mountPath: /dev
          - name: run-udev
            mountPath: /run/udev
          - name: tmp
            mountPath: /tmp/ceph
      containers:
        - name: monstore-rebuild
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -o pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              /bin/bash /tmp/mount/monstore_rebuild.sh 2>&1 \
                | tee -a /var/log/rook-ceph/recovery-monstore-rebuild-${TIMESTAMP}.log
          env:
          - name: MONMAP
            value: $MONMAP_BINARY
          - name: RECOVERY_TYPE
            value: $RECOVERY_TYPE
          - name: HOSTNAME
            value: $TARGET_HOSTNAME
          - name: MON_NAME
            value: $TARGET_MON_NAME
          - name: MON_HOSTNAME
            value: $TARGET_MON_HOSTNAME
          - name: HAS_MON_FLOAT
            value: "$HAS_MON_FLOAT"
          - name: HAS_OSD_KEYRING_UPDATE_JOB
            value: "$HAS_OSD_KEYRING_UPDATE"
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - name: rook-data
            mountPath: /var/lib/rook
          - name: devices
            mountPath: /dev
          - name: run-udev
            mountPath: /run/udev
          - name: tmp
            mountPath: /tmp/ceph
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: ceph-config
            mountPath: /etc/ceph
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
          - name: rook-ceph-log
            mountPath: /var/log/rook-ceph
