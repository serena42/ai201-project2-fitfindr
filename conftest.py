"""
conftest.py — its presence at the project root puts this directory on sys.path
so tests under tests/ can `from tools import ...` and `from utils...`.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(__file__)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
