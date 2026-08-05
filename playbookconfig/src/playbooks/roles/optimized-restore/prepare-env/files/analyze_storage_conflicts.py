#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Analyze conflicts between backup storage metadata and the
# factory-installed storage state.
#
# Classifies each detected conflict as:
#   - block:   Incompatible condition that prevents restore.
#   - warning: Mismatch that is non-fatal but should be noted.
#   - ignore:  Difference that is expected and safe to skip.
#
# Usage:
#   analyze_storage_conflicts.py <backup_metadata_json> \
#                                <factory_storage_backend>
#
# Arguments:
#   backup_metadata_json    - JSON string from detect_backup_storage_metadata.py
#   factory_storage_backend - 'rook-ceph' or 'lvm' (detected from flag files)
#
# Outputs JSON to stdout:
# {
#   "conflicts": [
#     {
#       "id": "unique-conflict-id",
#       "severity": "block|warning|ignore",
#       "category": "backend|filesystem|overrides|state",
#       "description": "Human-readable description",
#       "backup_value": "...",
#       "factory_value": "..."
#     }, ...
#   ],
#   "summary": {
#     "total": N,
#     "blocking": N,
#     "warnings": N,
#     "ignored": N
#   },
#   "restore_allowed": true|false
# }

import json
import sys


# The database stores the rook-ceph backend type as 'ceph-rook',
# while the playbook fact factory_storage_backend uses 'rook-ceph'
# (derived from flag file .node_rook_configured). Normalize both
# to a canonical form for comparison.
BACKEND_ALIASES = {
    'ceph-rook': 'rook-ceph',
}


def normalize_backend(value):
    """Normalize backend name to canonical form."""
    if value is None:
        return None
    return BACKEND_ALIASES.get(value, value)


def analyze_backend_conflicts(backup_metadata, factory_backend):
    """Check backend type compatibility.

    Rules:
      - backend type mismatch (rook-ceph vs lvm) -> block
      - backup has no configured backend -> block
      - backup backend state is not 'configured' -> warning
    """
    conflicts = []
    primary = normalize_backend(backup_metadata.get('primary_backend'))
    factory_backend = normalize_backend(factory_backend)

    if primary is None:
        conflicts.append({
            'id': 'backend-not-detected',
            'severity': 'block',
            'category': 'backend',
            'description': (
                'No configured storage backend found in backup. '
                'Cannot determine restore path.'),
            'backup_value': 'none',
            'factory_value': factory_backend,
        })
        return conflicts

    if primary != factory_backend:
        conflicts.append({
            'id': 'backend-type-mismatch',
            'severity': 'block',
            'category': 'backend',
            'description': (
                'Storage backend type mismatch. '
                'Cross-backend restore is not supported.'),
            'backup_value': primary,
            'factory_value': factory_backend,
        })
        return conflicts

    # Check for non-configured backends in backup
    for b in backup_metadata.get('storage_backends', []):
        if b['backend'] == primary and b['state'] != 'configured':
            conflicts.append({
                'id': 'backend-state-not-configured',
                'severity': 'warning',
                'category': 'state',
                'description': (
                    "Backup storage backend '%s' is in state '%s' "
                    "instead of 'configured'. Restore will proceed "
                    "but backend may require manual intervention."
                    % (b['name'], b['state'])),
                'backup_value': b['state'],
                'factory_value': 'configured',
            })

    return conflicts


def analyze_override_conflicts(backup_metadata, factory_backend):
    """Check helm override compatibility.

    Rules:
      - rook-ceph user-overrides present in backup -> ignore
        (they are preserved through DB restore)
      - backup expects rook-ceph overrides but factory is lvm -> block
        (covered by backend mismatch, but explicit for clarity)
    """
    conflicts = []
    factory_backend = normalize_backend(factory_backend)
    rook_ov = backup_metadata.get('rook_ceph_overrides', {})

    if rook_ov.get('has_user_overrides') and factory_backend == 'lvm':
        conflicts.append({
            'id': 'rook-overrides-on-lvm-factory',
            'severity': 'block',
            'category': 'overrides',
            'description': (
                'Backup contains rook-ceph user-overrides but factory '
                'storage backend is LVM CSI. Overrides cannot be applied.'),
            'backup_value': 'rook-ceph user-overrides present',
            'factory_value': 'lvm',
        })
    elif rook_ov.get('has_user_overrides') and factory_backend == 'rook-ceph':
        charts = rook_ov.get('charts_with_user_overrides', [])
        conflicts.append({
            'id': 'rook-overrides-preserved',
            'severity': 'ignore',
            'category': 'overrides',
            'description': (
                'Backup contains rook-ceph user-overrides for charts: '
                '%s. They will be preserved through DB restore.'
                % ', '.join(charts)),
            'backup_value': '%d charts with overrides' % len(charts),
            'factory_value': 'rook-ceph (compatible)',
        })

    return conflicts


def analyze_services_conflicts(backup_metadata, factory_backend):
    """Check storage services compatibility.

    Rules:
      - Backup backend provides services not expected for the
        factory backend type -> warning
    """
    conflicts = []
    factory_backend = normalize_backend(factory_backend)
    expected_services = {
        'rook-ceph': 'ceph',
        'lvm': 'block-storage',
    }

    for b in backup_metadata.get('storage_backends', []):
        if b['state'] != 'configured':
            continue
        services = b.get('services', '')
        expected = expected_services.get(factory_backend, '')
        if expected and expected not in services:
            conflicts.append({
                'id': 'backend-services-mismatch',
                'severity': 'warning',
                'category': 'state',
                'description': (
                    "Backup backend '%s' provides services '%s', "
                    "expected '%s' for %s backend."
                    % (b['name'], services, expected, factory_backend)),
                'backup_value': services,
                'factory_value': expected,
            })

    return conflicts


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: %s <backup_metadata_json> "
            "<factory_storage_backend>"
            % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    try:
        backup_metadata = json.loads(sys.argv[1])
    except (json.JSONDecodeError, ValueError) as e:
        print("Error: invalid JSON input: %s" % e, file=sys.stderr)
        sys.exit(1)

    factory_backend = sys.argv[2]

    all_conflicts = []
    all_conflicts.extend(
        analyze_backend_conflicts(backup_metadata, factory_backend))
    all_conflicts.extend(
        analyze_override_conflicts(backup_metadata, factory_backend))
    all_conflicts.extend(
        analyze_services_conflicts(backup_metadata, factory_backend))

    blocking = [c for c in all_conflicts if c['severity'] == 'block']
    warnings = [c for c in all_conflicts if c['severity'] == 'warning']
    ignored = [c for c in all_conflicts if c['severity'] == 'ignore']

    result = {
        'conflicts': all_conflicts,
        'summary': {
            'total': len(all_conflicts),
            'blocking': len(blocking),
            'warnings': len(warnings),
            'ignored': len(ignored),
        },
        'restore_allowed': len(blocking) == 0,
    }

    print(json.dumps(result))


if __name__ == '__main__':
    main()
