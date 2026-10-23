# Plan — Phase 53: more language model providers

Phase file: `docs/roadmap/phases/53-llm-providers.md`. Branch `feature/53-llm-providers`.

## Tasks

1. **Keys and provider-neutral plumbing.** `config.py` / `settings_fields.py` / `.env.example`:
   `OPENAI_LLM_URL` (url, default `http://localhost:1234/v1`), `OPENAI_LLM_KEY` (secret),
   `OPENAI_LLM_MODEL` (default empty: the server's only model is not guessed), `ANTHROPIC_API_KEY`
   (secret), `ANTHROPIC_MODEL` (default `claude-opus-5-5`). `net.py`: `llm_url(settings)`,
   `llm_model(settings)`; `remote_llm_host` covers the three providers (Anthropic always remote).
   `gpu_usage.llm` also for an `openai_compatible` server on loopback. `/health.llm.model` from
   `llm_model`.
2. **`llm/openai_compatible.py`** (`OpenAICompatibleLanguageModel`): `POST /chat/completions`
   (`stream: false`; JSON schema as `response_format: {type: "json_schema", json_schema: {name,
   schema}}`), SSE stream (`data: {choices[0].delta.content}` … `data: [DONE]`), Bearer key when
   set, reachability probe `GET /models` once (connection failure → `LlmUnreachableError`),
   `is_available` = the model is listed, `release` no-op, `cancel` closes the client. A shared
   `tests/llm/contract.py` suite used by Ollama and this provider.
3. **`llm/anthropic.py`** (`AnthropicLanguageModel`) on the official `anthropic` SDK (new
   dependency): `client.beta.messages.stream(model, max_tokens=64000, system, messages,
   output_config={effort: "medium", format?: json_schema}, betas=["server-side-fallback-2026-07-01"],
   fallbacks="default")`; `generate` reads `get_final_message()`, `stream` yields `text_stream`;
   `stop_reason == "refusal"` → `LanguageModelError`; `APIConnectionError` → `LlmUnreachableError`;
   `is_available` = `models.retrieve(model)`. The SDK client comes from a factory (tests: a fake).
   Registered as `LANGUAGE_MODELS["anthropic"]`.
4. **Config tests**: `CheckTarget.OPENAI_LLM` (`GET {url}/models`, model listed) and
   `CheckTarget.ANTHROPIC` (key set → `models.retrieve` through the provider); locale messages.
5. **UI**: labels / help for the five keys (en, pt-BR, es), `TestAnchors` for `OPENAI_LLM_URL`
   and `ANTHROPIC_API_KEY`, `ConnectionTargets`, the sidebar's "not reachable (start Ollama)" made
   provider-neutral, the remote note mentions the provider.
6. **Docs and packaging**: `docs/language-models.md` (from `remote-ollama.md`, which links there),
   architecture §9, api-contract, `engine.spec` hidden import `anthropic`.
7. **Checks**: full suites; manual: Ollama's own OpenAI-compatible endpoint
   (`http://localhost:11434/v1`, `qwen2.5:7b`) as `openai_compatible` for minutes of a stored
   meeting, the Config Test; Anthropic without a key (`not_configured`) — a real Claude call needs
   the user's key (pending manual test).
