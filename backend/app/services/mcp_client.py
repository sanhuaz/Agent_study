"""不依赖 Agent 框架的同步 MCP 客户端。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, TypeVar

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


T = TypeVar("T")


def _run_async(operation: Callable[[], Awaitable[T]]) -> T:
    """在同步调用点执行异步 MCP 操作，兼容 FastAPI 已运行的事件循环。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(operation())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(operation())).result()


class StdioMCPClient:
    """通过 stdio 发现并调用 MCP 工具。"""

    def __init__(
        self,
        name: str,
        server_command: list[str],
        env: dict[str, str] | None = None,
        auto_expand: bool = True,
    ) -> None:
        if not server_command:
            raise ValueError("MCP 服务器启动命令不能为空")

        self.name = name
        self.server_command = server_command
        self.env = env or {}
        self.auto_expand = auto_expand
        self.prefix = f"{name}_" if auto_expand else ""
        self._available_tools = self._discover_tools()

    def _new_transport(self) -> StdioTransport:
        return StdioTransport(
            command=self.server_command[0],
            args=self.server_command[1:],
            env=self.env or None,
        )

    def _discover_tools(self) -> list[dict[str, Any]]:
        async def discover() -> list[dict[str, Any]]:
            async with Client(self._new_transport()) as client:
                tools = await client.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": getattr(tool, "inputSchema", {}) or {},
                    }
                    for tool in tools
                ]

        try:
            return _run_async(discover)
        except Exception:
            # 与旧实现保持一致：发现异常先转为空列表，由调用方统一终止初始化。
            return []

    def list_tools(self) -> list[str]:
        return [self._external_name(tool["name"]) for tool in self._available_tools]

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        internal_name = self._internal_name(tool_name)
        return next(
            (
                tool
                for tool in self._available_tools
                if tool.get("name") == internal_name
            ),
            None,
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        internal_name = self._internal_name(tool_name)
        started_at = perf_counter()

        async def call() -> Any:
            async with Client(self._new_transport()) as client:
                result = await client.call_tool(internal_name, arguments)
                return self._extract_content(result)

        result = _run_async(call)
        print(
            "[PERF][MCP] "
            f"tool={internal_name} elapsed={perf_counter() - started_at:.2f}s "
            f"result_chars={len(str(result))}"
        )
        return f"工具 '{internal_name}' 执行结果:\n{result}"

    def run(self, parameters: dict[str, Any]) -> str:
        """兼容现有地图服务使用的 action 调用接口。"""
        action = str(parameters.get("action", "")).lower()
        if not action and "tool_name" in parameters:
            action = "call_tool"

        try:
            if action == "list_tools":
                if not self._available_tools:
                    return "没有找到可用的工具"
                result = f"找到 {len(self._available_tools)} 个工具:\n"
                for tool in self._available_tools:
                    result += f"- {tool['name']}: {tool['description']}\n"
                return result

            if action == "call_tool":
                tool_name = parameters.get("tool_name")
                if not tool_name:
                    return "错误：必须指定 tool_name 参数"
                return self.call_tool(str(tool_name), parameters.get("arguments", {}))

            if not action:
                return "错误：必须指定 action 参数或 tool_name 参数"
            return f"错误：不支持的操作 '{action}'"
        except Exception as error:
            return f"MCP 操作失败: {error}"

    def _external_name(self, internal_name: str) -> str:
        return f"{self.prefix}{internal_name}" if self.auto_expand else internal_name

    def _internal_name(self, external_name: str) -> str:
        if self.prefix and external_name.startswith(self.prefix):
            return external_name[len(self.prefix) :]
        return external_name

    @staticmethod
    def _extract_content(result: Any) -> Any:
        content = getattr(result, "content", None)
        if not content:
            return None
        values = [
            getattr(item, "text", getattr(item, "data", str(item)))
            for item in content
        ]
        return values[0] if len(values) == 1 else values
