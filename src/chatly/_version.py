"""Single source of the package version.

Lives in its own module so `_transport.py` can build the `User-Agent` header
without importing the package barrel (which imports `_transport`).
"""

from __future__ import annotations

__version__ = "0.1.0"

#: The exact ``User-Agent`` every request carries. Contract §2.
USER_AGENT = f"chatly-sdk-python/{__version__}"
