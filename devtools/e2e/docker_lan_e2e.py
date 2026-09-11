#!/usr/bin/env python3
"""Cross-endpoint LAN E2E for the QMT stack.

Runs the real server/server.py (driven by devtools/fake_qmt) in one Docker
container and the real qmt_client in another, on a private bridge network, so
the interaction crosses two network namespaces and two IP addresses.

Opt-in: needs a running Docker daemon, and is NOT part of the default pytest
suite.

    python3 devtools/e2e/docker_lan_e2e.py

Exit codes: 0 pass (or SKIP when Docker is unavailable), 1 check failure,
2 setup failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
CONTAINER = "qmt-e2e-server"


def _run(cmd, check=True, timeout=None, env=None):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if check and proc.returncode != 0:
        sys.stderr.write("command failed: %s\n%s%s\n" % (" ".join(cmd), proc.stdout, proc.stderr))
        raise SystemExit(2)
    return proc


def _docker_available():
    if shutil.which("docker") is None:
        return False
    return _run(["docker", "info"], check=False).returncode == 0


def _wait_ready(target, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        logs = _run(["docker", "logs", target], check=False)
        if "listener ready" in (logs.stdout + logs.stderr):
            return True
        state = _run(["docker", "inspect", "-f", "{{.State.Running}}", target], check=False).stdout.strip()
        if state != "true":
            return False
        time.sleep(0.5)
    return False


def _parse():
    parser = argparse.ArgumentParser(description="Cross-endpoint LAN E2E over Docker")
    parser.add_argument("--token", default="lan-token")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--discovery-port", type=int, default=18081)
    parser.add_argument("--subnet", default="172.30.0.0/24")
    parser.add_argument("--server-ip", default="172.30.0.3")
    parser.add_argument("--client-ip", default="172.30.0.2")
    parser.add_argument("--network", default="qmt-e2e-net")
    parser.add_argument("--image", default="qmt-e2e-client:local")
    parser.add_argument("--base-image", default="python:3.12-slim")
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--keep", action="store_true", help="keep the container and network for debugging")
    parser.add_argument("--keep-image", action="store_true", help="keep the built image")
    return parser.parse_args()


def main():
    args = _parse()
    if not _docker_available():
        print("SKIP: docker daemon is not available")
        return 0

    try:
        _run(["docker", "rm", "-f", CONTAINER], check=False)
        _run(["docker", "network", "rm", args.network], check=False)
        _run(["docker", "network", "create", "--subnet", args.subnet, args.network])
        # DOCKER_BUILDKIT=0 keeps the legacy builder, which resolves FROM from the
        # local image instead of asking the registry for metadata every run.
        _run(
            ["docker", "build", "-t", args.image, "--build-arg", "BASE_IMAGE=" + args.base_image, HERE],
            env=dict(os.environ, DOCKER_BUILDKIT="0"),
        )

        _run([
            "docker", "run", "-d", "--name", CONTAINER,
            "--network", args.network, "--ip", args.server_ip,
            "-v", REPO_ROOT + ":/work", "-w", "/work",
            args.image, "python3", "-u", "devtools/run_fake_qmt.py",
            "--host", "0.0.0.0", "--port", str(args.port), "--token", args.token,
            "--allowed-hosts", "%s:%d" % (args.server_ip, args.port),
            "--discovery", "--discovery-port", str(args.discovery_port),
        ])

        if not _wait_ready(CONTAINER, args.ready_timeout):
            sys.stderr.write("server container did not become ready; logs:\n")
            sys.stderr.write(_run(["docker", "logs", CONTAINER], check=False).stdout)
            return 2

        print("server = %s (%s), client = %s (%s)" % (CONTAINER, args.server_ip, "qmt-e2e-client", args.client_ip))
        result = _run([
            "docker", "run", "--rm",
            "--network", args.network, "--ip", args.client_ip,
            "-v", REPO_ROOT + ":/work", "-w", "/work",
            "-e", "PYTHONPATH=/work/client/src",
            "-e", "QMT_E2E_SERVER_IP=" + args.server_ip,
            "-e", "QMT_E2E_PORT=" + str(args.port),
            "-e", "QMT_E2E_DISCOVERY_PORT=" + str(args.discovery_port),
            "-e", "QMT_E2E_TOKEN=" + args.token,
            args.image, "python3", "-u", "devtools/e2e/client_e2e.py",
        ], check=False)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    finally:
        if not args.keep:
            _run(["docker", "rm", "-f", CONTAINER], check=False)
            _run(["docker", "network", "rm", args.network], check=False)
            if not args.keep_image:
                _run(["docker", "rmi", args.image], check=False)


if __name__ == "__main__":
    sys.exit(main())
