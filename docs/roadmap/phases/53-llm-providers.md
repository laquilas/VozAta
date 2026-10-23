# Phase 53 — More language model providers

## Goal

Minutes, action items, partial minutes and Ask can use a language model other than Ollama:
an **OpenAI-compatible** chat server (LM Studio, vLLM, llama.cpp server, OpenAI itself) or
**Anthropic** (Claude). Chosen on the Config page; Ollama stays the default. From the backlog
("Additional LLM providers behind `LanguageModel`").

## Depends on

43, 38

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- `ports.py` (`LanguageModel`, `LanguageModelError`, `LlmUnreachableError`), `llm/ollama.py`,
  `bootstrap.py` (`LANGUAGE_MODELS`, the `llm` health, `/settings/test`), `net.py`
  (`remote_llm_host`), `processing/gpu_gate.py` (`gpu_usage.llm`), `settings_fields.py`,
  `connection_checks.py`
- UI: `SettingsViewModel.cs` (`TestAnchors`), `ConnectionTargets`, `Strings*.resx`
  (`Setting_*`, `SettingHelp_*`), the sidebar LLM status
- `docs/remote-ollama.md`, [phase 43](43-remote-ollama.md)

## Scope

| Provider (`LLM_PROVIDER`) | Keys | Calls |
|---------------------------|------|-------|
| `ollama` (default) | unchanged | unchanged |
| `openai_compatible` | `OPENAI_LLM_URL` (default `http://localhost:1234/v1`, LM Studio), `OPENAI_LLM_KEY` (secret, optional), `OPENAI_LLM_MODEL` | `POST {url}/chat/completions` (`stream` for Ask), JSON schema through `response_format: {type: "json_schema"}`; availability `GET {url}/models` lists the model |
| `anthropic` | `ANTHROPIC_API_KEY` (secret), `ANTHROPIC_MODEL` (default `claude-opus-5-5`) | the official `anthropic` SDK: `messages.stream` (always streamed: long minutes), structured output through `output_config.format`, effort `medium`, refusal fallbacks on (`fallbacks: "default"`); availability `models.retrieve` |

- Both implement `LanguageModel`; `release()` does nothing (no local VRAM), `cancel()` closes the
  request in flight. A connection failure is `LlmUnreachableError` (host), a refusal or an HTTP
  error `LanguageModelError`.
- **Privacy**: the transcript leaves this PC for any non-loopback URL and always for Anthropic.
  `/health.llm.remote` / `host` say so (phase 43's note on the Config page covers it, its text
  made provider-neutral).
- **GPU**: an `openai_compatible` server on loopback (LM Studio on this PC) counts as a local
  GPU user like Ollama (phase 40 gate); a remote one and Anthropic do not.
- **Config page**: the keys in the `minutes` group, labels and help in en / pt-BR / es, a Test
  next to `OPENAI_LLM_URL` and `ANTHROPIC_API_KEY` (`/settings/test/openai_llm`,
  `/settings/test/anthropic`); `LLM_PROVIDER` options list the three.
- Docs: `docs/remote-ollama.md` becomes "Language models" (Ollama here or elsewhere, an
  OpenAI-compatible server, Anthropic), architecture §9 keys, api-contract (`/settings/test`
  targets, `/health.llm`).

## Acceptance criteria

- [ ] With `LLM_PROVIDER=openai_compatible` and LM Studio / llama.cpp serving a model, minutes,
      action items and Ask work; the Config Test says ok.
- [ ] With `LLM_PROVIDER=anthropic` and a key, the same; without a key the Test says what is missing.
- [ ] The sidebar / Config show that the transcript leaves the PC for a remote provider.

## Tests

A shared `LanguageModel` contract suite run against Ollama, OpenAI-compatible
(`httpx.MockTransport`) and Anthropic (a fake SDK client); errors (unreachable, HTTP error,
refusal, malformed JSON, cancel); registry, health `remote`, GPU usage, settings fields and
tests; UI resource parity and test anchors.

## Out of scope

Tool use, prompt caching tuning, per-task providers (minutes on one, Ask on another), Azure / Bedrock.

## Kickoff prompt

> Start phase 53 (`docs/roadmap/phases/53-llm-providers.md`): read its *Read first* files, write
> `plans/53-llm-providers.md`, then implement it task by task.

## Progress

- **Branch:** `feature/53-llm-providers`
- **Status:** in progress
- **Updated:** 2026-10-23
- **Next step:** task 4: Config tests `openai_llm` (GET {url}/models, model listed) and `anthropic`
  (key set, `models.retrieve` through the provider) in `connection_checks.py`, with their locale
  messages.

### Steps

- [x] Implementation plan (`plans/53-llm-providers.md`)
- [x] Keys, provider-neutral host / model / GPU rules, `/health.llm`
- [x] OpenAI-compatible provider and the shared contract suite
- [x] Anthropic provider (official SDK)
- [ ] Config tests for both providers
- [ ] UI: labels, tests, provider-neutral texts
- [ ] Docs and packaging
- [ ] Full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- Anthropic goes through the official `anthropic` SDK (the project's Claude API rule), not raw
  HTTP; defaults from its current guidance: `claude-opus-5-5`, effort `medium`, server-side
  refusal fallbacks on, always streamed.
- `load_settings` only reads keys declared in `settings_fields.py`, so the five keys live there
  (group `minutes`). `/health.llm.model` now names the model of the chosen provider
  (`net.llm_model`).
- Without `OPENAI_LLM_MODEL` the OpenAI-compatible provider uses the first model `/models` lists (LM
  Studio serves the loaded one).
- The Anthropic provider closes every object of the JSON schema (`additionalProperties: false`, on a
  copy) because structured outputs need closed objects; the action-item schema has none. A read
  timeout is a plain failure, a connection failure `LlmUnreachableError` (host `api.anthropic.com`).
  New dependency `anthropic>=2.2,<3` (built on `httpx2`).
