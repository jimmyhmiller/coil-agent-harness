# Declared providers

A model server the harness does not know about is described in configuration, not
in code. Point it at a machine — including one reachable only over SSH — and the
harness owns everything that follows: opening the tunnel, keeping it alive,
advertising the provider's capabilities, routing to it, and offering it in the
model picker.

## The file

`$HARNESS_CONFIG_DIR/providers.json`, defaulting to
`~/.coil-agent-harness/providers.json`. It is machine-specific and is not meant to
be committed.

```json
{
  "version": 1,
  "providers": [
    {
      "name": "metaphysics",
      "kind": "openai-chat",
      "default_model": "qwen3.8-27b",
      "label": "Metaphysics · Qwen3.8 27B",
      "summary": "local llama.cpp over ssh",
      "reasoning": { "dialect": "qwen-jinja", "default_effort": "medium" },
      "transport": {
        "ssh": {
          "host": "computer.jimmyhmiller.com",
          "remote_port": 8080
        }
      }
    }
  ]
}
```

That is the whole setup. Nothing has to be started beforehand and no port has to
be chosen.

```sh
./harness run metaphysics qwen3.8-27b "explain this repository"
```

A factory step pins it the same way any provider is pinned:

```json
{ "file": "03-verify.md", "provider": "metaphysics" }
```

Omitting `model` there uses the entry's `default_model`.

## Fields

| field | required | meaning |
|---|---|---|
| `name` | yes | How the provider is named everywhere: CLI, `factory.json`, routing, picker. May not shadow a built-in name. |
| `kind` | no | Wire adapter. Only `openai-chat` (OpenAI-compatible Chat Completions) is supported; anything else is refused. |
| `default_model` | no | Model used when the provider is pinned without one. An entry without it is not offered in the picker. |
| `label` / `summary` | no | Picker display. `label` defaults to the name. |
| `path` | no | Request path. Defaults to `/v1/chat/completions`. |
| `api_key_env` | no | Name of the environment variable holding the key. The key itself never appears in configuration. Omit it for a server that needs no auth. |
| `cost_tier` | no | Relative routing cost, 1 = cheapest. Defaults to 1. |
| `reasoning.dialect` | no | `openai`, `qwen-jinja`, or `none`. Defaults to `openai`. |
| `reasoning.default_effort` | no | Effort used when a run does not ask for one. Defaults to `medium`. |
| `transport` | yes | Exactly one of `ssh` or `url`. |

### `transport.ssh`

| field | required | meaning |
|---|---|---|
| `host` | yes | An ssh destination exactly as `ssh` would take it — `host`, `user@host`, or a `Host` alias from your `ssh_config`. Existing ssh configuration keeps working. |
| `remote_port` | yes | The port on the far side. |
| `remote_host` | no | Resolved on the far side. Defaults to `127.0.0.1`, which is what makes a service bound to remote loopback reachable. |
| `identity_file` | no | Passed as `-i`. |
| `keepalive_seconds` | no | `ServerAliveInterval`. Defaults to 15. |

### `transport.url`

```json
"transport": { "url": "http://127.0.0.1:8080" }
```

A base URL the harness can already reach. `path` is appended to it.

## Reasoning dialects

This is a real incompatibility between servers, not a preference.

- **`openai`** — effort is sent as a top-level `reasoning_effort`. Correct for
  hosted OpenAI-compatible services.
- **`qwen-jinja`** — llama.cpp **ignores** a top-level `reasoning_effort`
  entirely; the value only reaches the model when passed as a chat-template
  kwarg. The harness sends it as `chat_template_kwargs.reasoning_effort` and
  clamps to what the Qwen template accepts (`low`, `medium`, `xhigh`) because
  anything else raises a template exception and returns HTTP 500. Effort `none`
  becomes `chat_template_kwargs.enable_thinking: false`, which is how thinking is
  actually disabled there — the `thinking` object other providers use is ignored.
- **`none`** — effort is never sent, and the provider does not advertise the
  reasoning capability.

## How the tunnel is managed

Owned by `src/infra/ssh_tunnel.coil` and driven on the request path.

1. A free loopback port is obtained from the kernel by binding port 0 and reading
   back the assignment.
2. `ssh -N -L 127.0.0.1:<local>:<remote_host>:<remote_port> <host>` is spawned
   with `BatchMode=yes` (never prompt), `ExitOnForwardFailure=yes` (a forward that
   cannot bind kills the child instead of forwarding nothing),
   `StrictHostKeyChecking=accept-new`, and server keepalives.
3. Readiness is proved by connecting to the local port, not assumed from a
   successful spawn. `ssh` binds a `-L` listener only after authentication
   succeeds, so this also proves the host accepted the key.
4. Each request reuses the live tunnel. A dead one is reconnected; a destination
   that keeps failing is retried under exponential backoff capped at 30s, and
   during the backoff window the *original* diagnostic is returned rather than a
   fresh timeout.
5. Tunnels are released when the provider factory closes, so no ssh child is
   orphaned.

A tunnel that cannot be established is a configuration failure carrying ssh's own
words (`Permission denied (publickey)`, `cannot listen to port`), naming the host.
It is never reported as a refused connection to a local port whose provenance you
would have no way to guess.

The local listener is explicitly bound to `127.0.0.1`, so a forwarded private
service is never republished on a public interface.

## Failure behavior

A missing `providers.json` is not an error — the harness behaves exactly as it
does without one.

Anything else is fatal at startup and names the offending entry: unreadable,
unparseable, unsupported version, missing name, a name that shadows a built-in,
a duplicate, an unsupported kind or dialect, or a transport that is absent,
doubled, or unspawnable. A malformed provider is never silently dropped, because
work the operator meant for one machine would then quietly run somewhere else.

Recorded with every run, in the `ModelRequestStarted` event: the resolved
endpoint including the loopback port, the transport kind, the ssh host and remote
port, and the reasoning dialect. No secret passes through configuration or events.
