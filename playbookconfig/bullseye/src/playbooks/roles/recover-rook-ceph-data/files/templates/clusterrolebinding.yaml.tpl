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
