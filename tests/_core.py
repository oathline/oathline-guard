"""Where the tests find things: this repository first on the path, and Oathline Core as an installed dependency (`pip install
"oathline>=0.2.0,<0.3"`, from PyPI), exactly as a user's install finds it (Claude 09:40 Mon 9 Nov 2026: no path override for the
release build)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
