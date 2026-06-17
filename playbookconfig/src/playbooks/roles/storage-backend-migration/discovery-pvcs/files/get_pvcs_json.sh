#!/bin/bash
# Outputs a JSON array of PVCs filtered by type (cephfs/general) with match flag
# Usage: get_pvcs_json.sh <regex>
REGEX_VALUE="$1"

kubectl get pvc -A \
    -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.storageClassName,VOLUMEMODE:.spec.volumeMode,SIZE:.spec.resources.requests.storage \
| awk -v dyn_regex="$REGEX_VALUE" '
    NR==1 { next }
    $3 ~ /^(cephfs|general)$/ {
        vol_mode = ($4 == "<none>" || $4 == "") ? "Filesystem" : $4
        printf "{\"namespace\":\"%s\",\"name\":\"%s\",\"type\":\"%s\",\"volume_mode\":\"%s\",\"requested_size\":\"%s\",\"match\":%s}\n",
            $1, $2,
            ($3 == "cephfs" ? "CephFS" : "RBD"),
            vol_mode,
            $5,
            ($2 ~ dyn_regex ? "true" : "false")
    }
' | awk 'BEGIN{printf "["} NR>1{printf ","} {printf $0} END{printf "]\n"}'
