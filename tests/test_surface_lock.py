"""Generate ``surface.lock.json`` by *executing* every method, then compare it
to the manifest.

Why this exists rather than a source scan. ``check-sdk-surface-parity.mjs``
first matched path strings in each SDK's source text, and it was fooled twice
over:

* **It could not tell documentation from code.** Three SDK authors wrote doc
  comments about two routes that turned out to be unreachable; the gate
  counted those comments as implementations and printed a full score for
  methods that raised ``NotImplementedError``.
* **It could not see a path that is built rather than written.** This SDK
  percent-encodes user-supplied segments, so
  ``Workspace.team_members`` assembles its path with
  ``encode_path('teams', team_id)`` and the string ``/v1/teams/`` appears
  nowhere in the file. A text scan reads that as "not implemented".

The lock file is produced by calling all 163 methods through the in-process
fake transport and recording the request each one actually issued. A comment
cannot emit an HTTP request, and a helper-built path shows up the same as a
literal one, so the artifact is evidence rather than inference.

Each entry also carries the top-level **shape** of the route's successful
response — ``array``, ``page``, ``object`` or ``empty`` — declared by hand in
:mod:`expected_shapes` and fed to the method it describes. Read the comment
at the top of that module before changing a value: the declaration is this
SDK's own second opinion on the API, not a copy of the manifest's, and it is
only worth something because the two were written independently.

Regenerating it is part of running the suite, deliberately — a lock that only
refreshes when someone remembers to run a script is a lock that goes stale
and then gets believed.
"""

from __future__ import annotations

import json
import pathlib
import unittest
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

import support
from expected_shapes import EXPECTED_SHAPE, SHAPE_COUNTS
from invocations import CALLS
from support import HTTPResponse, build_client, json_response
from test_surface import SPEC_PATH

from chatly import Page, ResponseDecodeError

#: Written into the package directory; a committed artifact.
LOCK_PATH = pathlib.Path(__file__).resolve().parents[1] / "surface.lock.json"

#: Minimum entries. A manifest that failed to parse must fail loudly rather
#: than shrink the audited set to zero and report success — the exact way
#: two gates in this repo have gone blind.
#:
#: 55 until 2026-10-14, when the remaining key-accessible routes got typed
#: methods — 104 of them, then three more (``webhooks.delete``, ``root.me``,
#: ``workspace.mine``) once those were added to the manifest, and then
#: ``visitors.start_conversation`` when that route opened to API keys later
#: the same day. It has only ever moved up, and it must: a drop means the
#: manifest stopped parsing, not that the API shrank.
FLOOR = 163


#: The four top-level response shapes. Every route on the surface is exactly
#: one of them; see ``$shapeMeans`` in the manifest for how each was derived
#: from a handler's ``@ZodResponse`` schema.
SHAPES = ("array", "page", "object", "empty")

# The hand-declared shape column, and its asserted distribution, live in
# `tests/expected_shapes.py` — moved there when this file hit the contract's
# 650-line ceiling (§9). Read the comment at the top of that module before
# changing a value: the whole worth of the column is that it was written
# from the handlers rather than copied from the manifest.


def response_for_shape(shape: str) -> HTTPResponse:
    """A success body of one shape, as the API would send it."""
    if shape == "empty":
        # A real 204 carries no body at all, and no content-type. A decoder
        # that insists on parsing one fails here, which is the only reason
        # this value exists separately from `object`.
        return HTTPResponse(status=204, headers={}, body=b"")
    if shape == "page":
        return json_response({"items": [{"id": "x_1"}], "nextCursor": None})
    if shape == "array":
        return json_response([{"id": "x_1"}])
    if shape == "object":
        return json_response({"id": "x_1"})
    raise AssertionError(f"unknown shape {shape!r}")


def actual_shape(value: Any) -> str:
    """The shape a decoded return value really has, in the same vocabulary.

    This is the half that catches a method which wraps or unwraps: a ``list``
    that handed back ``page.items`` from a cursored route, or one that
    reached for ``items`` on a bare-array route, disagrees here even though
    the request it issued was perfect.

    :class:`~chatly.Page` counts as ``page`` because that is this SDK's
    rendering of the envelope. ``search.query`` returns the raw envelope
    instead — the route carries ``facets`` and ``tier`` beside the cursor —
    so a dict with an ``items`` list and a cursor key counts too.
    """
    if value is None:
        return "empty"
    if isinstance(value, Page):
        return "page"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        has_cursor = "nextCursor" in value or "next_cursor" in value
        if isinstance(value.get("items"), list) and has_cursor:
            return "page"
        return "object"
    return f"scalar({type(value).__name__})"


def client_answering(shape: str) -> Tuple[Any, Any]:
    """A client whose transport answers every request with ``shape``."""
    client, transport, _ = build_client()
    transport.fallback = response_for_shape(shape)
    return client, transport


def normalise(observed: str, template: str) -> Tuple[Optional[str], Optional[str]]:
    """Fold an observed path back onto the manifest's ``{...}`` form.

    Matched **by position**: segment *i* of the observed path lines up with
    segment *i* of the manifest path. Where the manifest has a placeholder,
    the manifest's own parameter name is recorded; where it has a literal,
    the observed segment must equal it.

    That positional comparison is what gives the lock its teeth. It is not
    merely copying the manifest: a method that called the wrong path fails
    because a literal segment disagrees, and one that called a path of a
    different shape fails on the segment count. Only the *values* in
    placeholder positions are discarded, which is the one thing that should
    not be pinned.

    Returns ``(normalised_path, None)`` or ``(None, reason)``.
    """
    observed_parts = [unquote(part) for part in observed.split("/")]
    template_parts = template.split("/")

    if len(observed_parts) != len(template_parts):
        return None, (
            f"segment count {len(observed_parts)} != {len(template_parts)} "
            f"(observed {observed!r}, manifest {template!r})"
        )

    out: List[str] = []
    for index, (got, want) in enumerate(zip(observed_parts, template_parts)):
        if want.startswith("{") and want.endswith("}"):
            if got == "":
                return None, f"segment {index} is empty where {want} was expected"
            out.append(want)
        else:
            if got != want:
                return None, (
                    f"segment {index} is {got!r}, manifest says {want!r} "
                    f"(observed {observed!r})"
                )
            out.append(want)
    return "/".join(out), None


def load_manifest() -> Optional[List[Dict[str, Any]]]:
    if not SPEC_PATH.exists():
        return None
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return [
        {
            "ns": e["ns"],
            "name": e["name"],
            "http": e["http"],
            "path": e["path"],
            # `.get`, not `[...]`: a mirror can be carrying a vendored
            # manifest from before the shape pass, and `None` here produces a
            # readable diff instead of a KeyError two frames away.
            "shape": e.get("shape"),
        }
        for e in spec["entries"]
    ]


def sort_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    return (entry["ns"], entry["name"])


class SurfaceLock(unittest.TestCase):
    """Execute all 163 methods, write the lock, then assert on it.

    Generation happens in :meth:`setUpClass` rather than in a test, because
    unittest orders a class's tests alphabetically: the tests that read the
    lock ran before the one that wrote it, and the suite failed on a missing
    file. Generating once up front also means running a single test by name
    behaves the same as running the class.
    """

    manifest: Optional[List[Dict[str, Any]]]
    recorded: List[Dict[str, Any]]
    problems: List[str]
    shape_problems: List[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest()
        cls.recorded = []
        cls.problems = []
        cls.shape_problems = []
        if cls.manifest is None:
            return

        for entry in cls.manifest:
            key = (entry["ns"], entry["name"])
            dotted = f"{key[0]}.{key[1]}"
            invoke = CALLS.get(key)
            if invoke is None:
                cls.problems.append(f"{dotted}: no invocation defined in the suite")
                continue

            declared = EXPECTED_SHAPE.get(dotted)
            if declared is None:
                cls.shape_problems.append(f"{dotted}: no declared response shape")
                continue

            # One client per route, answering with the shape THIS file
            # declares — not one fake answering everything with a page
            # envelope, which is how `macros.list` passed in two other SDKs
            # and failed against the real API.
            client, transport = client_answering(declared)
            try:
                result = invoke(client)
            except Exception as exc:  # noqa: BLE001 - a failure to call IS the finding
                cls.problems.append(f"{dotted}: raised {type(exc).__name__}: {exc}")
                continue

            if transport.count != 1:
                cls.problems.append(
                    f"{dotted}: issued {transport.count} requests, expected 1"
                )
                continue

            got_shape = actual_shape(result)
            if got_shape != declared:
                cls.shape_problems.append(
                    f"{dotted}: fed a {declared} body, the method returned "
                    f"{got_shape} — it is wrapping or unwrapping the envelope"
                )

            request = transport.last
            observed_path = urlsplit(request.url).path
            folded, reason = normalise(observed_path, entry["path"])
            if reason is not None:
                cls.problems.append(f"{dotted}: {reason}")
            cls.recorded.append(
                {
                    "ns": entry["ns"],
                    "name": entry["name"],
                    "http": request.method,
                    # On a normalisation failure, record what was really
                    # issued. A lock that silently showed the manifest's path
                    # would hide the drift it exists to expose.
                    "path": folded if folded is not None else observed_path,
                    "shape": declared,
                }
            )

        cls.recorded.sort(key=sort_key)

        # Written before any assertion, so a failing run still leaves the
        # artifact that explains itself.
        LOCK_PATH.write_text(
            json.dumps(
                {
                    "sdk": "python",
                    "generatedBy": "tests/test_surface_lock.py",
                    "entries": cls.recorded,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def setUp(self) -> None:
        if self.manifest is None:
            self.skipTest(
                f"{SPEC_PATH} is absent (running outside the monorepo); the "
                "committed surface.lock.json cannot be regenerated or verified here"
            )

    # ---- the assertions ----------------------------------------------

    def test_the_manifest_meets_the_floor(self) -> None:
        """A manifest that failed to parse must fail, not shrink the audit."""
        assert self.manifest is not None
        self.assertGreaterEqual(
            len(self.manifest),
            FLOOR,
            "the manifest parsed to fewer entries than the floor — it probably "
            "did not parse, and a shrunken audit set would pass vacuously",
        )

    def test_every_method_issued_exactly_the_request_the_manifest_claims(self) -> None:
        self.assertEqual(
            self.problems, [], "methods did not issue the request the manifest claims"
        )

    def test_every_method_returned_the_shape_this_suite_declares(self) -> None:
        """Fed its declared shape, each method hands back that shape.

        Separate from the request check above because it is a different
        finding: a method can issue a flawless request and still wrap the
        body in an envelope the route does not send, or unwrap one it does.
        """
        self.assertEqual(
            self.shape_problems,
            [],
            "methods did not return the response shape this suite declares",
        )

    def test_the_executed_surface_equals_the_manifest(self) -> None:
        assert self.manifest is not None
        self.assertEqual(
            self.recorded,
            sorted(self.manifest, key=sort_key),
            "the executed surface and the manifest disagree",
        )

    def test_the_written_lock_is_well_formed(self) -> None:
        """Read the artifact back off disk, as the gate will."""
        self.assertTrue(LOCK_PATH.exists(), "surface.lock.json was not written")
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

        self.assertEqual(lock["sdk"], "python")
        self.assertEqual(lock["generatedBy"], "tests/test_surface_lock.py")
        self.assertGreaterEqual(len(lock["entries"]), FLOOR)

        keys = [(e["ns"], e["name"]) for e in lock["entries"]]
        self.assertEqual(keys, sorted(keys), "entries are not sorted by ns then name")
        self.assertEqual(len(keys), len(set(keys)), "duplicate entries in the lock")

        for entry in lock["entries"]:
            self.assertEqual(
                list(entry.keys()),
                ["ns", "name", "http", "path", "shape"],
                "key order is part of the artifact: the gate diffs these files "
                "and a reordered key is noise in every review",
            )
            self.assertTrue(entry["path"].startswith("/v1/"), entry)
            self.assertIn(entry["http"], ("GET", "POST", "PUT", "PATCH", "DELETE"), entry)
            self.assertIn(entry["shape"], SHAPES, entry)
            self.assertEqual(
                entry["shape"],
                EXPECTED_SHAPE[f"{entry['ns']}.{entry['name']}"],
                "the written lock disagrees with this suite's own declaration",
            )

    def test_the_lock_carries_every_shape(self) -> None:
        """The gate fails a lock whose rows all share one shape. So does this.

        A generator that dropped the field, or a sweep that flattened it to
        `object`, leaves every other assertion here satisfied.
        """
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        counts = {shape: 0 for shape in SHAPES}
        for entry in lock["entries"]:
            counts[entry["shape"]] += 1
        self.assertEqual(counts, SHAPE_COUNTS)

    def test_the_lock_covers_every_method_the_suite_calls(self) -> None:
        """Nothing in the manifest is left uncalled, and nothing is invented."""
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        locked = {(e["ns"], e["name"]) for e in lock["entries"]}
        self.assertEqual(
            locked, set(CALLS.keys()), "the lock and the suite's invocations disagree"
        )

    def test_a_helper_built_path_is_captured(self) -> None:
        """The case a text scan cannot see, pinned explicitly.

        ``team_members`` assembles its path through ``encode_path``, so the
        literal ``/v1/teams/`` appears nowhere in the source. It must still
        land in the lock.
        """
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        entry = next(
            e
            for e in lock["entries"]
            if (e["ns"], e["name"]) == ("workspace", "team_members")
        )
        self.assertEqual(entry["path"], "/v1/teams/{id}/members")
        self.assertEqual(entry["http"], "GET")

        source = (
            pathlib.Path(support.__file__).resolve().parents[1]
            / "src"
            / "chatly"
            / "resources"
            / "workspace.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "/v1/teams/",
            source,
            "this assertion documents why the lock exists; if the path has "
            "become a literal, the point still holds for the other built paths",
        )


class DeclaredShapes(unittest.TestCase):
    """The shape column itself, before any of it is believed.

    Needs no manifest, so it runs in a mirror and in an extracted sdist too
    — the declaration is this package's own statement about the API and does
    not depend on the spec file being next door.
    """

    def test_every_invocation_has_a_declared_shape_and_nothing_is_orphaned(self) -> None:
        dotted = {f"{ns}.{name}" for ns, name in CALLS}
        self.assertEqual(
            set(EXPECTED_SHAPE),
            dotted,
            "the declared shapes and the suite's invocations disagree",
        )

    def test_every_declared_value_is_one_of_the_four(self) -> None:
        bad = {k: v for k, v in EXPECTED_SHAPE.items() if v not in SHAPES}
        self.assertEqual(bad, {})

    def test_the_column_is_not_vacuous(self) -> None:
        """A column of 163 ``object`` rows is unanimity about nothing.

        Every other assertion in this file would pass it: the fixture would
        be an object, each method would be handed an object, and the lock
        would agree with itself. The distribution is the only thing that
        notices, so it is pinned — 33 arrays, 13 pages, 116 objects and the
        single real 204.
        """
        counts = {shape: 0 for shape in SHAPES}
        for shape in EXPECTED_SHAPE.values():
            counts[shape] += 1
        self.assertEqual(counts, SHAPE_COUNTS)
        for shape in SHAPES:
            self.assertGreater(counts[shape], 0, f"no route declares {shape}")


#: Every auto-paginating method, keyed by the route it walks.
#:
#: Written out rather than reflected over ``dir()``: the assertion below is
#: that this hand-written set equals the routes declared ``page``, which is
#: only worth something if the two sides were produced independently.
WALKERS = {
    "bots.list": lambda c: c.bots.iter_list(),
    "bots.deliveries": lambda c: c.bots.iter_deliveries("ID1"),
    "contacts.list": lambda c: c.contacts.iter_list(),
    "contacts.journey": lambda c: c.contacts.iter_journey("ID1"),
    "conversations.list": lambda c: c.conversations.iter_list(),
    "conversations.messages": lambda c: c.conversations.iter_messages("ID1"),
    "conversations.unattended": lambda c: c.conversations.iter_unattended(),
    "tickets.list": lambda c: c.tickets.iter_list(),
    "triggers.list": lambda c: c.triggers.iter_list(),
    "kb.articles": lambda c: c.kb.iter_articles(),
    "search.query": lambda c: c.search.iter_query("refund"),
    "events.list": lambda c: c.events.iter_list(),
    "webhooks.deliveries": lambda c: c.webhooks.iter_deliveries(),
}


class PaginatorsRefuseTheWrongShape(unittest.TestCase):
    """The negative direction, which is the half that proves the rest.

    :class:`SurfaceLock` feeds every method the shape this suite says its
    route sends, and asserts on what comes back. That cannot prove the
    declaration *matters*: a decoder which ignored the body entirely would
    pass it, and so would one that quietly returned an empty page for
    anything it did not recognise.

    So here each walker is fed a bare JSON array where it expects
    ``{"items": ..., "nextCursor": ...}`` and is required to fail loudly.
    That is exactly what the real API handed the .NET and Rust clients on
    ``GET /v1/macros`` while their suites were green — and Rust's decoder
    did not even raise: it read the array as an empty page and returned it
    with a 200, so the caller was told the list was empty.

    This SDK had the same defect. ``page_from_payload`` folded a bare array
    into one cursor-less page and turned any other unrecognised body into an
    empty page with the payload in ``Page.raw``. It is strict now, and the
    tolerance survives only on ``ChatlyClient.paginate``, the untyped escape
    hatch, where there is no manifest entry to consult.
    """

    def test_the_walkers_are_exactly_the_routes_declared_page(self) -> None:
        """Neither side of this test may shrink quietly.

        A walker list that drifted down to one entry would still pass every
        assertion below.
        """
        page_routes = {k for k, v in EXPECTED_SHAPE.items() if v == "page"}
        self.assertEqual(
            set(WALKERS),
            page_routes,
            "every `page` route needs a walker here, and nothing else belongs",
        )
        self.assertEqual(len(page_routes), SHAPE_COUNTS["page"])

    def test_a_bare_array_where_a_page_belongs_is_an_error(self) -> None:
        for key, walk in sorted(WALKERS.items()):
            with self.subTest(route=key):
                client, transport = client_answering("array")
                with self.assertRaises(
                    ResponseDecodeError,
                    msg=f"{key}'s paginator accepted a bare array as a page",
                ):
                    for _ in walk(client):
                        break
                # The request must actually have been made. Without this, a
                # walker that raised on argument validation before touching
                # the transport would pass for the wrong reason.
                self.assertEqual(transport.count, 1, f"{key} issued no request")

    def test_the_same_walkers_do_yield_on_a_real_page(self) -> None:
        """The control. A paginator that raised on everything is not strict."""
        for key, walk in sorted(WALKERS.items()):
            with self.subTest(route=key):
                client, transport = client_answering("page")
                rows = list(walk(client))
                self.assertEqual([row["id"] for row in rows], ["x_1"])
                self.assertEqual(transport.count, 1)


class NormalisationItself(unittest.TestCase):
    """The folding function is load-bearing, so test it directly."""

    def test_placeholders_are_taken_from_the_manifest(self) -> None:
        self.assertEqual(
            normalise("/v1/contacts/c_1/tags/vip", "/v1/contacts/{id}/tags/{tag}"),
            ("/v1/contacts/{id}/tags/{tag}", None),
        )

    def test_a_literal_mismatch_is_a_failure_not_a_fold(self) -> None:
        folded, reason = normalise("/v1/contacts/c_1/labels/vip", "/v1/contacts/{id}/tags/{tag}")
        self.assertIsNone(folded)
        self.assertIn("'labels'", str(reason))

    def test_a_different_shape_is_a_failure(self) -> None:
        folded, reason = normalise("/v1/contacts/c_1", "/v1/contacts/{id}/tags/{tag}")
        self.assertIsNone(folded)
        self.assertIn("segment count", str(reason))

    def test_a_static_path_folds_to_itself(self) -> None:
        self.assertEqual(normalise("/v1/tickets/queues", "/v1/tickets/queues"), ("/v1/tickets/queues", None))

    def test_a_static_segment_is_not_mistaken_for_a_value(self) -> None:
        """``/v1/conversations/unattended`` must not fold against ``/{id}``."""
        folded, reason = normalise(
            "/v1/conversations/unattended", "/v1/conversations/{id}"
        )
        self.assertEqual(folded, "/v1/conversations/{id}")
        self.assertIsNone(reason)
        # ...which is why the manifest entry, not a guess, picks the template:
        # the two routes are distinct entries and each is folded against its own.
        self.assertEqual(
            normalise("/v1/conversations/unattended", "/v1/conversations/unattended"),
            ("/v1/conversations/unattended", None),
        )

    def test_percent_encoded_values_are_decoded_before_comparison(self) -> None:
        self.assertEqual(
            normalise(
                "/v1/contacts/c_1/tags/needs%2Freview", "/v1/contacts/{id}/tags/{tag}"
            ),
            ("/v1/contacts/{id}/tags/{tag}", None),
        )

    def test_an_empty_placeholder_segment_is_refused(self) -> None:
        folded, reason = normalise("/v1/contacts//tags/vip", "/v1/contacts/{id}/tags/{tag}")
        self.assertIsNone(folded)
        self.assertIn("empty", str(reason))


if __name__ == "__main__":
    unittest.main()
