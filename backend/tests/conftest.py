"""Test bootstrap: allow running on Python 3.10 envs that ship project deps."""

from __future__ import annotations

import datetime as _datetime
import sys

if sys.version_info < (3, 11) and not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]
