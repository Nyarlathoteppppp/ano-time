# Local LiteLLM free-pool integration

## Scope

AnoTime Smart Hybrid Final uses the private LiteLLM Gateway running on this Mac
as its only fallback after the selected direct primary. AnoTime treats
`free-pool` as an opaque external alias: its internal members and ordering are
owned by the Gateway and must not be changed from this project. AnoTime does
not configure or directly call a Cloudflare GLM provider.

Connection contract:

- Base URL: `http://localhost:4000/v1`
- Public model alias: `free-pool`
- Client credential: `LITELLM_CLIENT_KEY`
- Default credential source: `~/litellm-gateway/.env`

`translation_workflows.providers.load_local_gateway_client_key()` reads only
the named client variable. An existing process environment variable takes
precedence. The value is held in memory by the `Translator` instance and must
never be printed, persisted to `config.ini`, copied to Keychain, committed, or
included in diagnostics.

## Routing position

The provider name is `Local LiteLLM Free Pool` with priority 20. It is added
only when the client credential is available.

```text
selected Smart Hybrid primary
  → Local LiteLLM free-pool
```

The default selected primary is the direct fast pool:

- Fast mode: direct Groq and Cerebras are priorities 1 and 2.
- Gemini mode remains available as an alternate primary at priority 1.
- Local LiteLLM `free-pool` is priority 20.
- There is no direct GLM provider in Smart Hybrid Final. The external Gateway
  may independently include GLM inside `free-pool`.

This is intentionally a Final-only fallback. Progressive Preview and optional
Bridge keep their existing isolated clients and scheduling state. Single Model
and Apple Only are unchanged. A Gateway failure enters the existing provider
cooldown/failover path and cannot remove or delay the already-visible Apple
draft beyond the existing remote deadline.

No startup health gate was added. The concrete failure being handled is a
request-time unavailable local Gateway; `HybridTranslator` already catches
that provider error, applies cooldown, and selects the next eligible provider.
A second preflight mechanism would duplicate existing behavior and couple App
startup to Docker availability.

## Verification

Automated contracts cover:

- reading only `LITELLM_CLIENT_KEY` from an isolated `.env`;
- omitting the provider when no client credential is available;
- fixed localhost base URL and `free-pool` alias;
- priority after the selected primary;
- primary failure → local pool success;
- default selection is Groq → Cerebras and AnoTime has no direct GLM route;
- complete regression and release secret audit.

Non-spending live checks are Gateway liveliness and authenticated `/v1/models`
visibility for `free-pool`. A real completion may consume provider quota and is
not part of the default automated suite.

Gateway administration is outside this repository's maintenance scope. This
project may perform read-only availability diagnosis when requested, but must
not edit Gateway routing, restart its containers, or manage its credentials.
