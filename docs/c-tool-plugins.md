# C tool plugins

Trusted native libraries can add tools without being compiled into the harness.
The public ABI is [include/harness_tool_plugin.h](../include/harness_tool_plugin.h).
It contains no Coil data layouts: only fixed-width integers, pointers, function
pointers, and pointer-length byte slices cross the shared-library boundary.

This is deliberately a **tool ABI**, not a general extension ABI. A loaded library
runs native code inside the harness process and has the process's full authority.
Untrusted or independently supervised extensions still belong on the agent bus.

## Export and describe tools

Every library exports two C symbols:

```c
uint32_t harness_tool_abi_version(void);
const HarnessToolPlugin *harness_tool_plugin(void);
```

`harness_tool_plugin` returns a process-lifetime descriptor containing one or more
`HarnessToolDescriptor` values. Each tool declares:

- name and description;
- JSON Schema input document;
- read-only, reversible, or destructive effect;
- strict-schema and idempotence flags;
- timeout in milliseconds;
- opaque tool context and an execution callback.

The harness validates every descriptor and schema before exposing any tool. Tool
names still pass through the ordinary `ToolRegistry`, so invalid names and duplicate
authority are rejected. A plugin bundle checks all names before registration and
does not partially install on a collision.

## Execution

The execution callback receives normalized JSON arguments along with the call ID,
run ID, monotonic run/tool deadlines, and a host cancellation callback:

```c
int32_t execute(void *tool_context,
                const HarnessToolInvocation *invocation,
                HarnessToolResult *result);
```

Returning zero means the callback filled `result`; nonzero means the callback itself
failed. A successful result must contain valid JSON. Error and denied results may
omit output JSON. The harness copies/parses all returned bytes before calling the
plugin's required `release_result` callback, so plugins may use any allocator.

Callbacks for different calls may run concurrently. A plugin must either be
thread-safe or synchronize its own mutable `plugin_context` and `tool_context`.

## Load and compose

```coil
(match (c-tool-plugin-load allocator library-path)
  (DynamicCToolPluginLoadFailed [message] ...)
  (DynamicCToolPluginLoaded [loaded]
    (let [plugin (box! allocator DynamicCToolPlugin loaded)]
      (register-tool-bundle! plugin registry allocator)
      ...)))
```

`DynamicCToolPlugin` implements `ToolBundle`, so native tools compose exactly like
Coil-native bundles. The registry can then be assigned to `ModelRequest.tools` or
`HarnessRuntimeConfig.registry`.

Call `c-tool-plugin-close!` only after all runs and tool worker threads using that
registry have stopped. It calls the optional plugin `shutdown` hook and then
`dlclose`. Closing earlier would unload executable callback addresses still held by
the registry.

## Build and test

On macOS:

```sh
cc -dynamiclib -fPIC -std=c11 \
  -I /path/to/coil-agent-harness/include \
  my_tools.c -o libmy_tools.dylib
```

On Linux, use `-shared` and produce a `.so`. A complete implementation lives in
`integration/c_tool_plugin_fixture.c`; `scripts/test_c_tool_plugin.sh` builds it,
loads it, registers `c_echo`, executes it through the normal harness tool interface,
and verifies the returned JSON.
