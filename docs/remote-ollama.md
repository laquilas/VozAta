# Using Ollama on another PC

The minutes, the action items and "Ask the meeting" are written by an Ollama model. By default that
model runs on the same computer as VozAta. If you have a stronger PC on the same local network, it
can run Ollama instead, and this computer's GPU is left to the speech recognition.

Only the **language model** moves with this guide. Speech recognition can move to a GPU PC too, with
a VozAta worker: see [Using a VozAta worker on another PC](remote-worker.md). Recording always runs
on the computer where VozAta is installed (see
[The engine cannot run on another PC](#the-engine-cannot-run-on-another-pc)).

> **Privacy.** With a remote Ollama, the transcript text of your meetings is sent to the other PC.
> Use it only on a network you trust.

## On the other PC (the Ollama server)

These steps are for Windows. Run them in PowerShell.

1. Install [Ollama](https://ollama.com).
2. Make Ollama listen on the network instead of only on the PC itself. Set a user environment
   variable, then quit Ollama from the tray icon and start it again:

   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
   ```

3. Pull the model the minutes use (the default is `qwen2.5:7b`; any model that fits the server's GPU
   works):

   ```powershell
   ollama pull qwen2.5:7b
   ```

4. Allow inbound connections on the private network profile (run PowerShell as administrator):

   ```powershell
   New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -Protocol TCP -LocalPort 11434 -Profile Private -Action Allow
   ```

5. Give the PC a fixed address: a DHCP reservation in your router, or a static IP. Otherwise the
   address changes and VozAta stops finding it.
6. Find the address (`ipconfig`, the IPv4 line of your network adapter), for example `192.168.1.50`.

Ollama has **no authentication**. Anyone who can reach port 11434 can use it, so never expose it to
the internet (no router port forwarding) and keep the firewall rule on the **Private** profile only.

## On the computer with VozAta

1. Check that the server answers. In PowerShell:

   ```powershell
   curl http://192.168.1.50:11434/api/tags
   ```

   It prints the models installed on the other PC. If it does not answer, the firewall rule, the
   address or the `OLLAMA_HOST` variable (step 2 above) is wrong.
2. Open **Config → Minutes** and set **Ollama URL** to `http://192.168.1.50:11434`.
3. Set **Ollama model** to a name from that `curl` output, exactly as written (for example
   `qwen2.5:7b`). The model must be pulled on the **server**, not on this computer.
4. Press **Save**, then the **Test** button next to the URL. A success message means the minutes
   will be written by the other PC.

The same two settings live in `%APPDATA%\VozAta\.env` as `OLLAMA_URL` and `OLLAMA_MODEL`.

`OLLAMA_KEEP_ALIVE` (default `0`) tells the server how long to keep the model in memory after a job.
`0` frees the server's GPU right away; use `5m` on a server dedicated to VozAta to skip the reload
between meetings.

## When it does not work

| Symptom | What to do |
|---------|------------|
| An error with `WinError 10061` ("connection refused") when writing the minutes or extracting action items | Nothing is listening at the URL: Ollama is stopped on the server, or the address is wrong. Start Ollama there and run the `curl` check again. |
| `curl` times out | The firewall blocks port 11434, the PCs are on different networks, or the server's network profile is *Public* instead of *Private*. |
| `curl` answers on the server itself but not from here | `OLLAMA_HOST` is not `0.0.0.0:11434`, or Ollama was not restarted after changing it. |
| The test passes but the minutes say the model is not installed | Run `ollama pull <model>` **on the server** for the name in **Ollama model**. |
| It worked yesterday and now fails | The server's address changed; use a fixed address (step 5). |

## The engine cannot run on another PC

The engine is the `vozata-engine` program the app starts by itself. It is not possible to run it on
another PC and point the app at it, and the app does not offer a setting for that:

- **It records the wrong audio.** The engine captures the microphone and the system sound (WASAPI)
  of the computer it runs on, and stores the recordings there. A remote engine would record the
  other PC, not the meeting you are in.
- **It has no authentication.** For that reason `serve` refuses to listen on every interface
  (`API_HOST` of `0.0.0.0`, `::` or empty) and the API contract forbids it. Anyone on the network
  could otherwise read your meetings and start recordings.

What can be moved to another machine is the heavy work that does not need your audio devices:

| Work | Where it can run | How |
|------|------------------|-----|
| Minutes, action items, Ask | another PC | this guide |
| Speech recognition (Whisper) | a VozAta worker on a GPU PC of your network | [Using a VozAta worker on another PC](remote-worker.md) (`STT_PROVIDER=vozata_worker`); this PC takes over when the worker does not answer |
| Speech recognition (Whisper) | an OpenAI-compatible speech server | **Config → Transcription**: set the speech provider to the OpenAI-compatible one and its URL (`STT_PROVIDER`, `OPENAI_STT_URL`). It sends the **audio** to that server |
| Speaker detection | this computer only | – |
