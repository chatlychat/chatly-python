"""Generate ``surface.lock.json`` by *executing* every method, then compare it
to the manifest.

Why this exists rather than a source scan. ``check-sdk-surface-parity.mjs``
first matched path strings in each SDK's source text, and it was fooled twice
over:

* **It could not tell documentation from code.** Three SDK authors wrote doc
  comments about two routes that turned out to be unreachable; the gate
  counted those comments as implementations and printed ``55/55`` for methods
  that raised ``NotImplementedError``.
* **It could not see a path that is built rather than written.** This SDK
  percent-encodes user-supplied segments, so
  ``Workspace.team_members`` assembles its path with
  ``encode_path('teams', team_id)`` and the string ``/v1/teams/`` appears
  nowhere in the file. A text scan reads that as "not implemented".

The lock file is produced by calling all 55 methods through the in-process
fake transport and recording the request each one actually issued. A comment
cannot emit an HTTP request, and a helper-built path shows up the same as a
literal one, so the artifact is evidence rather than inference.

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
from support import build_client
from test_surface import CALLS, SPEC_PATH

#: Written into the package directory; a committed artifact.
LOCK_PATH = pathlib.Path(__file__).resolve().parents[1] / "surface.lock.json"

#: Minimum entries. A manifest that failed to parse must fail loudly rather
#: than shrink the audited set to zero and report success — the exact way
#: two gates in this repo have gone blind.
FLOOR = 55


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
        {"ns": e["ns"], "name": e["name"], "http": e["http"], "path": e["path"]}
        for e in spec["entries"]
    ]


def sort_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    return (entry["ns"], entry["name"])


class SurfaceLock(unittest.TestCase):
    """Execute all 55 methods, write the lock, then assert on it.

    Generation happens in :meth:`setUpClass` rather than in a test, because
    unittest orders a class's tests alphabetically: the tests that read the
    lock ran before the one that wrote it, and the suite failed on a missing
    file. Generating once up front also means running a single test by name
    behaves the same as running the class.
    """

    manifest: Optional[List[Dict[str, Any]]]
    recorded: List[Dict[str, Any]]
    problems: List[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest()
        cls.recorded = []
        cls.problems = []
        if cls.manifest is None:
            return

        for entry in cls.manifest:
            key = (entry["ns"], entry["name"])
            invoke = CALLS.get(key)
            if invoke is None:
                cls.problems.append(f"{key[0]}.{key[1]}: no invocation defined in the suite")
                continue

            client, transport, _ = build_client()
            try:
                invoke(client)
            except Exception as exc:  # noqa: BLE001 - a failure to call IS the finding
                cls.problems.append(
                    f"{key[0]}.{key[1]}: raised {type(exc).__name__}: {exc}"
                )
                continue

            if transport.count != 1:
                cls.problems.append(
                    f"{key[0]}.{key[1]}: issued {transport.count} requests, expected 1"
                )
                continue

            request = transport.last
            observed_path = urlsplit(request.url).path
            folded, reason = normalise(observed_path, entry["path"])
            if reason is not None:
                cls.problems.append(f"{key[0]}.{key[1]}: {reason}")
            cls.recorded.append(
                {
                    "ns": entry["ns"],
                    "name": entry["name"],
                    "http": request.method,
                    # On a normalisation failure, record what was really
                    # issued. A lock that silently showed the manifest's path
                    # would hide the drift it exists to expose.
                    "path": folded if folded is not None else observed_path,
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
            self.assertEqual(sorted(entry.keys()), ["http", "name", "ns", "path"], entry)
            self.assertTrue(entry["path"].startswith("/v1/"), entry)
            self.assertIn(entry["http"], ("GET", "POST", "PUT", "PATCH", "DELETE"), entry)

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
