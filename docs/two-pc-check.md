# Two-PC check of the VozAta worker

A repeatable end-to-end check of the worker across two PCs: run it after every change to the
worker, the pairing or the packaging. The **GPU PC** runs VozAta Worker; the **client PC** records
and runs the script. Part of it is a script, part of it is done by hand in the app.

## Before you start

| Where | What |
|-------|------|
| Both PCs | On the same local network, with the **Private** network profile (Windows Settings → Network). |
| GPU PC | VozAta Worker installed (`VozAta-Worker-Setup-<v>.exe`), with speaker identification downloaded (**Download speaker identification** in VozAta Worker) to check it, see [What the worker offers](remote-worker.md#what-the-worker-offers). |
| GPU PC | `HF_TOKEN=...` in `%APPDATA%\VozAta\worker\.env` (for speakers), then VozAta Worker opened, **Allow on the network** done once. The **Tasks for the other PCs** card lists all three tasks as offered. |
| Client PC | The repository with its `.venv` (`pip install -e "engine[dev]"`), for the script. VozAta installed, for the manual steps. |
| Client PC | For the pre-emption step: a working microphone and output device (the script records and plays a WAV on the default output, so the system track hears speech). |

The script never touches your settings: it starts its own client engine in a new temporary folder
with its own port, database and `.env`. Pairing it gives that engine the worker token, not yours.

## The script

On the client PC, from the repository root, with the code VozAta Worker shows on the GPU PC:

```powershell
.venv\Scripts\python scripts\two_pc_check.py --code 123456 --record --play meeting.wav
```

`meeting.wav` is any recording with two or more people talking (16-bit PCM, about 30 s is
enough). Other options: `--worker-name <name>` when several workers answer; `--worker-url
http://<GPU PC>:8766 --token <token>` to skip discovery and pairing (PCs on different subnets);
`--no-speakers` for a worker without speakers; `--local-speech` when the client should transcribe
on its own GPU (see pre-emption below); `--folder <dir>` to keep the scratch folder.

| Step | What it does | Passes when |
|------|--------------|-------------|
| discover | `GET /worker/discover` on the scratch engine | the worker answers with a network (not loopback) address |
| pair | `POST /worker/pair` with the code | the worker accepts the code; URL and token are saved in the scratch `.env` |
| health | the worker's `/health` with the token | it offers speech, translation and (unless `--no-speakers`) speakers |
| translate | a Portuguese sentence to English on the worker | the English text comes back (the first time the worker downloads opus-mt, ~160 MB) |
| diarize + cancel | a diarization job on the worker, cancelled once running | the job is `cancelled` within 5 s |
| pre-emption (`--record`) | records the WAV, stops; when the queue's diarize step runs on the worker, starts a second recording with live transcription | see below; then the first meeting finishes with its speakers |

**Pre-emption, what to expect.** A recording takes the queue's GPU steps away only when it loads a
model on **this** PC's GPU. With speech on the worker (the default) the recording uses no GPU
here, so the diarize step keeps running on the worker: the script expects that. With
`--local-speech` (speech recognition on this PC, speakers on the worker) and an NVIDIA GPU here,
the live Whisper takes the GPU: the diarize step goes `paused`, the worker job is cancelled, and
the step is redone after the second recording. The script expects a pause only in that case.

The script prints a table (PASS / FAIL / SKIP) and exits with 1 when a step failed.

## By hand, in the apps

| # | Do | Expect |
|---|----|--------|
| 1 | Client PC: VozAta → Config → Worker → **Find workers** | the GPU PC is listed with its name, address and GPU |
| 2 | Pick it, type the code shown in VozAta Worker, **Pair** | a success message; URL and token are filled in |
| 3 | **Test** next to the address | "ok", with the worker's version and GPU |
| 4 | Tick the three **Use the worker for** switches, **Save**, restart if asked; reopen Config | the three switches are still ticked |
| 5 | Start a recording | the sidebar shows **Worker: <GPU PC>** under the engine status; the live transcript arrives |
| 6 | Turn on live translation for a recording | translated lines arrive (from the worker) |
| 7 | Stop; wait for the meeting to be processed | its speakers are found (Speaker identification on the worker) |
| 8 | On the GPU PC, **Exit** VozAta Worker from the tray; start a recording on the client | a notification says the worker did not answer and the task runs on this PC; the sidebar shows **This PC (worker off)** with a red dot |
| 9 | Open VozAta Worker again; start a new recording | the sidebar shows **Worker: <GPU PC>** again |

## Results

Record each run in `docs/roadmap/phases/52-two-pc-check.md` (*Decisions and notes*): date, the two
PCs, the script's table and what the manual steps showed.
