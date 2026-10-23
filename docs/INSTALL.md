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
| ~4 GB of free disk | program (~1.5 GB with the CUDA libraries) + speech model (~1.6 GB, downloaded on first use) | recordings use ~10 MB per minute |

Python and .NET are **not** needed: both are inside the installer.

## Install

1. Download `VozAta-Setup-<version>.exe` from the
   [GitHub releases](https://github.com/laquilas/VozAta/releases).
2. Run it. It installs for your user only, in `%LOCALAPPDATA%\Programs\VozAta`, and adds VozAta to
   the Start menu.

## First run

- The app starts its engine by itself. The **first recording downloads the Whisper speech model**
  (~1.6 GB) into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`); the status line says
  "Loading the speech model — already recording" meanwhile, and nothing you say is lost.
- **Choose your devices** on the Recording tab: the microphone and the system output you hear the
  meeting on. The meters show whether sound arrives.
- **Settings tab**: interface and meeting language, minutes model, how audio is cut, the external
  speech API, and more. Most changes apply from the next recording; a few ask to restart the engine.

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

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| "The audio device … did not open within 20 s" | Another app may hold the device, or the Windows audio service is stuck: restart *Windows Audio* (services) or the PC. |
| The engine does not start | Check that no other program uses port 8765 (`API_PORT` in `%APPDATA%\VozAta\.env`). To see the engine's messages, close VozAta, open a terminal in `%APPDATA%\VozAta` and run `"%LOCALAPPDATA%\Programs\VozAta\engine\vozata-engine.exe" serve`. |
| Transcription is slow | Without an NVIDIA GPU (or a recent driver) Whisper runs on the CPU. Install the NVIDIA driver, or use a smaller CPU model in the settings. |
| "Minutes: … not reachable (start Ollama)" | Start Ollama and pull the model shown in the status bar. To use Ollama on another PC of your network, see [Using Ollama on another PC](remote-ollama.md); to move speech recognition to a GPU PC, see [Using a VozAta worker on another PC](remote-worker.md). |
| No sound from the system audio | Pick the output device you actually listen on (headphones vs. speakers) on the Recording tab. |

## Building the installer yourself

```powershell
python -m pip install -e "engine[cuda,package]"   # engine, CUDA libraries, PyInstaller
pwsh packaging/build.ps1 -Version 1.0.0           # needs the .NET 10 SDK and Inno Setup 6
pwsh packaging/build.ps1 -Version 1.0.0 -CpuOnly  # smaller build without the CUDA libraries
```

The installer lands in `build/installer/`. The GitHub workflow `Release` builds it on every `v*` tag
and can be run by hand.
