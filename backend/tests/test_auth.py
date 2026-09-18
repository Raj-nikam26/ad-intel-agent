"""
Sign-in (Clerk) and ownership.

With AUTH_ENABLED on, one user's session is invisible to another, and
the audit log records who made each change. The signed-in user is
injected by overriding the dependency; token checks are tested below with
real RS256 signatures from a throwaway key.
"""

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.auth import current_user
from app.config import settings
from app.main import app


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    yield
    app.dependency_overrides.pop(current_user, None)


def as_user(user_id):
    app.dependency_overrides[current_user] = lambda: {
        "id": user_id, "email": f"{user_id}@example.com", "name": user_id, "picture": "",
    }
    return TestClient(app)


def upload(client):
    df = pd.DataFrame({"Category": ["A", None], "Publication": ["X", "Y"],
                       "Advertiser Name by AI": ["Acme", "Beta"]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return client.post("/upload", files={"file": ("t.xlsx", buf.read(), "application/vnd.ms-excel")})


def test_auth_disabled_by_default_so_the_demo_needs_no_account():
    client = TestClient(app)
    assert upload(client).status_code == 200
    body = client.get("/health").json()
    assert body["auth_enabled"] is False and body["user"] is None


def test_signed_out_requests_are_rejected_when_auth_is_on(auth_on):
    client = TestClient(app)
    assert upload(client).status_code == 401
    assert client.get("/data/anything").status_code == 401


def test_a_session_is_invisible_to_another_user(auth_on):
    owner = as_user("user-1")
    res = upload(owner)
    assert res.status_code == 200, res.text
    session_id = res.json()["session_id"]
    assert owner.get(f"/data/{session_id}").status_code == 200

    other = as_user("user-2")
    # 404, not 403: guessing ids reveals nothing about which ones exist
    for path in (f"/data/{session_id}", f"/history/{session_id}",
                 f"/export/{session_id}", f"/mapping/{session_id}", f"/issues/{session_id}"):
        assert other.get(path).status_code == 404, path


def test_edits_record_who_made_them(auth_on):
    client = as_user("user-1")
    session_id = upload(client).json()["session_id"]

    from app.agent import execute_tool_call
    from app.data_store import session_store
    execute_tool_call("apply_edit", {
        "operation": "fill_missing_value_bulk", "column": "Category",
        "value": "Filled", "reason": "test",
    }, session_store.get(session_id), user_id="user-1")

    entry = client.get(f"/history/{session_id}").json()["audit_log"][0]
    assert entry["user_id"] == "user-1"


# ------------------------------------------------ Clerk token verification

def _signed_token(claims):
    """A token signed with a throwaway RSA key, plus that key's public half."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return jwt.encode(claims, key, algorithm="RS256"), key.public_key()


class _FakeJwks:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": self.public_key})()


def _use_key(monkeypatch, public_key):
    from app import auth
    monkeypatch.setattr(auth, "_jwks_client", _FakeJwks(public_key))
    monkeypatch.setattr(settings, "clerk_issuer", "https://example.clerk.accounts.dev")
    monkeypatch.setattr(settings, "clerk_authorized_parties", ["http://localhost:5173"])


def _claims(**over):
    import time
    now = int(time.time())
    base = {"sub": "user_abc", "iat": now, "exp": now + 60,
            "iss": "https://example.clerk.accounts.dev", "azp": "http://localhost:5173"}
    base.update(over)
    return base


def test_valid_clerk_token_is_accepted_and_owns_its_uploads(auth_on, monkeypatch):
    token, pub = _signed_token(_claims())
    _use_key(monkeypatch, pub)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    res = upload(client)
    assert res.status_code == 200, res.text
    assert client.get(f"/data/{res.json()['session_id']}").status_code == 200


@pytest.mark.parametrize("bad", [
    {"exp": 1},                                      # expired
    {"iss": "https://evil.example"},                 # wrong issuer
    {"azp": "https://evil.example"},                 # issued for another site
])
def test_invalid_clerk_tokens_are_rejected(auth_on, monkeypatch, bad):
    token, pub = _signed_token(_claims(**bad))
    _use_key(monkeypatch, pub)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert upload(client).status_code == 401


def test_token_signed_by_another_key_is_rejected(auth_on, monkeypatch):
    token, _ = _signed_token(_claims())
    _, other_pub = _signed_token(_claims())
    _use_key(monkeypatch, other_pub)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert upload(client).status_code == 401


def test_publishable_key_gives_the_clerk_domain(monkeypatch):
    import base64
    from app.auth import clerk_domain
    encoded = base64.b64encode(b"happy-cat-12.clerk.accounts.dev$").decode()
    monkeypatch.setattr(settings, "clerk_publishable_key", f"pk_test_{encoded}")
    assert clerk_domain() == "happy-cat-12.clerk.accounts.dev"
