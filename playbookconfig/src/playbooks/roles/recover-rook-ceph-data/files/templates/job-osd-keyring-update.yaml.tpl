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
      initContainers:
        - name: init
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: [ "/bin/bash", "/tmp/mount/provision.sh" ]
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
        - name: osd-data
          image: $CEPH_IMAGE
          command: [ "/bin/bash", "-c", "/usr/sbin/ceph-volume raw list > /tmp/ceph/osd_data" ]
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
      containers:
        - name: osd-keyring-update
          image: $CEPH_CONFIG_HELPER_IMAGE
          command: [ "/bin/bash", "/tmp/mount/osd_keyring_update.sh" ]
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
