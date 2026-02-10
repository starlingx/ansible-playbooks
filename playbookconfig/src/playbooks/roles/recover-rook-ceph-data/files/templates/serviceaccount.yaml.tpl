---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rook-ceph-recovery
  namespace: rook-ceph
imagePullSecrets:
  - name: default-registry-key
