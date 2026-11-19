"""Where the tests find things: this repository first on the path, and Oathline Core 0.3.x AS INSTALLED, exactly as a user's
install finds it (Claude 23:40 Fri 13 Nov 2026, the release candidate: K8). Install Core first: from PyPI once 0.3.0 is there, or,
before that, the local wheel (`pip install --no-index <path>/oathline-0.3.0-py3-none-any.whl`). No path override: a test run that
cannot import an installed Core 0.3.x stops here and says so."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# what a test's subprocess needs on PYTHONPATH: nothing when Core is installed; a run on a BASE interpreter that finds Core through
# PYTHONPATH (an unpacked wheel, never a checkout path) passes the same entries on, so every subprocess imports the same Core
CORE_PATHS: list = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]

try:
    import oathline  # noqa: E402,F401
except ImportError:                       # pragma: no cover - the message is the point
    raise SystemExit("Oathline Core 0.3.x is not installed: pip install oathline (or the local 0.3.0 wheel), then run the tests")

assert oathline.__version__.startswith("0.3."), oathline.__version__
