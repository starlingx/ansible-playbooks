---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-osd-keyring-update-$TARGET_HOSTNAME
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-osd-keyring-update
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-osd-keyring-update-$TARGET_HOSTNAME
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-osd-keyring-update
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
          path: /var/lib/ceph/data
          type: ""
      - name: tmp
        hostPath:
          path: /tmp/ceph
          type: ""
      - name: devices
        hostPath:
          path: /dev
          type: ""
      - name: run-udev
        hostPath:
          path: /run/udev
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
                | tee -a /var/log/rook-ceph/recovery-osd-keyring-update-provision-${TIMESTAMP}.log
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
          - name: tmp
            mountPath: /tmp/ceph
          - name: devices
            mountPath: /dev
          - name: run-udev
            mountPath: /run/udev
        - name: wait-ceph-ready
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -o pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              /bin/bash /tmp/mount/wait_ceph_ready.sh 2>&1 \
                | tee -a /var/log/rook-ceph/recovery-osd-keyring-update-wait-ceph-ready-${TIMESTAMP}.log
          volumeMounts:
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: ceph-config
            mountPath: /etc/ceph
          - name: rook-ceph-log
            mountPath: /var/log/rook-ceph
      containers:
        - name: osd-keyring-update
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -o pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              /bin/bash /tmp/mount/osd_keyring_update.sh 2>&1 \
                | tee -a /var/log/rook-ceph/recovery-osd-keyring-update-${TIMESTAMP}.log
          env:
          - name: HOSTNAME
            value: $TARGET_HOSTNAME
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - name: rook-data
            mountPath: /var/lib/rook
          - name: tmp
            mountPath: /tmp/ceph
          - name: devices
            mountPath: /dev
          - name: run-udev
            mountPath: /run/udev
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: ceph-config
            mountPath: /etc/ceph
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
          - name: rook-ceph-log
            mountPath: /var/log/rook-ceph
