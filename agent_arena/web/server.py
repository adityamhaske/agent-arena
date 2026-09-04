"""A local web server for the arena, built on nothing but the standard library.

`pip install agent-arena` must not start pulling in a web framework, so this is
`http.server` plus a routing table. It is a single-user tool bound to localhost
by default and has no authentication — see :func:`serve` for what that means and
how the few guards here (host allow-list, no CORS, no directory traversal) keep
an accidental exposure from becoming a remote shell.
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from ..core.errors import ArenaError
from ..service.errors import ConflictError, NotFoundError
from .api import ApiError, ArenaAPI
from .language import plain_error

STATIC_DIR = Path(__file__).parent / "static"

#: Refuse a request body big enough to be an attack rather than a test suite.
MAX_BODY_BYTES = 8 * 1024 * 1024


class Route:
    __slots__ = ("method", "pattern", "handler")

    def __init__(self, method: str, pattern: str, handler: Callable[..., Any]) -> None:
        self.method = method
        self.pattern = re.compile(f"^{pattern}$")
        self.handler = handler


def build_routes(api: ArenaAPI) -> list[Route]:
    """Map URLs to :class:`ArenaAPI` methods. The whole HTTP surface, in one place."""
    name = r"(?P<name>[a-z0-9][a-z0-9_-]{0,63})"
    return [
        Route("GET", r"/api/catalog", lambda **_: api.catalog()),
        Route(
            "GET",
            r"/api/projects",
            lambda query, **_: {
                "projects": api.list_projects(include_archived=_truthy(query.get("all")))
            },
        ),
        Route("POST", r"/api/projects", lambda body, **_: api.create_project(body)),
        Route("GET", rf"/api/projects/{name}", lambda name, **_: api.describe_project(name)),
        Route("PUT", rf"/api/projects/{name}", lambda name, body, **_: api.update_project(name, body)),
        Route("PUT", rf"/api/projects/{name}/tests", lambda name, body, **_: api.save_tests(name, body)),
        Route("POST", rf"/api/projects/{name}/run", lambda name, body, **_: api.start_run(name, body)),
        Route("GET", rf"/api/projects/{name}/history", lambda name, **_: api.history(name)),
        Route(
            "GET",
            rf"/api/projects/{name}/result",
            lambda name, query, **_: api.stored_run(name, query.get("run_id")),
        ),
        Route(
            "POST",
            rf"/api/projects/{name}/whatif",
            lambda name, body, **_: api.rescore(name, body.get("run_id"), body),
        ),
        Route("GET", r"/api/jobs/(?P<job_id>[a-f0-9]{1,32})", lambda job_id, **_: api.job_status(job_id)),
        Route(
            "POST",
            r"/api/jobs/(?P<job_id>[a-f0-9]{1,32})/cancel",
            lambda job_id, **_: api.cancel_run(job_id),
        ),

        # Lifecycle. Until these existed the product had no way to remove
        # anything: a project created by a typo was permanent and the database
        # grew forever.
        Route("DELETE", rf"/api/projects/{name}", lambda name, query, **_: api.delete_project(name, query)),
        Route("POST", rf"/api/projects/{name}/duplicate", lambda name, body, **_: api.duplicate_project(name, body)),
        Route("POST", rf"/api/projects/{name}/archive", lambda name, body, **_: api.archive_project(name, body)),
        Route("GET", rf"/api/projects/{name}/runs", lambda name, query, **_: api.list_runs(name, query)),
        Route(
            "DELETE",
            rf"/api/projects/{name}/runs/(?P<run_id>[A-Za-z0-9_.-]{{1,80}})",
            lambda name, run_id, query, **_: api.delete_run(name, run_id, query),
        ),
        Route(
            "POST",
            rf"/api/projects/{name}/runs/(?P<run_id>[A-Za-z0-9_.-]{{1,80}})/label",
            lambda name, run_id, body, **_: api.label_run(name, run_id, body),
        ),
        Route("POST", rf"/api/projects/{name}/vacuum", lambda name, query, **_: api.vacuum(name, query)),
        Route("GET", rf"/api/projects/{name}/export", lambda name, query, **_: api.export_run(name, query)),
        Route("GET", r"/api/providers", lambda **_: api.list_providers()),
        Route("POST", r"/api/providers", lambda body, **_: api.save_provider(body)),
        Route(
            "DELETE",
            r"/api/providers/(?P<provider_id>[A-Za-z0-9_.-]{1,64})",
            lambda provider_id, query, **_: api.delete_provider(provider_id, query),
        ),
        Route(
            "POST",
            r"/api/providers/(?P<provider_id>[A-Za-z0-9_.-]{1,64})/test",
            lambda provider_id, **_: api.test_provider(provider_id),
        ),
        Route(
            "POST",
            r"/api/providers/(?P<provider_id>[A-Za-z0-9_.-]{1,64})/discover",
            lambda provider_id, **_: api.discover_provider_models(provider_id),
        ),
        Route("GET", r"/api/local", lambda **_: api.local_runtime()),
        Route("POST", r"/api/local/start", lambda **_: api.start_local_runtime()),
        Route("GET", r"/api/settings", lambda **_: api.settings()),
        Route("PUT", r"/api/settings", lambda body, **_: api.update_settings(body)),
    ]


class ArenaHandler(BaseHTTPRequestHandler):
    """One request. Static files from ``static/``, everything else from the API."""

    server_version = "AgentArenaUI"
    protocol_version = "HTTP/1.1"

    # Replaced on the subclass build_app returns.
    routes: list[Route] = []
    allowed_hosts: set[str] = set()

    # ---- plumbing ------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Quiet by default: a request log for every poll would bury real output."""
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _origin_allowed(self) -> bool:
        """Reject a state-changing request that another site initiated.

        The Host allow-list stops DNS rebinding, but it does not stop a plain
        cross-site form POST: that carries a legitimate Host header. Absence of
        CORS keeps an attacker from *reading* the reply, and this keeps them
        from causing the write in the first place.

        Same-origin requests either omit Origin (most browsers, on same-origin
        navigations) or send one matching the host we are served under, so an
        absent Origin is allowed and a foreign one is not.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
            return fetch_site in ("", "same-origin", "same-site", "none")
        try:
            hostname = urlsplit(origin).hostname or ""
        except ValueError:
            return False
        return hostname.lower() in self.allowed_hosts

    def _host_allowed(self) -> bool:
        """Block DNS-rebinding: only the names we are actually served under.

        Without this, a page on the open internet could point a hostname at
        127.0.0.1 and drive this API from the user's browser.
        """
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        # A request with no Host header used to pass. HTTP/1.1 requires one, so
        # its absence is a malformed request rather than a same-origin call.
        return bool(host) and host in self.allowed_hosts

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # Scripts stay locked to same-origin — that is the directive that
        # matters against injected markup. Inline `style=` is allowed because
        # the bars and progress meters set their width from data, and data:
        # images for the favicon.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _read_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError("Malformed Content-Length.") from None
        if length > MAX_BODY_BYTES:
            raise ApiError("That request is too large.", status=413)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("The request body was not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ApiError("The request body must be a JSON object.")
        return parsed

    # ---- dispatch ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        if not self._host_allowed():
            self._json(403, {"error": "This server only answers requests from localhost."})
            return
        if method != "GET" and not self._origin_allowed():
            self._json(
                403,
                {"error": "This request came from another site, so it was refused."},
            )
            return

        path, _, query_string = self.path.partition("?")
        query = _parse_query(query_string)

        if not path.startswith("/api/"):
            self._serve_static(path)
            return

        try:
            body = self._read_body() if method in ("POST", "PUT") else {}
            # DELETE takes its options from the query string; a body on a
            # DELETE is not universally supported by clients or proxies.
            for route in self.routes:
                if route.method != method:
                    continue
                match = route.pattern.match(path)
                if match:
                    payload = route.handler(body=body, query=query, **match.groupdict())
                    self._json(200, payload)
                    return
            self._json(404, {"error": f"No such endpoint: {path}"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc)})
        except NotFoundError as exc:
            # The service layer raises this for a name that does not exist.
            # Without this branch it fell through to the generic 400 below, so
            # "no such provider" and "malformed provider" looked identical to a
            # caller, while the project and run routes already answered 404.
            self._json(404, {"error": plain_error(str(exc)), "detail": str(exc)})
        except ConflictError as exc:
            self._json(409, {"error": plain_error(str(exc)), "detail": str(exc)})
        except ArenaError as exc:
            self._json(400, {"error": plain_error(str(exc)), "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 — a UI bug must not kill the server
            self._json(
                500,
                {
                    "error": "Something went wrong on the server.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            )

    # ---- static --------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            # Any unknown path falls back to the app shell, so client-side
            # routing works on a refresh.
            target = STATIC_DIR / "index.html"
            if not target.is_file():
                self._json(500, {"error": "The UI files are missing from this install."})
                return
        body = target.read_bytes()
        if target.name == "index.html":
            # Stamp the asset links with the running version. Without this an
            # upgrade can pair a fresh app.js with a cached app.css, which
            # renders a subtly broken page rather than an obviously broken one.
            from .. import __version__  # noqa: PLC0415

            body = body.replace(b"__ARENA_VERSION__", __version__.encode())

        content_type, _ = mimetypes.guess_type(target.name)
        # Everything is served no-store. These are three small files off a
        # loopback socket, so caching buys nothing measurable — and a cached
        # app.css paired with a freshly upgraded app.js renders a subtly
        # broken page for a minute after every `pip install --upgrade`, which
        # is a bad trade for bytes nobody was waiting on.
        cache = "no-store"
        self._send(
            200,
            body,
            content_type or "application/octet-stream",
            {"Cache-Control": cache},
        )


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_query(query_string: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(query_string).items() if values}


def build_app(projects_dir: str | Path, host: str = "127.0.0.1") -> type[ArenaHandler]:
    """A handler class bound to one projects directory. Used directly by tests."""
    api = ArenaAPI(projects_dir)
    allowed = {"localhost", "127.0.0.1", "::1", "0.0.0.0", host.lower()}

    class BoundHandler(ArenaHandler):
        routes = build_routes(api)
        allowed_hosts = allowed

    BoundHandler.api = api  # type: ignore[attr-defined]  — for tests
    return BoundHandler


def serve(
    projects_dir: str | Path = "projects",
    host: str = "127.0.0.1",
    port: int = 8420,
    open_browser: bool = True,
    verbose: bool = False,
) -> None:
    """Run the UI until interrupted.

    Binds to loopback by default and has no login, because it drives the local
    filesystem and can spend money against your API keys. Passing a non-loopback
    ``host`` puts that on your network with no authentication in front of it;
    the caller is told so plainly rather than being quietly protected.
    """
    handler = build_app(projects_dir, host=host)
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise ArenaError(
            f"Could not start the UI on {host}:{port} — {exc}.\n"
            "Another program is probably using that port. Try `arena ui --port 8421`."
        ) from exc

    httpd.verbose = verbose  # type: ignore[attr-defined]
    httpd.daemon_threads = True
    shown = "localhost" if host in ("127.0.0.1", "::1") else host
    url = f"http://{shown}:{httpd.server_address[1]}"

    print(f"\n  Agent Arena is running at {url}")
    print(f"  Projects folder: {Path(projects_dir).resolve()}")
    if not _is_loopback(host):
        print(
            "\n  WARNING: this is bound to a non-loopback address and has no "
            "login.\n  Anyone who can reach it can edit your projects and spend "
            "your API credit."
        )
    print("\n  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Timer(0.4, lambda: _open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.server_close()


def _is_loopback(host: str) -> bool:
    import ipaddress  # noqa: PLC0415

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")


def _open(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 — a headless box is not an error
        pass


__all__ = ["build_app", "serve", "ArenaHandler", "build_routes"]
