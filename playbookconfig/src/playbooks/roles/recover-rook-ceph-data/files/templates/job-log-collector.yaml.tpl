---
apiVersion: batch/v1
kind: Job
metadata:
  name: rook-ceph-recovery-log-collector
  namespace: rook-ceph
  labels:
    app: rook-ceph-recovery-log-collector
spec:
  ttlSecondsAfterFinished: 30
  template:
    metadata:
      name: rook-ceph-recovery-log-collector
      namespace: rook-ceph
      labels:
        app: rook-ceph-recovery-log-collector
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
      - name: ceph-log
        hostPath:
          path: /var/log/ceph
          type: ""
      - name: rook-ceph-recovery
        configMap:
          name: rook-ceph-recovery
          defaultMode: 0555
      - name: kube-config
        hostPath:
          path: /etc/kubernetes/admin.conf
      containers:
        - name: log-collector
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: [ "/bin/bash", "/tmp/mount/log_collector.sh" ]
          volumeMounts:
          - name: ceph-log
            mountPath: /var/log/ceph
          - name: rook-ceph-recovery
            mountPath: /tmp/mount
          - name: kube-config
            mountPath: /etc/kubernetes/admin.conf
            readOnly: true
