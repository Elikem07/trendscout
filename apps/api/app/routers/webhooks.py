"""Inbound webhooks. Clerk user lifecycle events provision local users.

Clerk signs webhooks with Svix. Verification is mandatory; an unsigned or
mis signed request is rejected before any parsing side effects.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from svix.webhooks import Webhook

from app.config import get_settings
from app.db.models import ApiKey, User
from app.db.session import get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _primary_email(data: dict[str, Any]) -> str | None:
    addresses = {a.get("id"): a.get("email_address") for a in data.get("email_addresses", [])}
    primary = addresses.get(data.get("primary_email_address_id"))
    if primary:
        return str(primary)
    for value in addresses.values():
        if value:
            return str(value)
    return None


@router.post("/clerk", status_code=status.HTTP_200_OK)
async def clerk_webhook(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> dict[str, bool]:
    secret = get_settings().clerk_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()
    try:
        event: dict[str, Any] = Webhook(secret).verify(payload, dict(request.headers))
    except Exception as exc:  # noqa: BLE001 - any verify failure = unverifiable
        raise HTTPException(status_code=400, detail="Invalid signature") from exc

    event_type = str(event.get("type", ""))
    data: dict[str, Any] = event.get("data", {})
    clerk_id = str(data.get("id", ""))
    if not clerk_id:
        return {"received": True}

    user = db.scalar(select(User).where(User.clerk_id == clerk_id))

    if event_type in ("user.created", "user.updated"):
        email = _primary_email(data)
        if email is None:
            return {"received": True}
        if user is None:
            db.add(User(clerk_id=clerk_id, email=email))
        else:
            user.email = email
        db.commit()
    elif event_type == "user.deleted" and user is not None:
        db.execute(delete(ApiKey).where(ApiKey.user_id == user.id))
        db.delete(user)
        db.commit()

    return {"received": True}
