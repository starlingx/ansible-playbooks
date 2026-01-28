#!/usr/bin/env python3
"""
remove_docker_registry_service_params.py

Removes all serviceParameters entries where service == "docker" and section contains "registry"
from every System resource (in namespace deployment) in a multi-doc YAML.

Usage:
    python3 remove_docker_registry_service_params.py subcloud1-deploy-standard.yaml > cleaned.yaml
"""

import yaml
import sys


def clean_system_service_params(doc):
    """
    If this is a System resource, remove entries where service == 'docker' and section contains 'registry'.
    Returns the (possibly modified) document.
    """
    if not isinstance(doc, dict):
        return doc

    if (doc.get('kind') == 'System' and
            doc.get('apiVersion', '').startswith('starlingx.windriver.com/') and
            doc.get('metadata', {}).get('namespace') == 'deployment'):

        spec = doc.get('spec', {})
        if not isinstance(spec, dict):
            return doc

        params = spec.get('serviceParameters')
        if not isinstance(params, list):
            return doc

        original_count = len(params)
        cleaned_params = [
            p for p in params
            if not (isinstance(p, dict) and
                    p.get('service') == 'docker' and
                    'registry' in p.get('section', ''))
        ]

        if len(cleaned_params) < original_count:
            name = doc.get('metadata', {}).get('name', '(unknown)')
            removed = original_count - len(cleaned_params)
            print(f"Removed {removed} docker registry parameter(s) from System {name}", file=sys.stderr)
            spec['serviceParameters'] = cleaned_params

    return doc


def main(input_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        docs = list(yaml.safe_load_all(f))

    updated_docs = []
    modified_count = 0

    for doc in docs:
        if doc is None:
            continue

        new_doc = clean_system_service_params(doc)
        updated_docs.append(new_doc)

        # Very simple change detection (reference equality not reliable after yaml load)
        if new_doc is not doc or 'serviceParameters' in new_doc.get('spec', {}):
            modified_count += 1 if new_doc is not doc else 0

    total_systems = sum(1 for d in updated_docs if d and d.get('kind') == 'System')
    print(f"Processed {len(updated_docs)} documents, "
          f"found {total_systems} System resource(s), "
          f"cleaned {modified_count} document(s).", file=sys.stderr)

    yaml.safe_dump_all(
        updated_docs,
        sys.stdout,
        default_flow_style=False,
        sort_keys=False,
        explicit_start=True,
        allow_unicode=True,
        width=4096,           # try to keep long lines readable
        indent=2
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 remove_docker_registry_service_params.py input.yaml > output.yaml", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
