# Installing VozAta

VozAta records your microphone and the computer's sound, transcribes the meeting while it happens
and writes the minutes with a local language model. Everything runs on your computer unless you
choose an external speech API in the settings.

## Requirements

| What | Why | Notes |
|------|-----|-------|
| Windows 10 or 11, 64-bit | the app and the audio capture (WASAPI) | no administrator rights needed |
| NVIDIA GPU + recent driver (recommended) | fast transcription with Whisper | 6 GB of memory is enough; without an NVIDIA GPU transcription runs on the CPU (slower, smaller model) |
| [Ollama](https://ollama.com) (optional) | the meeting minutes | after installing it run `ollama pull qwen2.5:7b`; without Ollama you still get transcripts |
| ~4 GB of free disk | program (~0.6 GB) + speech model (~1.6 GB, downloaded on first use); GPU support +1.8 GB, speaker identification +4.6 GB, both optional | recordings use ~10 MB per minute |

Python and .NET are **not** needed: both are inside the installer.

## Install

1. Download `VozAta-Setup-<version>.exe` from the
   [GitHub releases](https://github.com/laquilas/VozAta/releases).
2. Run it. It installs for your user only, in `%LOCALAPPDATA%\Programs\VozAta`, and adds VozAta to
   the Start menu.

A GPU PC that transcribes for the other PCs of the network gets its own installer,
`VozAta-Worker-Setup-<version>.exe` (VozAta Worker and the engine, without the meeting app; it
installs in `%LOCALAPPDATA%\Programs\VozAta Worker`): see
[Using a VozAta worker on another PC](remote-worker.md).

## First run

- The app starts its engine by itself. The **first recording downloads the Whisper speech model**
  (~1.6 GB) into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`); the status line says
  "Loading the speech model — already recording" meanwhile, and nothing you say is lost.
- **Choose your devices** on the Recording tab: the microphone and the system output you hear the
  meeting on. The meters show whether sound arrives.
- **Settings tab**: interface and meeting language, minutes model, how audio is cut, the external
  speech API, and more. Most changes apply from the next recording; a few ask to restart the engine.

## When a meeting starts

When Microsoft Teams, Zoom, Webex, Slack or Discord is in a call and VozAta is not recording,
a banner offers **Record** / **Not now**. VozAta never starts recording by itself: you decide,
and you are responsible for telling the other participants. It looks at which programs use
the audio devices (Windows audio sessions), so a call in a browser (Google Meet) is not
noticed. Turn it off, or change the list of programs, on **Config → General** ("Suggest
recording meeting calls", "Meeting apps").

## Where things are

| What | Where | Kept when uninstalling |
|------|-------|------------------------|
| Recordings (audio, transcript, minutes) | `Documents\VozAta` | yes |
| Engine settings (`.env`) | `%APPDATA%\VozAta\.env` | yes |
| Desktop preferences (devices, window, tray) | `%APPDATA%\VozAta\ui.json` | yes |
| Program files | `%LOCALAPPDATA%\Programs\VozAta` | removed |
| Speech model cache | `%USERPROFILE%\.cache\huggingface` | yes (delete it to free ~1.6 GB) |

## Uninstall

Windows Settings → Apps → VozAta → Uninstall. Recordings and settings stay; delete the folders above
to remove them too.

## GPU support

Speech recognition runs much faster on an NVIDIA GPU, through the NVIDIA CUDA libraries (cuBLAS
and cuDNN, about 1.2 GB to download, 1.8 GB on disk). The installers do not carry them: on a PC
with an NVIDIA driver, the setup shows **Download GPU support for speech recognition**, ticked;
untick it to stay on the CPU. A console window shows the download. Later:
`"%LOCALAPPDATA%\Programs\VozAta\engine\vozata-engine.exe" cuda install` (`cuda status`,
`cuda remove`), or run the setup again. The files go into `%LOCALAPPDATA%\VozAta\cuda`, are
checked against the SHA-256 PyPI publishes, are shared by VozAta and VozAta Worker, and are removed
with the last of them. Without them speech recognition uses the CPU model (`WHISPER_CPU_MODEL`).

## Speaker identification

Telling the remote participants apart (User 1, User 2, ...) needs pyannote and PyTorch (about
3 GB to download, 4.6 GB on disk with CUDA), which the installers do not carry. Download them
once on the PC that runs them:

- during the setup (either installer): tick **Download speaker identification now** (a console
  window shows the download); running the setup again later offers it again;
- on a worker PC, later, in **VozAta Worker**: **Download speaker identification** on the *Tasks
  for the other PCs* card;
- or in a terminal: `"%LOCALAPPDATA%\Programs\VozAta\engine\vozata-engine.exe" speakers install`
  (`speakers status` says whether it is there, `speakers remove` deletes it).

It goes into `%LOCALAPPDATA%\VozAta\speakers` (a Python 3.13 environment made with `uv`; the CUDA
build of PyTorch when the PC has an NVIDIA GPU), shared by VozAta and VozAta Worker on the same
PC, and removed when the last of them is uninstalled. Restart
VozAta afterwards. It also needs a Hugging Face token (`HF_TOKEN`) and the pyannote model terms
accepted, as before.

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| "The audio device … did not open within 20 s" | Another app may hold the device, or the Windows audio service is stuck: restart *Windows Audio* (services) or the PC. |
| The engine does not start | Check that no other program uses port 8765 (`API_PORT` in `%APPDATA%\VozAta\.env`). To see the engine's messages, close VozAta, open a terminal in `%APPDATA%\VozAta` and run `"%LOCALAPPDATA%\Programs\VozAta\engine\vozata-engine.exe" serve`. |
| Transcription is slow | Without an NVIDIA GPU, a recent driver and the [GPU support](#gpu-support) download, Whisper runs on the CPU. Run `vozata-engine cuda status`; install the driver and `cuda install`, or use a smaller CPU model in the settings. |
| "Minutes: … not reachable (start Ollama)" | Start Ollama and pull the model shown in the status bar. To use Ollama on another PC of your network, see [Using Ollama on another PC](remote-ollama.md); to move speech recognition to a GPU PC, see [Using a VozAta worker on another PC](remote-worker.md). |
| No sound from the system audio | Pick the output device you actually listen on (headphones vs. speakers) on the Recording tab. |

## Building the installer yourself

```powershell
python -m pip install -e "engine[translation,package]"  # engine, translation, PyInstaller, uv
pwsh packaging/build.ps1 -Version 1.0.0                  # needs the .NET 10 SDK and Inno Setup 6 or 7
```

Neither the CUDA libraries nor speaker identification are in the installers: the PC that needs
them downloads them, see [GPU support](#gpu-support) and
[Speaker identification](#speaker-identification).

Both installers (`VozAta-Setup-<v>.exe` and `VozAta-Worker-Setup-<v>.exe`) land in
`build/installer/`. The GitHub workflow `Release` builds it on every `v*` tag
and can be run by hand.
