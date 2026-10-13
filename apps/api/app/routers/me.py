"""Current user endpoints."""

import datetime
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.auth import CurrentUser

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    plan: str
    created_at: datetime.datetime


@router.get("/me")
def me(user: CurrentUser) -> MeOut:
    return MeOut.model_validate(user)
