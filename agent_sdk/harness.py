"""Bridge between the coil harness tool registry and the Claude Agent SDK.

The Agent SDK owns the agent loop; the harness owns every tool.

Three options give us full control over what the model can reach:

  * ``tools=[]`` removes every built-in Claude Code tool, so the model's entire
    capability surface is whatever the harness registry exposes.
  * ``setting_sources=[]`` stops ``~/.claude`` and project settings from being
    read, so a run is reproducible from this file alone.
  * ``system_prompt`` is a plain string we own rather than the ``claude_code``
    preset, so none of Claude Code's own instructions leak in.

Authorization stays in one place: ``can_use_tool`` forwards the decision to the
harness, which already owns the effect classification and the authorization
mailbox. The SDK never makes a policy decision of its own.

Only the SDK itself is a dependency; the harness is reached over its existing
HTTP service using the standard library.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolAnnotations,
    ToolPermissionContext,
    create_sdk_mcp_server,
    tool,
)

SERVER_NAME = "harness"

# The harness classifies every tool by effect. These are the only three values
# it emits; anything else means the harness and this bridge are out of sync.
READ_ONLY = "read_only"
REVERSIBLE = "reversible"
DESTRUCTIVE = "destructive"


class HarnessError(RuntimeError):
    """The harness was reachable but rejected or failed the request."""


@dataclass(frozen=True)
class ToolSpec:
    """One tool as the harness describes it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    effect: str
    idempotent: bool

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "ToolSpec":
        effect = raw["effect"]
        if effect not in (READ_ONLY, REVERSIBLE, DESTRUCTIVE):
            raise HarnessError(
                f"tool {raw.get('name')!r} has unknown effect {effect!r}; "
                "the harness registry and this bridge disagree"
            )
        return cls(
            name=raw["name"],
            description=raw["description"],
            input_schema=raw["input_schema"],
            effect=effect,
            idempotent=bool(raw.get("idempotent", False)),
        )

    def annotations(self) -> ToolAnnotations:
        """Translate the harness effect classification into MCP annotations.

        ``readOnlyHint`` is the only one the SDK acts on -- it lets read-only
        tools run in parallel -- so it must stay accurate. The rest are
        informational and simply carry the harness's classification through.
        """
        return ToolAnnotations(
            readOnlyHint=self.effect == READ_ONLY,
            destructiveHint=self.effect == DESTRUCTIVE,
            idempotentHint=self.idempotent,
            openWorldHint=True,
        )


class HarnessClient:
    """Talks to the harness HTTP service.

    Blocking I/O is pushed to a worker thread so tool calls never stall the
    SDK's event loop -- several read-only tools may be in flight at once.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise HarnessError(f"{method} {path} failed: {error.code} {detail}") from error
        except urllib.error.URLError as error:
            raise HarnessError(
                f"cannot reach the harness at {self._base_url}: {error.reason}. "
                "Is `harness serve` running?"
            ) from error

    async def list_tools(self) -> list[ToolSpec]:
        payload = await asyncio.to_thread(self._request, "GET", "/v1/tools", None)
        return [ToolSpec.from_json(entry) for entry in payload["tools"]]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request, "POST", "/v1/tools/call", {"name": name, "arguments": arguments}
        )

    async def authorize(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Ask the harness whether this call is allowed.

        Returns ``(allowed, reason)``. The reason is only meaningful when the
        call was rejected.
        """
        payload = await asyncio.to_thread(
            self._request,
            "POST",
            "/v1/tools/authorize",
            {"name": name, "arguments": arguments},
        )
        return bool(payload["authorized"]), payload.get("reason", "")


def _render(result: dict[str, Any]) -> dict[str, Any]:
    """Turn a harness tool result into an MCP tool result.

    A failed tool is reported with ``is_error`` rather than raised, so the model
    reads the harness's own message and can react to it instead of seeing a
    bare Python traceback.
    """
    status = result.get("status")
    if status != "succeeded":
        message = result.get("error") or f"tool {status}"
        return {"content": [{"type": "text", "text": message}], "is_error": True}

    output = result.get("output")
    text = output if isinstance(output, str) else json.dumps(output, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def build_tool(client: HarnessClient, spec: ToolSpec) -> Any:
    """Wrap one harness tool as an SDK tool.

    The harness's JSON Schema is passed through untouched -- the Python
    decorator accepts a full JSON Schema dict, so there is no second schema to
    keep in sync and no lossy translation step.
    """

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _render(await client.call_tool(spec.name, args))
        except HarnessError as error:
            # Compose the message rather than letting the exception surface raw,
            # so the model can tell a transport failure from a tool failure.
            return {
                "content": [{"type": "text", "text": f"harness call failed: {error}"}],
                "is_error": True,
            }

    handler.__name__ = spec.name
    return tool(
        spec.name,
        spec.description,
        spec.input_schema,
        annotations=spec.annotations(),
    )(handler)


def _permission_handler(
    client: HarnessClient,
) -> Callable[[str, dict[str, Any], ToolPermissionContext], Awaitable[Any]]:
    """Delegate every permission decision to the harness.

    Without this the SDK would apply its own policy on top of the harness's,
    and the two could disagree. The harness already knows each tool's effect and
    owns the authorization mailbox, so it stays the single authority.
    """

    async def can_use_tool(
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> Any:
        prefix = f"mcp__{SERVER_NAME}__"
        if not tool_name.startswith(prefix):
            # With tools=[] nothing else should exist. Deny rather than guess.
            return PermissionResultDeny(
                message=f"{tool_name} is not a harness tool", interrupt=False
            )
        try:
            allowed, reason = await client.authorize(tool_name[len(prefix) :], input_data)
        except HarnessError as error:
            return PermissionResultDeny(message=f"authorization unavailable: {error}")
        if allowed:
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=reason or "the harness rejected this call")

    return can_use_tool


async def build_options(
    client: HarnessClient,
    *,
    system_prompt: str,
    model: str | None = None,
    cwd: str | None = None,
    max_turns: int | None = None,
) -> ClaudeAgentOptions:
    """Assemble SDK options whose entire tool surface is the harness registry."""
    specs = await client.list_tools()
    if not specs:
        raise HarnessError("the harness exposed no tools; nothing for the model to use")

    server = create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[build_tool(client, spec) for spec in specs],
    )

    return ClaudeAgentOptions(
        mcp_servers={SERVER_NAME: server},
        # Every harness tool is reachable; `can_use_tool` decides each call.
        # Listing nothing in allowed_tools keeps the harness in the loop.
        tools=[],  # strip every built-in Claude Code tool
        setting_sources=[],  # ignore ~/.claude and project settings
        system_prompt=system_prompt,
        can_use_tool=_permission_handler(client),
        model=model,
        cwd=cwd,
        max_turns=max_turns,
    )
