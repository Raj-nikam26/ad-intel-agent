"""
Test isolation.

Runs before any `app` module is imported, because settings are read once
at import time.

Unit tests must not touch the production services: they point at a
throwaway data directory and explicitly clear DATABASE_URL, NEO4J_URI and
REDIS_URL, so a developer with docker compose running gets the same
result as CI without it - and test sessions never land in the real graph.
"""

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ad-intel-tests-")
os.environ["DATABASE_URL"] = ""
os.environ["NEO4J_URI"] = ""
os.environ["REDIS_URL"] = ""
os.environ["S3_ENDPOINT_URL"] = ""
os.environ["AUTH_ENABLED"] = "false"   # auth tests switch it on explicitly
os.environ["RATE_LIMIT_ENABLED"] = "false"   # rate-limit tests switch it on
os.environ["SNAPSHOT_SIGNING_KEY"] = "test-signing-key"
