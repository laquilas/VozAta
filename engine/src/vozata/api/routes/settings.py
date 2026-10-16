"""`GET /settings`: current values (secrets masked) and the key schema; `PUT` updates `.env`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import error_body
from vozata.api.schemas import SettingSchema, SettingsUpdate, SettingsUpdated, SettingsView
from vozata.config import ConfigError
from vozata.settings_file import SettingsWriteError
from vozata.settings_view import settings_schema, settings_values

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsView, response_model_by_alias=True)
def get_settings(c: Annotated[ApiContainer, Depends(container)]) -> SettingsView:
    return SettingsView(
        values=settings_values(c.settings_file.current),
        schema=[SettingSchema(**item) for item in settings_schema()],
    )


@router.put(
    "/settings",
    response_model=SettingsUpdated,
    responses={422: {"description": "invalid_setting: `error.key` names the rejected key"}},
)
def put_settings(
    update: SettingsUpdate, c: Annotated[ApiContainer, Depends(container)]
) -> SettingsUpdated | JSONResponse:
    try:
        restart = c.settings_file.update(update.values)
    except ConfigError as error:
        body = error_body("invalid_setting", error.render(c.localizer))
        body["error"]["key"] = error.key
        return JSONResponse(body, status_code=422)
    except SettingsWriteError as error:
        message = c.localizer.t("errors.api.settings_write_failed", reason=error)
        return JSONResponse(error_body("settings_write_failed", message), status_code=503)
    return SettingsUpdated(
        values=settings_values(c.settings_file.current), restart_required=restart
    )
