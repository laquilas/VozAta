from __future__ import annotations

from pathlib import Path

from tests.api.conftest import Api
from vozata.config import Settings
from vozata.domain import AppLanguage

SESSION = "20261015_202358"


def test_templates_are_listed_in_order_with_localized_names(api: Api) -> None:
    response = api.client.get("/templates")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "general", "name": "General meeting"},
        {"id": "daily", "name": "Daily stand-up"},
        {"id": "one_on_one", "name": "One-on-one"},
        {"id": "client", "name": "Client meeting"},
        {"id": "retrospective", "name": "Retrospective"},
    ]


def test_template_names_follow_the_app_language(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "recordings", app_language=AppLanguage.PT_BR)
    api = Api(tmp_path, settings)

    with api.client:
        names = [item["name"] for item in api.client.get("/templates").json()]

    assert names[0] == "Reunião geral"
    assert names[3] == "Reunião com cliente"


def test_template_names_follow_a_saved_app_language(api: Api) -> None:
    api.client.put("/settings", json={"values": {"APP_LANGUAGE": "es"}})

    assert api.client.get("/templates").json()[0] == {"id": "general", "name": "Reunión general"}


def test_the_template_chosen_at_start_reaches_the_session(api: Api) -> None:
    response = api.client.post("/sessions", json={"template": "daily"})

    assert response.status_code == 201
    assert api.factory.sessions[0].options.template == "daily"


def test_start_without_a_template_leaves_the_default_to_the_engine(api: Api) -> None:
    api.client.post("/sessions", json={})

    assert api.factory.sessions[0].options.template is None


def test_an_unknown_template_at_start_is_422_and_nothing_starts(api: Api) -> None:
    response = api.client.post("/sessions", json={"template": "weekly"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unknown_template"
    assert error["message"] == (
        'Unknown minutes template "weekly". '
        "Use one of: general, daily, one_on_one, client, retrospective."
    )
    assert api.factory.sessions == []


def _recorded(api: Api) -> None:
    api.store.paths(SESSION).root.mkdir(parents=True)
    api.store.write_meta(SESSION, {"id": SESSION, "status": "done"})


def test_regenerate_passes_the_template_or_none(api: Api) -> None:
    _recorded(api)

    with_template = api.client.post(f"/sessions/{SESSION}/minutes", json={"template": "client"})
    without_body = api.client.post(f"/sessions/{SESSION}/minutes")

    assert (with_template.status_code, without_body.status_code) == (202, 202)
    assert api.regenerated == [(SESSION, "client"), (SESSION, None)]


def test_an_unknown_template_on_regenerate_is_422(api: Api) -> None:
    _recorded(api)

    response = api.client.post(f"/sessions/{SESSION}/minutes", json={"template": "weekly"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_template"
    assert api.regenerated == []
