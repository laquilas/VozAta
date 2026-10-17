"""Phase 23 configuration keys: action-item extraction and the task export targets."""

from __future__ import annotations

import pytest

from vozata.config import ConfigError, load_settings
from vozata.settings_view import settings_values


def test_action_item_defaults() -> None:
    defaults = load_settings(env={})

    assert defaults.extract_action_items is True
    assert (defaults.azdo_org_url, defaults.azdo_project, defaults.azdo_pat) == (None, None, None)
    assert (defaults.github_repo, defaults.github_token) == (None, None)
    values = settings_values(defaults)
    assert (values["AZDO_PAT"], values["GITHUB_TOKEN"]) == (None, None)  # nothing to mask


def test_action_item_values_and_secret_masks() -> None:
    settings = load_settings(
        env={
            "EXTRACT_ACTION_ITEMS": "false",
            "AZDO_ORG_URL": "https://dev.azure.com/acme/",
            "AZDO_PROJECT": "VozAta",
            "AZDO_PAT": "pat-secret",
            "GITHUB_REPO": "acme/vozata",
            "GITHUB_TOKEN": "ghp_secret",
        }
    )

    assert settings.extract_action_items is False
    assert settings.azdo_org_url == "https://dev.azure.com/acme"
    assert (settings.azdo_project, settings.azdo_pat) == ("VozAta", "pat-secret")
    assert (settings.github_repo, settings.github_token) == ("acme/vozata", "ghp_secret")
    values = settings_values(settings)
    assert (values["AZDO_PAT"], values["GITHUB_TOKEN"]) == ("********", "********")
    assert values["AZDO_ORG_URL"] == "https://dev.azure.com/acme"


def test_azdo_org_url_must_be_a_url() -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={"AZDO_ORG_URL": "dev.azure.com/acme"})

    assert (caught.value.key, caught.value.message_key) == ("AZDO_ORG_URL", "invalid_url")
