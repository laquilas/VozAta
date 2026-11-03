"""`python -m vozata.recorder` (also `python -m vozata recorder`, `vozata-recorder.exe`).

Serves the recorder API on `RECORDER_PORT` until `POST /shutdown` or Ctrl+C. When the port is
taken by a recorder that answers, exits 0 at once ("already running"): the desktop app can
start it every time without checking first.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from vozata import __version__
from vozata.recorder.settings import RecorderSettings, load_recorder_settings

_log = logging.getLogger("vozata.recorder")

ALREADY_RUNNING = 0
FAILED = 1
RECORDING = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vozata-recorder", description="VozAta recorder")
    parser.add_argument("--port", type=int, help="API port (default RECORDER_PORT, 8769)")
    parser.add_argument("--output-dir", type=Path, help="recordings folder (default OUTPUT_DIR)")
    parser.add_argument("--version", action="version", version=f"vozata-recorder {__version__}")
    parser.add_argument(
        "--stop", action="store_true", help="stop a running recorder unless it is recording"
    )
    return parser


def answers(port: int, timeout: float = 1.0) -> bool:
    """A recorder answers `/health` on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as reply:
            return json.loads(reply.read()).get("recorder") == "ok"
    except (OSError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_recorder_settings()
    overrides = {}
    if args.port is not None:
        overrides["port"] = args.port
    if args.output_dir is not None:
        overrides["output_dir"] = args.output_dir
    if overrides:
        settings = RecorderSettings(**{**settings.__dict__, **overrides})
    if args.stop:
        return stop(settings.port)
    return serve(settings)


def stop(port: int) -> int:
    """Ask a running recorder to quit: 0 when it quit or none runs, RECORDING while recording."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/shutdown", method="POST")
    try:
        urllib.request.urlopen(request, timeout=5).close()
    except urllib.error.HTTPError as error:
        if error.code == 409:
            print("The recorder is recording; it keeps running")
            return RECORDING
        return FAILED
    except OSError:
        pass  # none runs
    return 0


def serve(settings: RecorderSettings) -> int:
    from vozata.audio.catalog import WasapiCatalog
    from vozata.audio.portaudio import PortAudioThread
    from vozata.recorder.app import RecorderApp
    from vozata.recorder.http import RecorderServer
    from vozata.recorder.lock import remove_lock, write_lock
    from vozata.recorder.manifest import live_dir

    live = live_dir(settings.output_dir)
    live.mkdir(parents=True, exist_ok=True)
    handler = _log_to(live / "recorder.log")
    try:
        app = RecorderApp(settings, WasapiCatalog(), PortAudioThread)
        try:
            server = RecorderServer(settings.port, app.router)
        except OSError as error:
            if answers(settings.port):
                print(f"A recorder already runs on port {settings.port}")
                return ALREADY_RUNNING
            _log.error("Cannot listen on port %s: %s", settings.port, error)
            return FAILED
        write_lock(live, server.port, app.started_at)
        _log.info("Recorder %s on port %s, recordings in %s", __version__, server.port, live)
        app.start_up()
        watcher = threading.Thread(
            target=lambda: (app.shutdown_requested.wait(), server.shutdown()), daemon=True
        )
        watcher.start()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda *_: app.shutdown_requested.set())
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, lambda *_: app.shutdown_requested.set())
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            app.close()
            server.server_close()
            remove_lock(live)
            _log.info("Recorder stopped")
        return 0
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def _log_to(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    return handler


if __name__ == "__main__":
    sys.exit(main())
