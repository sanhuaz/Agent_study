"""FastMCP stdio 适配层的离线测试。"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.services import mcp_client as mcp_module  # noqa: E402


class FakeFastMCPClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, transport) -> None:
        self.transport = transport

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    async def list_tools(self):
        return [
            types.SimpleNamespace(
                name="maps_weather",
                description="查询天气",
                inputSchema={
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict):
        self.__class__.calls.append((name, arguments))
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text="杭州天气数据")]
        )


class StdioMCPClientTests(unittest.TestCase):
    def tearDown(self) -> None:
        FakeFastMCPClient.calls.clear()

    def test_discovers_prefixes_and_calls_raw_mcp_tool(self) -> None:
        with patch.object(mcp_module, "Client", FakeFastMCPClient):
            client = mcp_module.StdioMCPClient(
                name="amap",
                server_command=["uvx", "amap-mcp-server"],
                env={"AMAP_MAPS_API_KEY": "test-key"},
            )
            result = client.call_tool("amap_maps_weather", {"city": "杭州"})

        self.assertEqual(client.list_tools(), ["amap_maps_weather"])
        self.assertEqual(client.get_tool("amap_maps_weather")["name"], "maps_weather")
        self.assertEqual(FakeFastMCPClient.calls, [("maps_weather", {"city": "杭州"})])
        self.assertEqual(result, "工具 'maps_weather' 执行结果:\n杭州天气数据")

    def test_run_keeps_existing_action_interface(self) -> None:
        with patch.object(mcp_module, "Client", FakeFastMCPClient):
            client = mcp_module.StdioMCPClient(
                name="amap",
                server_command=["uvx", "amap-mcp-server"],
            )
            result = client.run(
                {
                    "action": "call_tool",
                    "tool_name": "maps_weather",
                    "arguments": {"city": "杭州"},
                }
            )

        self.assertEqual(result, "工具 'maps_weather' 执行结果:\n杭州天气数据")


if __name__ == "__main__":
    unittest.main()
