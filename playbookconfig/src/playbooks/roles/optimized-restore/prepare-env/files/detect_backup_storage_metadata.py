#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Detect and extract storage-related metadata from a backup's
# postgres dump file for factory restore.
#
# Detects:
#   - Storage backend configuration (storage_backend table)
#   - Rook-ceph helm user_overrides (helm_overrides table)
#   - Controller filesystem entries (controller_fs table)
#
# The dump uses multi-line INSERT statements (user_overrides can
# contain embedded YAML with newlines). This script reassembles
# multi-line statements before parsing.
#
# Usage: detect_backup_storage_metadata.py <sysinv_postgres_dump_file>
#
# Outputs JSON to stdout with detected metadata.

import json
import sys


def iter_insert_statements(filepath, table_name):
    """Iterate over complete INSERT statements for a table.

    Handles multi-line INSERT statements by accumulating lines
    until a closing ');' is found. Streams line-by-line to avoid
    loading the entire file into memory.

    Yields complete INSERT statement strings.
    """
    marker = "INSERT INTO public.%s VALUES" % table_name
    accumulating = False
    buffer = []

    with open(filepath) as f:
        for line in f:
            if not accumulating:
                if marker in line:
                    buffer = [line]
                    if line.rstrip().endswith(');'):
                        yield ''.join(buffer)
                        buffer = []
                    else:
                        accumulating = True
            else:
                buffer.append(line)
                if line.rstrip().endswith(');'):
                    yield ''.join(buffer)
                    buffer = []
                    accumulating = False


def parse_insert_values(statement):
    """Parse a complete INSERT statement into positional values.

    Handles quoted strings with embedded commas, parentheses,
    and newlines. Returns list of raw string values.
    """
    # Find the VALUES ( ... ); portion
    idx = statement.find('VALUES (')
    if idx == -1:
        return None
    # Skip "VALUES ("
    content = statement[idx + 8:]
    # Remove trailing ");\n" or ");"
    if content.rstrip().endswith(');'):
        content = content.rstrip()[:-2]

    # Parse respecting quoted strings
    values = []
    current = []
    in_quote = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_quote:
            if ch == "'" and i + 1 < len(content) and content[i + 1] == "'":
                # Escaped quote ''
                current.append("''")
                i += 2
                continue
            elif ch == "'":
                in_quote = False
                current.append(ch)
            else:
                current.append(ch)
        else:
            if ch == "'":
                in_quote = True
                current.append(ch)
            elif ch == ',' and not in_quote:
                values.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)
        i += 1
    # Last value
    values.append(''.join(current).strip())
    return values


def strip_quotes(val):
    """Remove surrounding single quotes from a SQL value."""
    if val and val.startswith("'") and val.endswith("'"):
        return val[1:-1].replace("''", "'")
    return val


def extract_storage_backends(filepath):
    """Extract storage_backend table entries.

    Real column order (from dump inspection):
    0=created_at, 1=updated_at, 2=deleted_at, 3=id, 4=uuid,
    5=backend, 6=state, 7=task, 8=forisystemid, 9=services,
    10=capabilities, 11=name
    """
    backends = []
    for stmt in iter_insert_statements(filepath, 'storage_backend'):
        cols = parse_insert_values(stmt)
        if cols and len(cols) >= 12:
            backends.append({
                'backend': strip_quotes(cols[5]),
                'name': strip_quotes(cols[11]),
                'state': strip_quotes(cols[6]),
                'services': strip_quotes(cols[9]),
            })
    return backends


def extract_helm_overrides_for_app(filepath, app_name):
    """Extract helm_overrides entries for a given app.

    First finds the app_id from kube_app table, then extracts
    helm_overrides rows matching that app_id.

    kube_app real column order:
    0=created_at, 1=updated_at, 2=id, 3=name, 4=app_version,
    5=manifest_name, 6=manifest_file, 7=status, 8=progress,
    9=active, 10=recovery_attempts, 11=app_metadata, 12=deleted_at

    helm_overrides real column order:
    0=created_at, 1=updated_at, 2=deleted_at, 3=id, 4=name,
    5=namespace, 6=user_overrides, 7=app_id, 8=attributes
    """
    # Find app_id
    app_id = None
    for stmt in iter_insert_statements(filepath, 'kube_app'):
        cols = parse_insert_values(stmt)
        if cols and len(cols) >= 4:
            if strip_quotes(cols[3]) == app_name:
                app_id = strip_quotes(cols[2])
                break

    if app_id is None:
        return []

    # Extract overrides
    overrides = []
    for stmt in iter_insert_statements(filepath, 'helm_overrides'):
        cols = parse_insert_values(stmt)
        if cols and len(cols) >= 8:
            line_app_id = strip_quotes(cols[7])
            if line_app_id == app_id:
                user_ov = strip_quotes(cols[6])
                if user_ov in ('NULL', '', 'None', None):
                    user_ov = None
                has_ov = user_ov is not None
                overrides.append({
                    'chart_name': strip_quotes(cols[4]),
                    'namespace': strip_quotes(cols[5]),
                    'has_user_overrides': has_ov,
                    'user_overrides': user_ov if has_ov else None,
                })
    return overrides


def extract_controller_fs(filepath):
    """Extract controller_fs entries.

    Real column order:
    0=created_at, 1=updated_at, 2=deleted_at, 3=id, 4=uuid,
    5=forisystemid, 6=state, 7=name, 8=size, 9=logical_volume,
    10=replicated, 11=supported_functions
    """
    filesystems = []
    for stmt in iter_insert_statements(filepath, 'controller_fs'):
        cols = parse_insert_values(stmt)
        if cols and len(cols) >= 10:
            size_raw = strip_quotes(cols[8])
            size = int(size_raw) if size_raw not in ('NULL', '', None) else 0
            filesystems.append({
                'name': strip_quotes(cols[7]),
                'size': size,
                'logical_volume': strip_quotes(cols[9]),
            })
    return filesystems


def main():
    if len(sys.argv) != 2:
        print("Usage: %s <sysinv_postgres_dump_file>"
              % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    dump_file = sys.argv[1]

    storage_backends = extract_storage_backends(dump_file)
    rook_overrides = extract_helm_overrides_for_app(
        dump_file, 'rook-ceph')
    controller_fs = extract_controller_fs(dump_file)

    # Determine primary backend type
    primary_backend = None
    for b in storage_backends:
        if b['state'] == 'configured':
            primary_backend = b['backend']
            break

    # Summarize user overrides
    charts_with_user_overrides = [
        o['chart_name'] for o in rook_overrides
        if o['has_user_overrides']
    ]

    # Build user_overrides map for preservation
    user_overrides_map = {}
    for o in rook_overrides:
        if o['has_user_overrides']:
            user_overrides_map[o['chart_name']] = o['user_overrides']

    result = {
        'storage_backends': storage_backends,
        'primary_backend': primary_backend,
        'rook_ceph_overrides': {
            'total_charts': len(rook_overrides),
            'has_user_overrides': len(charts_with_user_overrides) > 0,
            'charts_with_user_overrides': charts_with_user_overrides,
            'user_overrides_data': user_overrides_map,
        },
        'controller_filesystems': controller_fs,
    }

    print(json.dumps(result))


if __name__ == '__main__':
    main()
