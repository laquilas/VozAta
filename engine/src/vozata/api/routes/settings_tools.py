"""Config page helpers (phase 38): option lists, connection tests and the audio cache."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import (
    CacheCleared,
    ConnectionTestResult,
    SettingOptionItem,
    SettingOptionsView,
)
from vozata.connection_checks import CheckTarget

router = APIRouter(tags=["settings"])


@router.get("/settings/options", response_model=SettingOptionsView)
def setting_options(c: Annotated[ApiContainer, Depends(container)]) -> SettingOptionsView:
    lists = c.setting_options()
    return SettingOptionsView(
        options={
            source: [
                SettingOptionItem(value=item.value, label=item.label, available=item.available)
                for item in items
            ]
            for source, items in lists.options.items()
        },
        reachable=lists.reachable,
    )


@router.post("/settings/test/{target}", response_model=ConnectionTestResult)
def test_connection(
    target: CheckTarget, c: Annotated[ApiContainer, Depends(container)]
) -> ConnectionTestResult:
    result = c.connection_check(target, c.settings_file.current)  # the saved settings
    message = c.localizer.t(f"settings_test.{result.code}", **result.params)
    return ConnectionTestResult(ok=result.ok, message=message)


@router.delete("/storage/cache", response_model=CacheCleared)
def clear_audio_cache(c: Annotated[ApiContainer, Depends(container)]) -> CacheCleared:
    """Empty the WAV cache (phase 32); files in use (a player, the diarizer) are kept."""
    return CacheCleared(freed_bytes=c.audio_cache.clear() if c.audio_cache is not None else 0)
