"""Clerk webhook: Svix signature verification and user lifecycle."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import User
from app.db.session import get_sessionmaker
from app.main import create_app

SECRET = "whsec_MDAwMDAwMDAwMDAwMDAwMDAwMDAwMA=="

client = TestClient(create_app())


def sign(payload: str) -> dict[str, str]:
    msg_id = f"msg_{uuid.uuid4().hex[:10]}"
    ts = str(int(time.time()))
    to_sign = f"{msg_id}.{ts}.{payload}".encode()
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}"}


def event(event_type: str, clerk_id: str, email: str | None) -> str:
    data: dict[str, Any] = {"id": clerk_id}
    if email is not None:
        data["email_addresses"] = [{"id": "em_1", "email_address": email}]
        data["primary_email_address_id"] = "em_1"
    return json.dumps({"type": event_type, "data": data})


def get_user(clerk_id: str) -> User | None:
    with get_sessionmaker()() as session:
        return session.scalar(select(User).where(User.clerk_id == clerk_id))


def test_invalid_signature_rejected(clean_users: None) -> None:
    payload = event("user.created", "user_sig", "a@b.com")
    headers = sign(payload) | {"svix-signature": "v1,invalid"}
    resp = client.post("/webhooks/clerk", content=payload, headers=headers)
    assert resp.status_code == 400
    assert get_user("user_sig") is None


def test_user_created_provisions_row(clean_users: None) -> None:
    payload = event("user.created", "user_abc", "colin@example.com")
    resp = client.post("/webhooks/clerk", content=payload, headers=sign(payload))
    assert resp.status_code == 200
    user = get_user("user_abc")
    assert user is not None and user.email == "colin@example.com"
    assert user.plan == "free"


def test_user_updated_changes_email(clean_users: None) -> None:
    p1 = event("user.created", "user_upd", "old@example.com")
    client.post("/webhooks/clerk", content=p1, headers=sign(p1))
    p2 = event("user.updated", "user_upd", "new@example.com")
    client.post("/webhooks/clerk", content=p2, headers=sign(p2))
    user = get_user("user_upd")
    assert user is not None and user.email == "new@example.com"


def test_user_deleted_removes_row(clean_users: None) -> None:
    p1 = event("user.created", "user_del", "x@example.com")
    client.post("/webhooks/clerk", content=p1, headers=sign(p1))
    p2 = json.dumps({"type": "user.deleted", "data": {"id": "user_del"}})
    client.post("/webhooks/clerk", content=p2, headers=sign(p2))
    assert get_user("user_del") is None


def test_replay_of_created_is_idempotent(clean_users: None) -> None:
    payload = event("user.created", "user_rep", "r@example.com")
    client.post("/webhooks/clerk", content=payload, headers=sign(payload))
    resp = client.post("/webhooks/clerk", content=payload, headers=sign(payload))
    assert resp.status_code == 200  # updated path, no unique violation
