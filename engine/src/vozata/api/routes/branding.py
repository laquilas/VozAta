"""`GET /favicon.ico` and the API docs pages (`/docs`, `/redoc`) that show the VozAta logo."""

from __future__ import annotations

from importlib.resources import files

from fastapi import APIRouter, Request, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

FAVICON_PATH = "/favicon.ico"

router = APIRouter(include_in_schema=False)


def favicon_bytes() -> bytes:
    """The logo .ico shipped as package data (copy of `assets/web/favicon.ico`)."""
    return files("vozata.api").joinpath("static", "favicon.ico").read_bytes()


@router.get(FAVICON_PATH)
def favicon() -> Response:
    return Response(
        content=favicon_bytes(),
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/docs")
def swagger_ui(request: Request) -> HTMLResponse:
    app = request.app
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_favicon_url=FAVICON_PATH,
    )


@router.get("/redoc")
def redoc(request: Request) -> HTMLResponse:
    app = request.app
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_favicon_url=FAVICON_PATH,
    )
