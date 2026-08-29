---
project: harness
---

# tests/openai_chat_test.coil calls openai-chat-timeout-ms with two arguments

Three tests in tests/openai_chat_test.coil call (openai-chat-timeout-ms context request), but the function in src/providers/openai_chat.coil takes one argument. The whole repository's test sweep fails to typecheck because of it, so no other test can run.

Decide which side is right — the tests' two-argument call or the function's one-argument signature — and make them agree. Then run the full suite and confirm it is green.
