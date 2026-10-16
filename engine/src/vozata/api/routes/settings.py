"""`GET /settings`: current values (secrets masked) and the key schema. `PUT` is phase 10."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import SettingSchema, SettingsView
from vozata.settings_view import settings_schema, settings_values

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsView, response_model_by_alias=True)
def get_settings(c: Annotated[ApiContainer, Depends(container)]) -> SettingsView:
    return SettingsView(
        values=settings_values(c.settings),
        schema=[SettingSchema(**item) for item in settings_schema()],
    )
