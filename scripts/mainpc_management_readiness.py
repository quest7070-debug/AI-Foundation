"""Fixed owner direct-link observations, without credentials or host effects."""
from __future__ import annotations

import http.client
import json
import socket


def management_readiness():
    """Reachability is not authentication or permission to execute commands."""
    host = "10.0.1.1"
    ports = {}
    for name, port in (("ssh", 22), ("winrm_http", 5985), ("winrm_https", 5986)):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                ports[name] = "REACHABLE"
        except OSError:
            ports[name] = "UNREACHABLE"
    health = {"status": "UNAVAILABLE"}
    connection = http.client.HTTPConnection(host, 18080, timeout=2)
    try:
        connection.request("GET", "/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status == 200 and len(raw) <= 4096:
            doc = json.loads(raw)
            if type(doc) is dict and type(doc.get("api_key")) is bool:
                health = {"status": "OBSERVED", "auth_enabled": doc["api_key"]}
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return {"management_ports": ports, "strata_health": health,
            "credential_attempts": 0, "model_calls": 0,
            "note": "Port reachability does not establish an authenticated management session"}
