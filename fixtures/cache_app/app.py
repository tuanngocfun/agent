"""Small cache-writing fixture. The harness owns the independent test probes."""

import hashlib
import json
import os
import signal
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class CacheHandler(BaseHTTPRequestHandler):
    cache_dir = ""

    def _respond(self, code, payload):
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._respond(200, {"ready": True})
        if url.path != "/compute":
            return self._respond(404, {"error": "Unknown endpoint"})
        values = parse_qs(url.query).get("value", [])
        if len(values) != 1 or len(values[0]) > 1024:
            return self._respond(400, {"error": "Supply one value of at most 1024 characters"})
        result = hashlib.sha256(values[0].encode()).hexdigest()
        path = os.path.join(self.cache_dir, result + ".txt")
        cached = os.path.exists(path)
        try:
            if cached:
                with open(path, encoding="utf-8") as handle:
                    result = handle.read()
            else:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(result)
        except OSError as exc:
            return self._respond(500, {"error": str(exc)})
        self._respond(200, {"result": result, "cached": cached})


def main() -> int:
    # PID 1 needs a registered TERM handler for Kubernetes graceful termination.
    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    cache = os.environ.get("CACHE_DIR", "/var/cache/repair-app")
    if os.environ.get("FIXTURE_REQUIRES_ROOT", "0") == "1" and os.geteuid() != 0:
        print("Application initialization requires root under the trusted application contract", flush=True)
        return 1
    try:
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "cache-contract.txt"), "w", encoding="utf-8") as handle:
            handle.write("kube-repair-cache-contract-v1")
        with open(os.path.join(cache, "cache-contract.txt"), encoding="utf-8") as handle:
            assert handle.read() == "kube-repair-cache-contract-v1"
    except OSError as exc:
        print(f"Cache initialization failed: {exc}", flush=True)
        return 1
    print(json.dumps({"ready": True, "cache_path": cache, "uid": os.geteuid()}), flush=True)
    CacheHandler.cache_dir = cache
    HTTPServer(("0.0.0.0", 8080), CacheHandler).serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
