# Using a VozAta worker on another PC

Speech recognition (Whisper) is the heaviest work VozAta does during a meeting. If you have a PC on
the same local network with an NVIDIA GPU, it can run **VozAta Worker**, which transcribes for this
computer. This computer then loads no Whisper model and its GPU and memory stay free.

Recording always stays on this computer: the microphone and the system sound are captured here,
and the recordings are stored here. Only the audio chunks to transcribe travel to the worker.

> **Privacy.** With a worker, the **audio** of your meetings is sent to the other PC, in clear
> (plain HTTP) on your local network. Use it only on a network you trust.

If the worker does not answer, VozAta first looks for it on the network (its address may have
changed); if it is not there, VozAta transcribes on this computer and a notification says so
("The VozAta worker at … did not answer: speech recognition runs on this PC."). A recording never
stops because of the worker.

The language model (minutes, action items, Ask) can move to another PC too, with Ollama: see
[Using Ollama on another PC](remote-ollama.md). The same GPU PC can run both.

## On the GPU PC

1. Install VozAta on the GPU PC (the same installer).
2. Open **VozAta Worker** from the Start menu. It starts the worker and shows:
   - its state (the first start downloads the speech model, `WHISPER_MODEL`, which takes a while);
   - the **pairing code** (6 digits, a new one every 5 minutes);
   - this PC's addresses, its GPU, the loaded model and the token.
3. Press **Allow on the network** once. It asks for administrator rights and adds two firewall
   rules for the **Private** network profile only: TCP 8766 (the worker) and UDP 8767 (so other
   PCs can find it).
4. Turn on **Start with Windows** if the worker should always be there; it then starts minimized
   to the tray.

Closing the window keeps the worker running in the tray; **Exit** in the tray menu stops it.

The worker keeps its own settings in `%APPDATA%\VozAta\worker\.env` (made on the first start):
`WORKER_TOKEN` and `WORKER_ID` (never share the token), `WORKER_NAME` (the name other PCs see; empty
is the PC name), `WORKER_HOST` (default `0.0.0.0`, every network of that PC), `WORKER_PORT`
(8766), `WORKER_DISCOVERY_PORT` (8767) and the Whisper keys (`WHISPER_MODEL`, `WHISPER_DEVICE`,
`WHISPER_COMPUTE_TYPE`, `WHISPER_CPU_MODEL`). Its output goes to `worker.log` in the same folder.

Never expose the worker to the internet (no router port forwarding).

## On this computer

1. Open **Config → Worker (another PC)** and press **Find workers**. Every VozAta Worker on this
   PC's networks answers within a couple of seconds, with its address, version and GPU.
2. Type the code shown in VozAta Worker on the GPU PC next to it and press **Pair**. The address,
   the token and the worker's id are saved.
3. Press **Test** next to the address. A success message names the worker's version and GPU.
4. Under **Use the worker for**, tick what the worker should do: **Speech recognition**,
   **Speaker identification**, **Live translation**. Press **Save**; speech asks for an engine
   restart, the others apply from the next recording.

Five wrong codes lock pairing on the worker for a minute. The settings live in
`%APPDATA%\VozAta\.env` as `WORKER_URL`, `WORKER_TOKEN`, `WORKER_ID` and the providers the
switches set (`STT_PROVIDER`, `DIARIZATION_PROVIDER`, `TRANSLATION_PROVIDER` = `vozata_worker`).
The sidebar shows **Worker: <host>** under the engine status while the worker does the work, and
**This PC (worker off)** when a chosen task fell back to this PC.

### Without discovery

When the PCs are on different subnets, or the router blocks broadcasts, set the address by hand:
**Worker address** `http://<GPU PC address>:8766` and **Worker token** (shown in VozAta Worker),
then **Test**. A worker set this way is not found again when its address changes: give the GPU PC
a fixed address (a DHCP reservation in your router).

### Command line

The worker is `vozata-engine.exe worker` in the `engine` folder of VozAta (`python -m vozata
worker` from the sources); `vozata-engine.exe worker --check` prints the version and the address
without starting anything. The first start prints the token once.

## Speaker identification on the worker

The worker can also identify the speakers (pyannote): after a meeting, and live when live speaker
labels are on.

1. On the GPU PC, put your Hugging Face token in `%APPDATA%\VozAta\worker\.env` as
   `HF_TOKEN=...` (the same token and model terms as on this PC) and restart VozAta Worker.
2. On this computer, tick **Speaker identification** under **Config → Worker → Use the worker
   for**. This computer then needs no Hugging Face token of its own, unless the worker is
   off: then its own pyannote runs, which needs one.

When the worker does not answer, a notification says "speaker identification runs on this PC".

## Live translation on the worker

Tick **Live translation** under **Use the worker for**. The worker translates each line with
opus-mt (on its CPU, about 300 MB of memory); it needs the `translation` extra there
(`pip install -e ".[translation]"` when it runs from the sources). A worker without it does not
offer translation, and this PC translates instead.

## VRAM on the GPU PC

The worker keeps Whisper loaded between meetings. When the same PC also runs Ollama for the
minutes, both share its GPU:

| Model | VRAM, about |
|-------|-------------|
| Whisper `large-v3-turbo` (`int8_float16`) | 1.5–2 GB |
| pyannote (diarization, only while it runs; the embedder stays loaded) | about 1 GB |
| opus-mt (translation) | none: it runs on the CPU (about 300 MB of RAM) |
| Ollama `qwen2.5:7b` (Q4) | 5–6 GB |

An 8 GB GPU fits both; with less, use a smaller Ollama model or `OLLAMA_KEEP_ALIVE=0` (the default)
so Ollama frees its memory after each job.

## When it does not work

| Symptom | What to do |
|---------|------------|
| **Find workers** lists nothing | VozAta Worker is not open, **Allow on the network** was not done, the GPU PC's network profile is *Public*, or the PCs are on different subnets (set the address by hand). |
| **Pair** says the code was refused | Type the code shown **now** in VozAta Worker (it changes every 5 minutes). After 5 wrong codes, wait a minute. |
| A notification says the worker did not answer, and transcription runs on this PC | The worker is not running or cannot be reached. Open VozAta Worker on the GPU PC and press **Test** here. |
| **Test** says the token was refused | Pair again, or copy the token shown in VozAta Worker into **Worker token**. |
| VozAta Worker says the worker stopped | Open `worker.log` (the path is in the message): a model download failed, or the port is used by another program (`WORKER_PORT`). |
| Transcription is slow on the worker | The GPU PC has no working CUDA and runs on its CPU (`WHISPER_CPU_MODEL`); VozAta Worker and the **Test** message say so. |
