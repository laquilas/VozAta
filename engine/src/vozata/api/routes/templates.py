"""`GET /templates`: the minutes templates with names in `APP_LANGUAGE` (phase 20)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import TemplateInfo

router = APIRouter(tags=["templates"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/templates", response_model=list[TemplateInfo])
def list_templates(c: Container) -> list[dict[str, str]]:
    language = c.settings.app_language
    return [
        {"id": template.id, "name": template.localized(language).name}
        for template in c.templates.all()
    ]


def check_template(c: ApiContainer, template: str | None) -> None:
    """`422 unknown_template` unless `template` is None or a bundled template id."""
    if template is not None and template not in c.templates:
        raise ApiError(422, "unknown_template", id=template, allowed=", ".join(c.templates.ids()))
