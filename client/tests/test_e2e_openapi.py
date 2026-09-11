"""OpenAPI / Swagger docs tests against the real server.py via FakeQMT."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from test_e2e_fake_qmt import _load_fake_qmt_server


def _get(url, token=None):
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.getcode(), response.headers.get("Content-Type"), body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type"), exc.read().decode("utf-8")


def test_openapi_document_matches_routes():
    FakeQMTServer = _load_fake_qmt_server()
    server = FakeQMTServer(token="docs-token", port=0).start()
    try:
        status, content_type, body = _get("%s/openapi.json" % server.base_url)
        assert status == 200
        assert content_type.startswith("application/json")
        spec = json.loads(body)
        assert spec["openapi"].startswith("3.")
        assert "bearerAuth" in spec["components"]["securitySchemes"]
        assert "qmtToken" in spec["components"]["securitySchemes"]
        for path in ("/order", "/cancel", "/can-cancel", "/candles", "/positions", "/ws"):
            if path == "/ws":
                assert path not in spec["paths"]
            else:
                assert path in spec["paths"]

        # every $ref must resolve to a declared component schema
        schemas = set(spec["components"]["schemas"])
        refs = []

        def collect(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    refs.append(node["$ref"])
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(spec["paths"])
        assert refs, "spec should use component schema refs"
        for ref in refs:
            assert ref.startswith("#/components/schemas/"), ref
            assert ref.rsplit("/", 1)[1] in schemas, ref

        status, content_type, body = _get("%s/docs" % server.base_url)
        assert status == 200
        assert content_type.startswith("text/html")
        assert "SwaggerUIBundle" in body

        status, _, _ = _get("%s/health" % server.base_url)
        assert status == 401

        status, _, body = _get("%s/" % server.base_url, token="docs-token")
        assert status == 200
        endpoints = set(json.loads(body)["endpoints"])
        spec_paths = set(spec["paths"])
        assert endpoints - spec_paths <= {"/ws"}
        assert spec_paths - endpoints == set()
    finally:
        server.stop()
