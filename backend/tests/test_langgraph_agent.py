"""LangGraph Agent 子图的离线行为测试。"""

from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.agents.langgraph_agent import LangGraphAgent  # noqa: E402


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[list[dict[str, str]]] = []

    def invoke(self, messages, **kwargs) -> str:
        self.calls.append(deepcopy(messages))
        return next(self.responses)


class FakeToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.tool = {
            "name": "maps_text_search",
            "description": "搜索指定城市中的地点",
            "input_schema": {
                "properties": {
                    "keywords": {"type": "string"},
                    "city": {"type": "string"},
                    "limit": {"type": "integer"},
                }
            },
        }

    def list_tools(self) -> list[str]:
        return ["amap_maps_text_search"]

    def get_tool(self, tool_name: str):
        return self.tool if tool_name == "amap_maps_text_search" else None

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        self.calls.append((tool_name, arguments))
        return "工具返回的景点数据"


class LangGraphAgentTests(unittest.TestCase):
    def test_tool_loop_keeps_text_protocol_and_injects_result(self) -> None:
        llm = FakeLLM(
            [
                "[TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=杭州,limit=3]",
                "景点最终回答",
            ]
        )
        tools = FakeToolClient()
        agent = LangGraphAgent("景点搜索专家", llm, "景点提示词", tools)
        compiled_graph = agent.compiled_graph

        result = agent.run("搜索杭州景点")

        self.assertEqual(result, "景点最终回答")
        self.assertIs(agent.compiled_graph, compiled_graph)
        self.assertEqual(
            tools.calls,
            [
                (
                    "amap_maps_text_search",
                    {"keywords": "历史文化", "city": "杭州", "limit": 3},
                )
            ],
        )
        self.assertIn("## 可用工具", llm.calls[0][0]["content"])
        self.assertIn("工具返回的景点数据", llm.calls[1][-1]["content"])

    def test_three_tool_iterations_are_followed_by_one_final_model_call(self) -> None:
        tool_call = "[TOOL_CALL:amap_maps_text_search:keywords=景点,city=杭州]"
        llm = FakeLLM([tool_call, tool_call, tool_call, "最终回答"])
        tools = FakeToolClient()
        agent = LangGraphAgent("景点搜索专家", llm, "景点提示词", tools)

        result = agent.run("搜索杭州景点")

        self.assertEqual(result, "最终回答")
        self.assertEqual(len(llm.calls), 4)
        self.assertEqual(len(tools.calls), 3)

    def test_agent_without_tools_keeps_history_between_calls(self) -> None:
        llm = FakeLLM(["第一次回答", "第二次回答"])
        agent = LangGraphAgent("行程规划专家", llm, "规划提示词")

        self.assertEqual(agent.run("第一次问题"), "第一次回答")
        self.assertEqual(agent.run("第二次问题"), "第二次回答")

        second_messages = llm.calls[1]
        self.assertEqual(
            second_messages[1:4],
            [
                {"role": "user", "content": "第一次问题"},
                {"role": "assistant", "content": "第一次回答"},
                {"role": "user", "content": "第二次问题"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
