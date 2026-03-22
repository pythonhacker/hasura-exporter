#!/usr/bin/env python3

"""
Custom Hasura exporter in Python for Prometheus

Exposes:

- hasura_healthy - 1 or 0
- hasura_metadata_consistency_status - 1 or 0
- hasura_metadata_inconsistent_object{type, schema, table, name, source}

"""

import os
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

## Required env variables
HASURA_ADMIN_SECRET = os.getenv("HASURA_GRAPHQL_ADMIN_SECRET")
## Optional
HASURA_URL = os.getenv("HASURA_URL", "http://localhost:8080")
TIMEOUT = 3

def sanitize(value):
    """Escape label values for Prometheus"""
    if value is None:
        return "unknown"
    return str(value).replace('"', '\\"')

def check_health():
    try:
        resp = requests.get(f"{HASURA_URL}/healthz", timeout=TIMEOUT)
        return 1 if resp.status_code == 200 else 0
    except Exception:
        return 0

def check_metadata():
    """
    Returns:
    - status (1=consistent, 0=inconsistent, -1=error)
    - list of inconsistent objects (parsed)
    """
    try:
        headers = {
            "Content-Type": "application/json",
        }

        if HASURA_ADMIN_SECRET:
            headers["x-hasura-admin-secret"] = HASURA_ADMIN_SECRET

        payload = {
            "type": "get_inconsistent_metadata",
            "args": {}
        }

        resp = requests.post(
            f"{HASURA_URL}/v1/metadata",
            json=payload,
            headers=headers,
            timeout=TIMEOUT
        )

        if resp.status_code != 200:
            return -1, []

        data = resp.json()
        inconsistent = data.get("inconsistent_objects", [])

        status = 1 if len(inconsistent) == 0 else 0
        return status, inconsistent

    except Exception:
        return -1, []


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        health = check_health()
        metadata_status, inconsistent_objects = check_metadata()

        output = []

        # --- Core metrics ---
        output.append("# HELP hasura_healthy Hasura health status (1=up, 0=down)")
        output.append("# TYPE hasura_healthy gauge")
        output.append(f"hasura_healthy {health}")

        output.append("# HELP hasura_metadata_consistency_status Metadata consistency (1=consistent, 0=inconsistent, -1=error)")
        output.append("# TYPE hasura_metadata_consistency_status gauge")
        output.append(f"hasura_metadata_consistency_status {metadata_status}")

        output.append("# HELP hasura_metadata_inconsistent_object Inconsistent metadata objects")
        output.append("# TYPE hasura_metadata_inconsistent_object gauge")

        # --- Per-object metrics ---
        for obj in inconsistent_objects:
            obj_type = sanitize(obj.get("type"))

            definition = obj.get("definition", {})
            table_info = definition.get("table", {})

            schema = sanitize(table_info.get("schema"))
            table = sanitize(table_info.get("name"))
            relation_name = sanitize(definition.get("name"))
            source = sanitize(definition.get("source"))

            output.append(
                f'hasura_metadata_inconsistent_object'
                f'{{type="{obj_type}",schema="{schema}",table="{table}",name="{relation_name}",source="{source}"}} 1'
            )

        # --- Final output ---
        response = "\n".join(output) + "\n"

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(response.encode())

def run():
    port = int(os.getenv("PORT", "9114"))
    server = HTTPServer(("0.0.0.0", port), MetricsHandler)
    print(f"Hasura exporter running on :{port}/metrics")
    server.serve_forever()

if __name__ == "__main__":
    run()
