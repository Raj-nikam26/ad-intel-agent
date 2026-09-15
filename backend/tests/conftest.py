"""
Points the session store at a throwaway directory for the whole test run.

This has to happen before any `app` module is imported, because settings
are read once at import time. Without it the suite would write test
sessions into backend/data/ alongside real ones.
"""

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ad-intel-tests-")
