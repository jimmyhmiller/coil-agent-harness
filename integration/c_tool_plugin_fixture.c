#include "harness_tool_plugin.h"

#include <string.h>

#define SLICE_LITERAL(value) {(const uint8_t *)(value), sizeof(value) - 1u}

static int32_t execute_echo(void *tool_context,
                            const HarnessToolInvocation *invocation,
                            HarnessToolResult *result) {
  (void)tool_context;
  if (invocation == NULL || result == NULL ||
      invocation->struct_size != sizeof(*invocation) ||
      result->struct_size != sizeof(*result)) {
    return 1;
  }

  if (invocation->is_cancelled != NULL &&
      invocation->is_cancelled(invocation->host_context)) {
    result->status = HARNESS_TOOL_ERRORED;
    result->output_json = (HarnessToolSlice)SLICE_LITERAL("null");
    result->error = (HarnessToolSlice)SLICE_LITERAL("cancelled");
    return 0;
  }

  result->status = HARNESS_TOOL_SUCCEEDED;
  result->output_json = invocation->arguments_json;
  result->error = (HarnessToolSlice){NULL, 0};
  result->release_context = NULL;
  return 0;
}

static int32_t release_result(void *plugin_context, HarnessToolResult *result) {
  (void)plugin_context;
  (void)result;
  return 0;
}

static int32_t shutdown_plugin(void *plugin_context) {
  (void)plugin_context;
  return 0;
}

static const HarnessToolDescriptor tools[] = {
    {
        .struct_size = sizeof(HarnessToolDescriptor),
        .effect = HARNESS_TOOL_READ_ONLY,
        .strict = 1,
        .idempotent = 1,
        .name = SLICE_LITERAL("c_echo"),
        .description = SLICE_LITERAL("Echo an object through the C tool ABI."),
        .input_schema_json = SLICE_LITERAL(
            "{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\"}},"
            "\"required\":[\"text\"],\"additionalProperties\":false}"),
        .timeout_ms = 1000,
        .tool_context = NULL,
        .execute = execute_echo,
    },
};

static const HarnessToolPlugin plugin = {
    .struct_size = sizeof(HarnessToolPlugin),
    .tool_count = sizeof(tools) / sizeof(tools[0]),
    .tools = tools,
    .plugin_context = NULL,
    .release_result = release_result,
    .shutdown = shutdown_plugin,
};

uint32_t harness_tool_abi_version(void) { return HARNESS_TOOL_ABI_VERSION; }

const HarnessToolPlugin *harness_tool_plugin(void) { return &plugin; }
