# Reusable harness library

The harness modules are consumable from another Coil package. Applications own
the capability decision: they compose tool bundles into a registry and either put
that registry on a `ModelRequest` for one direct `run-agent` call or inject it into
a long-lived `HarnessRuntime`.

## Consume the repository

During local development:

```toml
[dependencies]
harness = { path = "../coil-agent-harness" }
```

From Git, pin application and release builds to a commit:

```toml
[dependencies]
harness = {
  git = "https://github.com/example/coil-agent-harness.git",
  sha = "0123456789abcdef0123456789abcdef01234567"
}
```

Coil also accepts `branch` or `tag` in place of `sha`; those selectors resolve on
each invocation and are therefore better suited to development than reproducible
builds. A future physical split can expose several packages from this repository
with Coil's `subdir` dependency field without changing their declared module names.

## Define a tool package

A tool library implements `ToolImplementation` for each callable tool and
`ToolBundle` for the capability it exposes. The bundle owns registration details;
the application only selects bundles:

```coil
(defstruct MyToolBundle [(configuration MyConfiguration)])

(impl ToolBundle MyToolBundle
  (register-tool-bundle! [(self (ptr MyToolBundle))
                          (registry (mut ToolRegistry))
                          (allocator (dyn Allocator))]
                         (-> bool)
                         (tool-register! (mut registry)
                                         (my-tool-definition allocator
                                                             (.configuration self)))))
```

The built-in `harness-tool-bundles` module currently provides:

- `EchoToolBundle`;
- `FilesystemToolBundle`, which includes bounded file operations and text search;
- `BashToolBundle`.

Registering a tool is the execution grant. Duplicate or invalid definitions return
`false` and never replace the existing tool.

## Compose a harness

```coil
(let [allocator (malloc-allocator)
      (mut registry) (tool-registry-new allocator)
      filesystem (primitive/alloc-stack FilesystemToolBundle)
      project (primitive/alloc-stack MyToolBundle)]
  (set! filesystem (filesystem-tool-bundle workspace))
  (set! project (my-tool-bundle configuration))
  (register-tool-bundle! filesystem (mut registry) allocator)
  (register-tool-bundle! project (mut registry) allocator)
  ...)
```

For a direct run, assign the registry to `ModelRequest.tools` and call `run-agent`.
For the durable service runtime, inject it through `HarnessRuntimeConfig`:

```coil
(let [(mut config) (harness-runtime-config-empty)]
  (set! (.registry config) registry-pointer)
  (match (harness-runtime-open-configured process-allocator
                                           service-allocator
                                           journal-path
                                           config)
    (HarnessRuntimeOpened [runtime] ...)
    (HarnessRuntimeOpenFailed [exit-code message] ...)))
```

`harness-runtime-config-empty` grants no built-in tools. Its `workspace` defaults
to `.`. A caller may independently enable `echo-tools`, `filesystem-tools`,
`bash-tools`, and `orchestration-tools`; those are added to the supplied registry.
The registry and its implementations must outlive the runtime.

`harness-runtime-open` remains the application-compatible wrapper. It selects the
historical defaults from `HARNESS_TOOL_GROUPS`, while the configured constructor is
deterministic and does not read tool policy from the environment.

See `examples/composable-harness` for a separate package that imports the harness,
defines its own tool and bundle, composes it with a built-in bundle, and runs as an
ordinary Coil project.

Tools do not have to be statically linked. Trusted shared libraries written in
Coil can describe and execute tools through the versioned C-compatible ABI
documented in [Coil tool plugins](c-tool-plugins.md). The loader adapts those
descriptors into the same `ToolBundle` and `ToolRegistry` interfaces.
