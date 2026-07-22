---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-operator
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-operator
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-operator
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-operator
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
                | tee -a /var/log/rook-ceph/recovery-operator-provision-${TIMESTAMP}.log
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
      containers:
        - name: operator
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -o pipefail
              TIMESTAMP=$(date +%Y%m%d_%H%M%S)
              /bin/bash /tmp/mount/operator.sh 2>&1 \
                | tee -a /var/log/rook-ceph/recovery-operator-${TIMESTAMP}.log
          env:
          - name: RECOVERY_TYPE
            value: $RECOVERY_TYPE
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
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: ceph-config
            mountPath: /etc/ceph
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
          - name: rook-ceph-log
            mountPath: /var/log/rook-ceph
