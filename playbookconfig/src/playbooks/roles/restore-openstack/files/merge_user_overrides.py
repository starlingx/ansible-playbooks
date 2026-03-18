#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import copy
import re
import sys
import yaml


def parse_yaml(text):
    """
    Parse a YAML string into a Python object.

    Args:
        text: The YAML string to parse.
    """
    if not text or text.strip() in ("", "NULL"):
        return {}
    try:
        return yaml.safe_load(text) or {}
    except Exception:
        return {}


def deep_merge(base, override):
    """
    Recursively merges two dictionaries, with values from override
    taking precedence.

    Args:
        base: The base dictionary to merge into.
        override: The dictionary whose values will override or extend the base.
    """
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def escape_sql(value):
    return value.replace("'", "''")


def unwrap(val):
    if not val or val.strip() == "NULL":
        return None
    val = val.strip()
    if val.upper().startswith("E'") and val.endswith("'"):
        val = val[2:-1].replace("''", "'").replace("\\\\", "\\")
    elif val.startswith("'") and val.endswith("'"):
        val = val[1:-1].replace("''", "'")
    return val


def parse_sql_updates(sql):
    """
    Parse update statements on helm_overrides table and returns
    a mapping of names to their system_overrides and user_overrides.

    Args:
        sql: SQL string containing update statements.
    """
    # quote_literal() uses E'...' when the value contains backslashes.
    # The bellow regex handles both plain ('...') and E-quoted (E'...') strings.
    # Ref: https://www.postgresql.org/docs/14/sql-syntax-lexical.html#SQL-SYNTAX-STRINGS-ESCAPE
    quoted = r"(?:E)?'(?:''|\\.|[^'])*'(?!')"
    pattern = re.compile(
        r"update\s+helm_overrides\s+set\s+"
        r"system_overrides=(NULL|" + quoted + r"),\s*"
        r"user_overrides=(NULL|" + quoted + r")\s*"
        r"where\s+name='([^']+)'",
        re.IGNORECASE | re.DOTALL,
    )
    result = {}
    for system, user, name in pattern.findall(sql):
        result[name] = {
            "system_overrides": unwrap(system),
            "user_overrides": unwrap(user),
        }
    return result


def main():
    incoming_file, current_file, output_file = sys.argv[1:4]

    with open(incoming_file) as f:
        incoming = parse_sql_updates(f.read())

    with open(current_file) as f:
        current = parse_sql_updates(f.read())

    output = []

    for name, inc in incoming.items():
        cur = current.get(name, {})

        inc_user = parse_yaml(inc.get("user_overrides"))
        cur_user = parse_yaml(cur.get("user_overrides"))

        merged = deep_merge(inc_user, cur_user)

        user_sql = (
            "'" + escape_sql(
                yaml.safe_dump(
                    merged,
                    default_flow_style=False,
                    sort_keys=False
                    )
                ) + "'"
            if merged else "NULL"
        )

        sys_val = cur.get("system_overrides") or inc.get("system_overrides")
        system_sql = "'" + escape_sql(sys_val) + "'" if sys_val else "NULL"

        output.append(
            f"update helm_overrides set system_overrides={system_sql}, "
            f"user_overrides={user_sql} where name='{name}' and namespace='openstack';"
        )

    with open(output_file, "w") as f:
        f.write("\n".join(output))


if __name__ == "__main__":
    main()
