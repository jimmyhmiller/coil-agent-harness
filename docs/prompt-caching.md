# Prompt-caching contract

The harness follows OpenAI's prompt-caching requirements:

- Keep the reusable prefix stable: instructions and the ordered tool definitions
  precede changing conversation content.
- Replay direct-subscription conversations append-only. Because that endpoint uses
  `store=false`, every continuation contains all prior response output items and
  their tool results, followed by the new items.
- Send one stable `prompt_cache_key` for a conversation, scoped as
  `provider/model/conversation_id`. If no conversation ID is supplied, the run ID is
  the scope; an empty global key is never used.
- Do not send `prompt_cache_options` to the ChatGPT subscription endpoint. It rejects
  that public-API option. Omitting it retains implicit/default caching while the
  stable cache key supplies routing affinity.
- Parse and publish `cached_input_tokens` and `cache_write_tokens` when the endpoint
  returns them. A zero is telemetry, not proof that a request was malformed: cache
  population and hits are provider decisions and only prefixes of at least 1,024
  tokens are eligible.

The upstream contract is documented in the [OpenAI prompt-caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

## Verification

Run:

```sh
coil test provider_contract
coil test runtime_controller
coil test factory_definition
coil test factory_coordinator
```

The provider contract checks the wire key, rejects the unsupported options field,
proves cumulative `store=false` replay across tool turns, and verifies cache-read and
cache-write usage parsing. The runtime contract checks both explicit conversation
scope and the run-ID fallback.

For live proof, inspect `model.request.started` and `model.request.completed` records
in a factory journal. Every turn in a run must retain the same `prompt_cache_key`;
request bytes should grow as tool history is appended; completed usage records expose
provider-reported cache reads. For example, the successful Snake issue run at
`.factory-runs/coil-snake/1786755482-da25986b/events.jsonl` contains repeated Luna
cache reads of 2,560 input tokens while the worker progresses through tool turns.
