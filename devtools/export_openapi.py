#!/usr/bin/env python3
"""Dump the OpenAPI document to stdout (or a file) without running the server.

    python3 devtools/export_openapi.py > openapi.json
"""

import json
import os
import sys

_SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server')
sys.path.insert(0, _SERVER_DIR)

from server_openapi import build_openapi_spec


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    text = json.dumps(build_openapi_spec(), ensure_ascii=False, indent=2, sort_keys=True)
    if target:
        with open(target, 'w', encoding='utf-8') as handle:
            handle.write(text + '\n')
    else:
        sys.stdout.write(text + '\n')


if __name__ == '__main__':
    main()
