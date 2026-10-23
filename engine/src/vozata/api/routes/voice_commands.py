"""`GET|PUT /voice-commands`: the phrases said after the wake word while recording (phase 50)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import VoiceCommandOut, VoiceCommandsBody, VoiceCommandsView
from vozata.commands.store import InvalidCommandsError, VoiceCommandStore, default_commands
from vozata.domain import VoiceCommand

router = APIRouter(tags=["voice commands"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/voice-commands", response_model=VoiceCommandsView)
def get_voice_commands(c: Container) -> VoiceCommandsView:
    """The saved list (else the defaults) and the defaults of the app language."""
    return VoiceCommandsView(
        commands=_out(_store(c).read()), defaults=_out(default_commands(c.localizer))
    )


@router.put("/voice-commands", response_model=VoiceCommandsView)
def put_voice_commands(body: VoiceCommandsBody, c: Container) -> VoiceCommandsView:
    """Replace the list (from the next recording); it comes back trimmed."""
    commands = [VoiceCommand(item.phrase, item.action, item.question) for item in body.commands]
    try:
        saved = _store(c).write(commands)
    except InvalidCommandsError as error:
        raise ApiError(422, "invalid_voice_commands", reason=error) from None
    except OSError as error:
        raise ApiError(503, "voice_commands_failed", reason=error) from None
    return VoiceCommandsView(commands=_out(saved), defaults=_out(default_commands(c.localizer)))


def _store(c: ApiContainer) -> VoiceCommandStore:
    return VoiceCommandStore(c.voice_commands_file(), c.localizer)


def _out(commands: list[VoiceCommand]) -> list[VoiceCommandOut]:
    return [VoiceCommandOut(**command.to_dict()) for command in commands]
