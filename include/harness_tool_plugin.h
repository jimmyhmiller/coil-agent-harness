#ifndef HARNESS_TOOL_PLUGIN_H
#define HARNESS_TOOL_PLUGIN_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HARNESS_TOOL_ABI_VERSION 1u

typedef struct HarnessToolSlice {
  const uint8_t *ptr;
  size_t len;
} HarnessToolSlice;

typedef int32_t (*HarnessToolIsCancelledFn)(void *host_context);

typedef struct HarnessToolInvocation {
  uint32_t struct_size;
  uint32_t reserved;
  HarnessToolSlice call_id;
  HarnessToolSlice arguments_json;
  HarnessToolSlice run_id;
  int64_t run_deadline_monotonic_ms;
  int64_t tool_deadline_monotonic_ms;
  void *host_context;
  HarnessToolIsCancelledFn is_cancelled;
} HarnessToolInvocation;

enum HarnessToolResultStatus {
  HARNESS_TOOL_SUCCEEDED = 0,
  HARNESS_TOOL_ERRORED = 1,
  HARNESS_TOOL_DENIED = 2
};

typedef struct HarnessToolResult {
  uint32_t struct_size;
  int32_t status;
  HarnessToolSlice output_json;
  HarnessToolSlice error;
  void *release_context;
} HarnessToolResult;

typedef int32_t (*HarnessToolExecuteFn)(void *tool_context,
                                        const HarnessToolInvocation *invocation,
                                        HarnessToolResult *result);

enum HarnessToolEffect {
  HARNESS_TOOL_READ_ONLY = 0,
  HARNESS_TOOL_REVERSIBLE = 1,
  HARNESS_TOOL_DESTRUCTIVE = 2
};

typedef struct HarnessToolDescriptor {
  uint32_t struct_size;
  uint32_t effect;
  uint32_t strict;
  uint32_t idempotent;
  HarnessToolSlice name;
  HarnessToolSlice description;
  HarnessToolSlice input_schema_json;
  int64_t timeout_ms;
  void *tool_context;
  HarnessToolExecuteFn execute;
} HarnessToolDescriptor;

typedef int32_t (*HarnessToolReleaseResultFn)(void *plugin_context,
                                              HarnessToolResult *result);
typedef int32_t (*HarnessToolShutdownFn)(void *plugin_context);

typedef struct HarnessToolPlugin {
  uint32_t struct_size;
  uint32_t tool_count;
  const HarnessToolDescriptor *tools;
  void *plugin_context;
  HarnessToolReleaseResultFn release_result;
  HarnessToolShutdownFn shutdown;
} HarnessToolPlugin;

/* Every plugin exports exactly these two symbols. The returned descriptor and
 * every tool descriptor remain valid until shutdown. */
uint32_t harness_tool_abi_version(void);
const HarnessToolPlugin *harness_tool_plugin(void);

#ifdef __cplusplus
}
#endif

#endif
