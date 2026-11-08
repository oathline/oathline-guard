"""Where the tests find Oathline Core: the pinned 0.2.0 at core-0.2.0 894a7e2 (Claude 14:12 Sun 8 Nov 2026), a `git archive` of
that commit at C:/dev/oathline-core-894a7e2, or OATHLINE_CORE_PATH. The package itself imports `oathline` like any installed
dependency; only the tests put the pinned copy first on the path."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.environ.get("OATHLINE_CORE_PATH") or os.path.join(os.path.dirname(ROOT), "oathline-core-894a7e2")
for p in (CORE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
