"""The real transport against a real socket.

Everything else in this suite injects a fake transport, which proves the SDK
builds the right request but never that :class:`chatly.UrllibTransport`
actually puts it on a wire. These tests run a loopback
:mod:`http.server` on an ephemeral port, so they need no network, no API key
and no running API — contract §9 — while still exercising real sockets, real
header casing, a real 204, a real timeout and a real connection failure.

A fake transport cannot catch a bug in the layer that talks to the operating
system, and that layer is where "works in tests, 404s in production" lives.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

import support

import chatly
from chatly import ChatlyClient
from chatly.retry import NO_RETRIES, RetryPolicy

#: Requests the server saw, for assertions after the fact.
RECORDED: List[Dict[str, Any]] = []
#: How many times ``/flaky`` has been hit, so it can fail then succeed.
FLAKY_HITS: Dict[str, int] = {"n": 0}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep the test output clean
        return

    # ---- plumbing ----------------------------------------------------

    def _record(self) -> Dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        entry = {
            "method": self.command,
            "path": urlsplit(self.path).path,
            "query": parse_qs(urlsplit(self.path).query, keep_blank_values=True),
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
        }
        RECORDED.append(entry)
        return entry

    def _send(
        self,
        status: int,
        payload: Any = None,
        *,
        headers: Optional[Dict[str, str]] = None,
        raw: Optional[bytes] = None,
    ) -> None:
        body = raw if raw is not None else (b"" if payload is None else json.dumps(payload).encode())
        self.send_response(status)
        if body:
            self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    # ---- routes ------------------------------------------------------

    def do_GET(self) -> None:
        entry = self._record()
        path, query = entry["path"], entry["query"]

        if path == "/v1/api-keys/whoami":
            self._send(
                200,
                {"workspaceId": "ws_1", "scopes": ["contacts:read"]},
                headers={"x-request-id": "req_whoami"},
            )
        elif path == "/v1/contacts":
            cursor = (query.get("cursor") or [None])[0]
            if cursor is None:
                self._send(200, {"items": [{"id": "a"}, {"id": "b"}], "nextCursor": "page2"})
            elif cursor == "page2":
                self._send(200, {"items": [{"id": "c"}], "nextCursor": None})
            else:
                self._send(400, {"error": {"code": "bad_cursor", "message": "unknown cursor"}})
        elif path == "/v1/missing":
            self._send(
                404,
                {"error": {"code": "not_found", "message": "Contact not found"}},
                headers={"x-request-id": "req_404"},
            )
        elif path == "/v1/ratelimited":
            self._send(
                429,
                {"error": {"code": "rate_limited", "message": "slow down"}},
                headers={"retry-after": "0"},
            )
        elif path == "/flaky":
            FLAKY_HITS["n"] += 1
            if FLAKY_HITS["n"] < 3:
                self._send(503, {"error": {"code": "unavailable", "message": "later"}})
            else:
                self._send(200, {"ok": True, "attempts": FLAKY_HITS["n"]})
        elif path == "/empty":
            self._send(204)
        elif path == "/notjson":
            self._send(200, raw=b"<html>a proxy answered</html>")
        elif path == "/slow":
            import time

            time.sleep(1.5)
            self._send(200, {"ok": True})
        elif path == "/v1/search":
            self._send(200, {"items": [], "nextCursor": None, "facets": {}, "tier": "postgres"})
        else:
            self._send(404, {"error": {"code": "no_route", "message": path}})

    def do_POST(self) -> None:
        entry = self._record()
        if entry["path"] == "/v1/contacts":
            self._send(201, {"id": "c_new", "echo": json.loads(entry["body"] or b"{}")})
        else:
            self._send(404, {"error": {"code": "no_route", "message": entry["path"]}})

    def do_PATCH(self) -> None:
        entry = self._record()
        self._send(200, {"patched": True, "echo": json.loads(entry["body"] or b"{}")})

    def do_PUT(self) -> None:
        entry = self._record()
        self._send(200, {"put": True, "echo": json.loads(entry["body"] or b"{}")})

    def do_DELETE(self) -> None:
        self._record()
        self._send(204)


class LoopbackTests(unittest.TestCase):
    server: ThreadingHTTPServer
    thread: threading.Thread
    base: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address[:2]
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        RECORDED.clear()
        FLAKY_HITS["n"] = 0

    def client(self, **kwargs: Any) -> ChatlyClient:
        """A client on the real transport, pointed at the loopback server."""
        kwargs.setdefault("retry", RetryPolicy(jitter=False, initial_backoff=0.0))
        return ChatlyClient("ck_loopback_key", api_url=self.base, **kwargs)

    # ---- the request actually reaches a socket -----------------------

    def test_a_real_request_carries_auth_and_the_user_agent(self) -> None:
        result = self.client().whoami()
        self.assertEqual(result, {"workspaceId": "ws_1", "scopes": ["contacts:read"]})
        headers = RECORDED[0]["headers"]
        self.assertEqual(headers["authorization"], "Bearer ck_loopback_key")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "chatly-sdk-python/0.1.0")

    def test_a_real_post_sends_a_json_body_and_an_idempotency_key(self) -> None:
        created = self.client().contacts.upsert(email="loop@example.com", name="Loop")
        self.assertEqual(created["id"], "c_new")
        self.assertEqual(created["echo"], {"email": "loop@example.com", "name": "Loop"})
        entry = RECORDED[0]
        self.assertEqual(entry["headers"]["content-type"], "application/json")
        self.assertIn("idempotency-key", entry["headers"])

    def test_auto_pagination_over_a_real_socket(self) -> None:
        ids = [c["id"] for c in self.client().contacts.iter_list()]
        self.assertEqual(ids, ["a", "b", "c"])
        self.assertEqual(len(RECORDED), 2)
        self.assertNotIn("cursor", RECORDED[0]["query"])
        self.assertEqual(RECORDED[1]["query"]["cursor"], ["page2"])

    def test_repeated_query_keys_survive_the_wire(self) -> None:
        """The thing a fake transport cannot prove: the server sees two values."""
        self.client().search.query("refund", kinds=["kb", "ticket"])
        self.assertEqual(RECORDED[0]["query"]["kinds"], ["kb", "ticket"])

    def test_a_real_404_raises_the_typed_error_with_a_request_id(self) -> None:
        with self.assertRaises(chatly.NotFoundError) as caught:
            self.client().request("GET", "/v1/missing")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(caught.exception.message, "Contact not found")
        self.assertEqual(caught.exception.request_id, "req_404")

    def test_a_real_429_is_retried_then_raises_with_retry_after(self) -> None:
        with self.assertRaises(chatly.RateLimitError) as caught:
            self.client().request("GET", "/v1/ratelimited")
        self.assertEqual(caught.exception.retry_after, 0.0)
        self.assertEqual(len(RECORDED), 3, "default policy is 3 attempts")

    def test_a_real_5xx_is_retried_and_then_succeeds(self) -> None:
        result = self.client().request("GET", "/flaky")
        self.assertEqual(result, {"ok": True, "attempts": 3})
        self.assertEqual(len(RECORDED), 3)

    def test_a_real_204_decodes_to_none(self) -> None:
        self.assertIsNone(self.client().request("GET", "/empty"))
        self.assertIsNone(self.client().request("DELETE", "/v1/anything"))

    def test_a_real_non_json_200_raises_response_decode_error(self) -> None:
        with self.assertRaises(chatly.ResponseDecodeError):
            self.client().request("GET", "/notjson")

    def test_patch_and_put_reach_the_server_as_themselves(self) -> None:
        """urllib needs an explicit ``method``; a silent fallback to GET or
        POST is a classic stdlib-HTTP bug, so assert the verb server-side."""
        client = self.client()
        client.request("PATCH", "/v1/thing", body={"a": 1})
        client.request("PUT", "/v1/thing", body={"b": 2})
        self.assertEqual([r["method"] for r in RECORDED], ["PATCH", "PUT"])
        self.assertEqual(json.loads(RECORDED[0]["body"]), {"a": 1})

    def test_an_error_response_does_not_leak_its_connection(self) -> None:
        """Regression: ``urllib.error.HTTPError`` is an open response object.

        Reading its body without closing it leaks the connection and emits a
        ``ResourceWarning`` when the collector eventually gets to it. This
        was real — found in this file's own output, not by a fake transport,
        which never constructs an ``HTTPError`` at all. A process retrying a
        failing endpoint leaked one socket per attempt.
        """
        import gc
        import warnings

        client = self.client(retry=NO_RETRIES)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(5):
                with self.assertRaises(chatly.NotFoundError):
                    client.request("GET", "/v1/missing")
            gc.collect()
        leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual([str(w.message) for w in leaks], [])

    # ---- failures that only a socket can produce ---------------------

    def test_a_real_timeout_raises_the_timeout_type(self) -> None:
        with self.assertRaises(chatly.ChatlyTimeoutError) as caught:
            self.client(timeout=0.25, retry=NO_RETRIES).request("GET", "/slow")
        self.assertIsInstance(caught.exception, chatly.TransportError)
        self.assertNotIsInstance(caught.exception, chatly.APIError)

    def test_a_refused_connection_raises_transport_error(self) -> None:
        import socket

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        client = ChatlyClient(
            "ck_loopback_key",
            api_url=f"http://127.0.0.1:{dead_port}",
            retry=NO_RETRIES,
            timeout=2.0,
        )
        with self.assertRaises(chatly.TransportError) as caught:
            client.whoami()
        self.assertNotIsInstance(caught.exception, chatly.APIError)
        self.assertIsNotNone(caught.exception.cause)

    def test_a_refused_connection_is_retried_before_it_gives_up(self) -> None:
        import socket

        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        waits: List[float] = []
        client = ChatlyClient(
            "ck_loopback_key",
            api_url=f"http://127.0.0.1:{dead_port}",
            retry=RetryPolicy(jitter=False, initial_backoff=0.0),
            timeout=2.0,
            sleep=waits.append,
        )
        with self.assertRaises(chatly.TransportError):
            client.whoami()
        self.assertEqual(len(waits), 2, "three attempts means two waits")


if __name__ == "__main__":
    unittest.main()
