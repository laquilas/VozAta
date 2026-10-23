"""Which apps use the audio devices right now (phase 54), through the Windows audio session API.

Every active render and capture endpoint's `IAudioSessionManager2` is enumerated; a session in
state Active (playing or capturing now) names its process. COM is initialized once per thread:
the meeting detector calls this from its own polling thread. Thin by design (needs Windows and
real devices): covered by the phase's manual check.
"""

from __future__ import annotations

import threading

ACTIVE_ENDPOINTS = 1  # DEVICE_STATE_ACTIVE
ALL_FLOWS = 2  # eAll: render and capture
SESSION_ACTIVE = 1  # AudioSessionStateActive


class WindowsAudioSessions:  # pragma: no cover - Windows COM and real devices
    """`AudioSessionMonitor` over pycaw / comtypes."""

    def __init__(self) -> None:
        self._initialized = threading.local()

    def active_apps(self) -> set[str]:
        import comtypes
        from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
        from pycaw.constants import CLSID_MMDeviceEnumerator

        if not getattr(self._initialized, "done", False):
            comtypes.CoInitialize()
            self._initialized.done = True
        enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
        )
        endpoints = enumerator.EnumAudioEndpoints(ALL_FLOWS, ACTIVE_ENDPOINTS)
        names: set[str] = set()
        for index in range(endpoints.GetCount()):
            device = endpoints.Item(index)
            manager = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            manager = manager.QueryInterface(IAudioSessionManager2)
            sessions = manager.GetSessionEnumerator()
            for position in range(sessions.GetCount()):
                control = sessions.GetSession(position).QueryInterface(IAudioSessionControl2)
                if control.GetState() != SESSION_ACTIVE:
                    continue
                name = _process_name(control.GetProcessId())
                if name:
                    names.add(name)
        return names


def _process_name(pid: int) -> str | None:  # pragma: no cover - real processes
    if not pid:
        return None  # the system sounds session
    import psutil

    try:
        return str(psutil.Process(pid).name())
    except psutil.Error:
        return None  # the process ended meanwhile
