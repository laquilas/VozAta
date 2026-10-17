from __future__ import annotations

from pathlib import Path

import pytest

from tests.api.conftest import Api
from vozata.api.routes.branding import favicon_bytes

REPO_FAVICON = Path(__file__).resolve().parents[3] / "assets" / "web" / "favicon.ico"


def test_favicon_serves_the_logo_icon(api: Api) -> None:
    response = api.client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"
    assert "max-age" in response.headers["cache-control"]
    assert response.content == favicon_bytes()
    assert response.content[:4] == b"\x00\x00\x01\x00"  # ICO header


@pytest.mark.skipif(not REPO_FAVICON.exists(), reason="repository assets not available")
def test_packaged_favicon_matches_the_repository_asset() -> None:
    assert favicon_bytes() == REPO_FAVICON.read_bytes()


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_docs_pages_use_the_favicon(api: Api, path: str) -> None:
    response = api.client.get(path)

    assert response.status_code == 200
    assert 'href="/favicon.ico"' in response.text
    assert "/openapi.json" in response.text


def test_branding_routes_stay_out_of_the_openapi_schema(api: Api) -> None:
    paths = api.client.get("/openapi.json").json()["paths"]

    assert not {"/favicon.ico", "/docs", "/redoc"} & paths.keys()
