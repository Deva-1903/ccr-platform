"""Test configuration: isolate all data (DB, uploads, results) in a temp dir.

Must run before `app` is imported anywhere, hence module-level env setup.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ["CCR_DATA_DIR"] = tempfile.mkdtemp(prefix="ccr_test_")
# Tests that exercise the anonymous run limit set this themselves; everything
# else should not trip over it while running multiple jobs per test.
os.environ.setdefault("CCR_ANON_MAX_RUNS_PER_DAY", "1000")

# Make `app` importable regardless of pytest invocation directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
