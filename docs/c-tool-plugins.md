# Coil tool plugins over a C ABI

Trusted native libraries can add tools without being compiled into the harness.
Both the host adapter and plugins are written in Coil. "C ABI" names the stable
calling convention and data layout at the shared-library boundary; it does not
require C source, a C header, or a generated C shim. The contract is defined in
[src/runtime/tool_plugin_abi.coil](../src/runtime/tool_plugin_abi.coil). Only
fixed-width integers, pointers, C-callable function pointers, and pointer-length
byte slices cross that boundary.

This is deliberately a **tool ABI**, not a general extension ABI. A loaded library
runs native code inside the harness process and has the process's full authority.
Untrusted or independently supervised extensions still belong on the agent bus.

## Export and describe tools

Every library exports two symbols using Coil's `export-c` form:

```coil
(export-c
  [my-abi-version :as "harness_tool_abi_version"]
  [my-plugin :as "harness_tool_plugin"])
```

`harness_tool_plugin` returns a process-lifetime descriptor containing one or more
`CToolDescriptor` values. Each tool declares:

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

The Coil execution callback receives normalized JSON arguments along with the call
ID, run ID, monotonic run/tool deadlines, and a host cancellation callback:

```coil
(defn execute [(tool-context (ptr i8))
               (invocation (ptr CToolInvocation))
               (result (ptr CToolResult))] (-> i32)
  ...)
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

`DynamicCToolPlugin` implements `ToolBundle`, so dynamically loaded tools compose
exactly like statically linked Coil bundles. The registry can then be assigned to
`ModelRequest.tools` or `HarnessRuntimeConfig.registry`.

Call `c-tool-plugin-close!` only after all runs and tool worker threads using that
registry have stopped. It calls the optional plugin `shutdown` hook and then
`dlclose`. Closing earlier would unload executable callback addresses still held by
the registry.

## Build and test

A plugin is an ordinary Coil module built as a shared library:

```sh
coil build my_tools.coil --shared -o libmy_tools.dylib
```

Use a `.so` output name on Linux. A complete Coil implementation lives in
[integration/coil_tool_plugin_fixture.coil](../integration/coil_tool_plugin_fixture.coil).
`scripts/test_c_tool_plugin.sh` builds it with Coil, loads it, registers
`coil_echo`, executes it through the normal harness tool interface, and verifies
the returned JSON. The test does not compile or generate C.
