"""Rate limits, security headers, snapshot signing and query isolation."""

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import rate_limit, snapshot_storage
from app.config import settings
from app.isolated_exec import run_isolated
from app.main import app
from app.safe_executor import ExecutionError, UnsafeExpressionError


def _req(ip="1.2.3.4"):
    return Request({"type": "http", "headers": [(b"x-forwarded-for", ip.encode())], "client": ("9.9.9.9", 1)})


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_chat_per_hour", 2)
    monkeypatch.setattr(settings, "rate_limit_uploads_per_hour", 1)
    monkeypatch.setattr(settings, "rate_limit_exempt", "")
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_limit_blocks_with_friendly_message(limits):
    user = {"id": "u1", "clerk_id": "user_abc", "email": ""}
    rate_limit.check("chat", _req(), user)
    rate_limit.check("chat", _req(), user)
    with pytest.raises(HTTPException) as e:
        rate_limit.check("chat", _req(), user)
    assert e.value.status_code == 429
    assert "try again in" in e.value.detail
    assert int(e.value.headers["Retry-After"]) > 0


def test_limits_are_per_user(limits):
    rate_limit.check("upload", _req(), {"id": "a"})
    rate_limit.check("upload", _req(), {"id": "b"})
    with pytest.raises(HTTPException):
        rate_limit.check("upload", _req(), {"id": "a"})


def test_anonymous_limited_by_forwarded_ip(limits):
    rate_limit.check("upload", _req("5.5.5.5"), None)
    rate_limit.check("upload", _req("6.6.6.6"), None)
    with pytest.raises(HTTPException):
        rate_limit.check("upload", _req("5.5.5.5"), None)


def test_exempt_account_never_limited(limits, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_exempt", "user_owner, someone@example.com")
    owner = {"id": "u9", "clerk_id": "user_owner", "email": ""}
    for _ in range(20):
        rate_limit.check("chat", _req(), owner)
    by_email = {"id": "u8", "clerk_id": "user_x", "email": "Someone@Example.com"}
    for _ in range(20):
        rate_limit.check("upload", _req(), by_email)


def test_upload_endpoint_returns_429(limits):
    client = TestClient(app)
    assert client.post("/sample").status_code == 200
    r = client.post("/sample")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_security_headers_present():
    r = TestClient(app).get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_snapshot_round_trip_and_tamper_refused(tmp_path):
    store = snapshot_storage.LocalSnapshots(tmp_path)
    df = pd.DataFrame({"a": [1, "4-5"], "b": [None, 2.5]})
    store.write("s", 0, df)
    pd.testing.assert_frame_equal(store.read("s", 0), df)

    path = tmp_path / "s" / "v0.pkl.gz"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(snapshot_storage.SnapshotIntegrityError):
        store.read("s", 0)


def test_unsigned_legacy_snapshot_still_reads(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    (tmp_path / "s").mkdir()
    df.to_pickle(tmp_path / "s" / "v0.pkl.gz", compression="gzip")
    pd.testing.assert_frame_equal(snapshot_storage.LocalSnapshots(tmp_path).read("s", 0), df)


def test_isolated_query_returns_result():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert run_isolated("df[df['x'] > 1]", df)['x'].tolist() == [2, 3]


def test_isolated_query_rejects_unsafe_before_spawning():
    with pytest.raises(UnsafeExpressionError):
        run_isolated("__import__('os')", pd.DataFrame())


def test_isolated_query_times_out():
    df = pd.DataFrame({"x": range(3000)})
    with pytest.raises(ExecutionError):
        run_isolated("df.merge(df, how='cross').merge(df, how='cross')", df, timeout=1)
