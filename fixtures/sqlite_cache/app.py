"""SQLite-backed cache fixture; independent probes are owned by the harness."""

import hashlib
import json
import os
import signal
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class CacheHandler(BaseHTTPRequestHandler):
    database_path = ""

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
        value = values[0]
        try:
            with closing(sqlite3.connect(self.database_path, timeout=1)) as database, database:
                row = database.execute("SELECT result FROM results WHERE input = ?", (value,)).fetchone()
                cached = row is not None
                if cached:
                    result = row[0]
                    database.execute("UPDATE results SET hits = hits + 1 WHERE input = ?", (value,))
                else:
                    result = hashlib.sha256(value.encode()).hexdigest()
                    database.execute("INSERT INTO results(input, result, hits) VALUES (?, ?, 0)", (value, result))
        except sqlite3.Error as exc:
            return self._respond(500, {"error": str(exc)})
        self._respond(200, {"result": result, "cached": cached})


def initialize_database(cache):
    """Create a real SQLite database, with all writes below the permitted path."""
    os.makedirs(cache, exist_ok=True)
    database_path = os.path.join(cache, "cache.sqlite3")
    with closing(sqlite3.connect(database_path, timeout=1)) as database, database:
        database.execute("PRAGMA journal_mode = DELETE")
        database.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        database.execute("CREATE TABLE IF NOT EXISTS results(input TEXT PRIMARY KEY, result TEXT NOT NULL, hits INTEGER NOT NULL)")
        database.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('contract', 'kube-repair-sqlite-contract-v1')")
    return database_path


def main():
    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    cache = os.environ.get("CACHE_DIR", "/var/lib/repair-sqlite")
    if os.environ.get("FIXTURE_REQUIRES_ROOT", "0") == "1" and os.geteuid() != 0:
        print("Application initialization requires root under the trusted application contract", flush=True)
        return 1
    try:
        CacheHandler.database_path = initialize_database(cache)
    except (OSError, sqlite3.Error) as exc:
        print(f"SQLite cache initialization failed: {exc}", flush=True)
        return 1
    print(json.dumps({"ready": True, "cache_path": cache, "uid": os.geteuid()}), flush=True)
    HTTPServer(("0.0.0.0", 8080), CacheHandler).serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
