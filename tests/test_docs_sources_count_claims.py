"""What this SDK's prose says about the docs-source article counts.

WHY A TEST ABOUT DOCUMENTATION. ``update`` used to answer
``{"articleCount": 0, "staleCount": 0}`` whatever the source held, and three
places here said so: this package's README, :meth:`DocsSources.list`'s
docstring and :meth:`DocsSources.update`'s. The API stopped doing it on
2026-10-16 (``apps/api/src/modules/docs-sources/docs-sources.service.ts`` now
reads the counts in the same transaction as the write; the behaviour is
pinned by ``docs-sources-update-counts.spec.ts``), and the only trace left of
the old behaviour was this client telling people to ignore a real number and
re-read it from ``list``.

Nothing in a thin HTTP client can detect that drift by exercising code — the
SDK forwards whatever the server sends. A claim about the server's behaviour
is testable here only as a claim, so it is pinned as one: in both directions,
so that deleting the sentence does not count as fixing it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "src" / "chatly" / "resources" / "docs_sources.py",
)

#: "update … zeros" with no sentence boundary between the two. `[^.]` is what
#: keeps this from matching across the fixed text, where the zero case belongs
#: to `create` and sits in its own sentence.
STALE_CLAIM = re.compile(
    r"update[^.]{0,120}?(zeros|always\s+0|placeholders)", re.IGNORECASE | re.DOTALL
)

#: The claim that replaced it. `create` DOES answer 0, correctly, and a reader
#: who is told nothing about that will read the 0 as data.
CREATE_CLAIM = re.compile(
    r"create[^.]{0,160}?(answers 0|no articles)", re.IGNORECASE | re.DOTALL
)


class DocsSourceCountClaims(unittest.TestCase):
    def test_nothing_still_says_update_answers_zero_counts(self) -> None:
        for path in DOCUMENTS:
            text = path.read_text(encoding="utf-8")
            found = [m.group(0) for m in STALE_CLAIM.finditer(text)]
            self.assertEqual(
                found,
                [],
                f"{path.name} still tells callers `update` reports zero counts. "
                "It reports the real ones since 2026-10-16 — see "
                "apps/api/src/modules/docs-sources/docs-sources.service.ts.",
            )

    def test_the_zero_case_is_still_attributed_to_create(self) -> None:
        for path in DOCUMENTS:
            text = path.read_text(encoding="utf-8")
            self.assertRegex(
                text,
                CREATE_CLAIM,
                f"{path.name} no longer says which route answers 0. `create` does, "
                "and a reader who is not told that reads it as a real count.",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
