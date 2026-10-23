# Using a VozAta worker on another PC

Speech recognition (Whisper) is the heaviest work VozAta does during a meeting. If you have a PC on
the same local network with an NVIDIA GPU, it can run a **VozAta worker** that transcribes for this
computer. This computer then loads no Whisper model and its GPU and memory stay free.

Recording always stays on this computer: the microphone and the system sound are captured here,
and the recordings are stored here. Only the audio chunks to transcribe travel to the worker.

> **Privacy.** With a worker, the **audio** of your meetings is sent to the other PC, in clear
> (plain HTTP) on your local network. Use it only on a network you trust.

If the worker does not answer, VozAta transcribes on this computer instead and a notification says
so ("The VozAta worker at … did not answer: speech recognition runs on this PC."). A recording never
stops because of the worker.

The language model (minutes, action items, Ask) can move to another PC too, with Ollama: see
[Using Ollama on another PC](remote-ollama.md). The same GPU PC can run both.

## On the GPU PC (the worker)

These steps are for Windows. Run them in PowerShell.

1. Copy or install VozAta on the GPU PC. The worker is the same `vozata-engine.exe` the app uses:
   after installing, it is in the `engine` folder next to `VozAta.Desktop.exe`.
2. Start the worker once from that folder:

   ```powershell
   .\vozata-engine.exe worker
   ```

   The first time, it creates a **token**, saves it in the `.env` of that folder as `WORKER_TOKEN`
   and prints it once:

   ```text
   New worker token, saved in .env: 8yQ…Zk. Enter it in VozAta on the other PC (Config → Worker).
   VozAta worker listening on http://0.0.0.0:8766 (Ctrl+C to stop).
   ```

   Every request must carry that token; without it the worker answers `401`. The Whisper model
   (`WHISPER_MODEL`, downloaded the first time) loads on the first request and stays loaded.
3. Allow inbound connections on the private network profile (PowerShell as administrator):

   ```powershell
   New-NetFirewallRule -DisplayName "VozAta worker" -Direction Inbound -Protocol TCP -LocalPort 8766 -Profile Private -Action Allow
   ```

4. Give the PC a fixed address (a DHCP reservation in your router, or a static IP) and note it
   (`ipconfig`, the IPv4 line), for example `192.168.1.50`.
5. To start the worker with Windows, create a scheduled task "At log on" that runs
   `vozata-engine.exe worker` in that folder, or put a shortcut to a small `.cmd` in
   `shell:startup`.

Settings of the worker PC (its own `.env`): `WORKER_HOST` (default `0.0.0.0`, every network of
that PC; a loopback address such as `127.0.0.1` needs no token), `WORKER_PORT` (default `8766`),
`WORKER_TOKEN`, and the Whisper keys `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`,
`WHISPER_CPU_MODEL`. `vozata-engine.exe worker --check` prints the version and the address
without starting anything.

Never expose the worker to the internet (no router port forwarding) and keep the firewall rule on
the **Private** profile only.

## On this computer

1. Open **Config → Worker (another PC)**:
   - **Worker address**: `http://192.168.1.50:8766`
   - **Worker token**: the token printed on the GPU PC
2. Press **Save**, then the **Test** button next to the address. A success message names the
   worker's version and GPU.
3. Open **Config → Transcription** and set the speech provider (`STT_PROVIDER`) to
   `vozata_worker`. Restart the engine when asked.

The settings live in `%APPDATA%\VozAta\.env` as `WORKER_URL`, `WORKER_TOKEN` and `STT_PROVIDER`.
The **Status** of the app (`GET /health`) shows the worker host as the speech device.

## VRAM on the GPU PC

The worker keeps Whisper loaded between meetings. When the same PC also runs Ollama for the
minutes, both share its GPU:

| Model | VRAM, about |
|-------|-------------|
| Whisper `large-v3-turbo` (`int8_float16`) | 1.5–2 GB |
| Ollama `qwen2.5:7b` (Q4) | 5–6 GB |

An 8 GB GPU fits both; with less, use a smaller Ollama model or `OLLAMA_KEEP_ALIVE=0` (the default)
so Ollama frees its memory after each job.

## When it does not work

| Symptom | What to do |
|---------|------------|
| A notification says the worker did not answer, and transcription runs on this PC | The worker is not running, the address is wrong, or the firewall blocks port 8766. Start the worker and press **Test**. |
| **Test** says the token was refused | Copy `WORKER_TOKEN` from the `.env` of the worker PC into **Worker token**. |
| **Test** times out | The PCs are on different networks, or the worker PC's network profile is *Public* instead of *Private*. |
| It worked yesterday and now falls back | The worker PC's address changed; give it a fixed address (step 4). |
| Transcription is slow on the worker | The worker PC has no working CUDA and runs on its CPU (`WHISPER_CPU_MODEL`); the **Test** message says `CPU`. |
