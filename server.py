"""Metadata service and platform-neutral API for a trusted LAN."""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from catalog import Cache, Catalog
from sources import Source, SourceError, SOURCE_NAMES

from matching import match_score, search_catalog
from plugins.plex.provider import dispatch_plex, descriptor as plex_descriptor, parse_key

def dispatch(catalog, method, path, query, body):
    # Feature keys are relative to the registered provider URI. Keep /tv as a
    # supported entry point, including definitions already cached by PMS.
    while path.startswith("/tv/"):
        path = path[3:]
    if method == "GET" and path in ("/", "/tv"):
        return plex_descriptor()
    if method == "GET" and path == "/health":
        return {"status": "ok", "version": "0.1.0", "sources": [s.name for s in catalog.sources]}
    if method == "POST" and path == "/v1/search":
        title = body.get("title")
        year = int(body["year"]) if body.get("year") else None
        records, errors = search_catalog(catalog, title, year)
        return {"items": [{**r, "key": catalog.key(r), "match_score": match_score(title, r, year)}
                          for r in records], "source_errors": errors}
    if method == "GET" and path.startswith("/v1/metadata/"):
        key = path[len("/v1/metadata/"):]
        item, errors = catalog.resolve(key)
        return {"item": {**item, "key": key}, "source_errors": errors}
    return dispatch_plex(catalog, method, path, query, body)


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortDrama/0.1"
    catalog = None

    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        status = 200
        try:
            self.connection.settimeout(15)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 32768:
                raise ValueError("Request too large")
            if self.command == "POST" and not length:
                raise ValueError("JSON body required")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw) if length else {}
            except ValueError:
                logging.warning("invalid JSON content_type=%r length=%s", self.headers.get("Content-Type"), length)
                raise
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            u = urlsplit(self.path)
            query = {k: v[-1] for k, v in parse_qs(u.query).items()}
            for name in ("X-Plex-Container-Start", "X-Plex-Container-Size"):
                if name in self.headers:
                    query[name] = self.headers[name]
            data = dispatch(self.catalog, self.command, u.path.rstrip("/") or "/", query, body)
        except (ValueError, TypeError):
            status, data = 400, {"error": "Invalid request"}
        except LookupError:
            status, data = 404, {"error": "Metadata not available"}
        except SourceError as exc:
            status, data = 502, {"error": str(exc)}
        except Exception:
            logging.exception("Provider request failed")
            status, data = 500, {"error": "Internal error"}
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        # Request URLs can contain Plex tokens; do not log request targets.
        logging.info("request method=%s", self.command)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cache = Cache(os.environ.get("CACHE_PATH", "/data/cache.db"))
    Handler.catalog = Catalog(cache, [Source(name) for name in SOURCE_NAMES])
    server = Server(("0.0.0.0", int(os.environ.get("PORT", "3000"))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
