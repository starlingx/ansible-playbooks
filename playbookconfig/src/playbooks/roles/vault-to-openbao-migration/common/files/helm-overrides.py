#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Print one chart's user or system Helm overrides as stored by sysinv.
`system helm-override-show` has no machine-readable output, so this reads them through
cgtsclient with the OS_* credentials from the environment (openrc). stdout: the overrides
YAML ('' when none). Exit: 0 ok / 2 usage / 4 read failed."""
import argparse
import os
import sys
from typing import Any, Callable, List, Optional

EXIT_READ = 4
FIELDS = {"user": "user_overrides", "system": "system_overrides"}

# () -> client. Injectable so tests need no platform.
ClientFactory = Callable[[], Any]


def platform_client() -> Any:
    """Build a sysinv client from the openrc environment."""
    from cgtsclient import client as cgts_client
    env = os.environ
    return cgts_client.get_client(
        "1",
        os_username=env["OS_USERNAME"],
        os_password=env["OS_PASSWORD"],
        os_auth_url=env["OS_AUTH_URL"],
        os_project_name=env["OS_PROJECT_NAME"],
        os_project_domain_name=env["OS_PROJECT_DOMAIN_NAME"],
        os_user_domain_name=env["OS_USER_DOMAIN_NAME"],
        os_region_name=env["OS_REGION_NAME"],
        os_service_type="platform",
        os_endpoint_type="internal")


def read_overrides(client: Any, app: str, chart: str, namespace: str, field: str) -> str:
    """Return the overrides YAML of one field, '' when the chart has none."""
    obj = client.helm.get_overrides(app, chart, namespace)
    value: Optional[str] = getattr(obj, FIELDS[field], None)
    return value or ""


def main(argv: List[str], factory: ClientFactory = platform_client) -> int:
    """Entry point: print the overrides and return the exit code."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("app")
    p.add_argument("chart")
    p.add_argument("namespace")
    p.add_argument("field", choices=sorted(FIELDS))
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        text = read_overrides(factory(), args.app, args.chart, args.namespace, args.field)
    # cgtsclient raises its own and keystoneauth exception types; any failure is a read failure.
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write("reading %s overrides of %s/%s failed: %s: %s\n"
                         % (args.field, args.app, args.chart, type(exc).__name__, exc))
        return EXIT_READ
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
