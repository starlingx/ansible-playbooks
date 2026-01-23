---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-mon-$TARGET_MON_NAME-cleanup-$TARGET_HOSTNAME
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-mon-cleanup
    app.kubernetes.io/part-of: rook-ceph-recovery
spec:
  template:
    metadata:
      name: rook-ceph-recovery-mon-$TARGET_MON_NAME-cleanup-$TARGET_HOSTNAME
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-mon-cleanup
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
      - name: rook-ceph-recovery
        configMap:
          name: rook-ceph-recovery
          defaultMode: 0555
      - name: kube-config
        hostPath:
          path: /etc/kubernetes/admin.conf
      containers:
        - name: mon-cleanup
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: [ "/bin/bash", "/tmp/mount/mon_cleanup.sh" ]
          env:
          - name: HOSTNAME
            value: $TARGET_HOSTNAME
          - name: MON_NAME
            value: $TARGET_MON_NAME
          - name: HAS_MON_FLOAT
            value: "$HAS_MON_FLOAT"
          securityContext:
            privileged: true
            readOnlyRootFilesystem: false
            runAsUser: 0
          volumeMounts:
          - name: rook-data
            mountPath: /var/lib/rook
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
