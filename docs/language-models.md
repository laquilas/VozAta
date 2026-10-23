# Language models

The minutes, the action items, "Ask the meeting" and the voice commands are written by a
language model. Choose it on **Config → Minutes** with **Minutes model provider**
(`LLM_PROVIDER`), then press **Test** next to its address or key.

| Provider | Runs on | The transcript goes to | Set up |
|----------|---------|------------------------|--------|
| `ollama` (default) | this PC, or another PC of your network | that PC | [Using Ollama on another PC](remote-ollama.md) for a remote one |
| `openai_compatible` | LM Studio, vLLM, the llama.cpp server on this or another PC; or OpenAI | the server's address | below |
| `anthropic` | Anthropic's servers (Claude) | `api.anthropic.com` | below |

> **Privacy.** Any address that is not this PC means the **text of your meetings** leaves it. The
> Config page says so next to the address or key. With Anthropic or OpenAI the provider's terms and
> billing apply.

## An OpenAI-compatible server

Many local servers speak the OpenAI chat API:

| Server | Address (`OPENAI_LLM_URL`) |
|--------|----------------------------|
| LM Studio (Developer tab → Start server) | `http://localhost:1234/v1` |
| llama.cpp `llama-server` | `http://localhost:8080/v1` |
| vLLM | `http://localhost:8000/v1` |
| Ollama itself | `http://localhost:11434/v1` |
| OpenAI | `https://api.openai.com/v1` (with `OPENAI_LLM_KEY`) |

1. Set **Minutes model provider** to `openai_compatible`.
2. Fill in the address; the key only when the server asks for one.
3. **OpenAI-compatible model**: the model name the server serves. Left empty, VozAta uses the
   first model the server lists, which in LM Studio is the model you loaded.
4. **Save**, then **Test**: it lists the server's models and checks yours is there.

A server on this PC uses its GPU like Ollama does: VozAta frees the speech model before the
minutes and lets a live recording take the GPU first. A server on another PC does not.
Action items ask for JSON through `response_format` (JSON schema); a server that ignores it
still works when the model answers with valid JSON, and VozAta retries once otherwise.

## Claude (Anthropic)

1. Create a key on [console.anthropic.com](https://console.anthropic.com).
2. Set **Minutes model provider** to `anthropic`, paste the key in **Anthropic API key**.
3. **Claude model** is `claude-opus-5-5` by default; `claude-sonnet-5-5` is cheaper.
4. **Save**, then **Test**: it looks the model up with your key.

VozAta talks to Claude through Anthropic's official SDK: every request is streamed, runs at effort
`medium`, and opts into Anthropic's server-side refusal fallbacks. Nothing runs on your GPU.

## When it does not work

| Symptom | What to do |
|---------|------------|
| Sidebar: "Minutes: … not reachable (check the language model in Config)" | Press **Test** on Config → Minutes: it says whether the server answered and whether the model is there. |
| Test: "it does not serve the model" | Load the model in LM Studio / start the server with it, or fix **OpenAI-compatible model**. |
| Test: "rejected the credentials" | The key is wrong or revoked. |
| Minutes fail with "Claude declined the request" | Claude refused this transcript; another model (`claude-sonnet-5-5`, or a local one) can write it. |
