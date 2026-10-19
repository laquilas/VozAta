"""`GET /sessions/{id}/audio/{track}` (phase 32): a session's audio as a WAV stream;
`DELETE /sessions/{id}/audio` (phase 39) removes it and keeps the session."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import StreamingResponse

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.wav_stream import RangeNotSatisfiableError, byte_range, wav_bytes
from vozata.audio.pcm import wav_size
from vozata.domain import AudioTrack, Channel

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]
WAV = "audio/wav"


@router.get(
    "/sessions/{session_id}/audio/{track}",
    response_class=StreamingResponse,
    responses={
        200: {"content": {WAV: {}}, "description": "The whole track as a WAV file."},
        206: {"content": {WAV: {}}, "description": "The bytes named by `Range`."},
        416: {"description": "The `Range` names no bytes of the file."},
    },
)
def session_audio(
    session_id: str,
    track: str,
    c: Container,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """`mic`, `system` or `mixed` as 16-bit PCM WAV, generated from the stored audio.

    `Range: bytes=...` (one range) gives `206` with `Content-Range`; an unsatisfiable range
    gives `416`. An unknown session, track or a track never recorded gives `404`.
    """
    c.store.read_meta(session_id)  # SessionNotFoundError: 404 session_not_found
    pcm = None
    if track in set(AudioTrack) and c.audio is not None:
        pcm = c.audio.track(session_id, AudioTrack(track))
    if pcm is None:
        raise ApiError(404, "audio_not_found", id=session_id, track=track)
    size = wav_size(pcm)
    headers = {"Accept-Ranges": "bytes"}
    try:
        wanted = byte_range(range_header, size)
    except RangeNotSatisfiableError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if wanted is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(wav_bytes(pcm), media_type=WAV, headers=headers)
    first, last = wanted
    headers["Content-Length"] = str(last - first + 1)
    headers["Content-Range"] = f"bytes {first}-{last}/{size}"
    return StreamingResponse(
        wav_bytes(pcm, first, last), status_code=206, media_type=WAV, headers=headers
    )


@router.delete("/sessions/{session_id}/audio", status_code=status.HTTP_204_NO_CONTENT)
def delete_session_audio(session_id: str, c: Container) -> None:
    """Remove a meeting's audio and keep its transcript, minutes and action items (phase 39):
    permanent in the database (space reclaimed in the background), to the Recycle Bin for the
    file backend. `409 session_still_active` for the live session, `404 no_audio` without audio.
    """
    c.store.read_meta(session_id)  # SessionNotFoundError: 404 session_not_found
    audio = c.audio

    def discard(session_id: str) -> None:  # checked once the session is known not to be live
        if audio is None or not any(audio.track(session_id, AudioTrack(ch)) for ch in Channel):
            raise ApiError(404, "no_audio", id=session_id)
        audio.discard(session_id)

    c.manager.discard_audio(session_id, discard)
