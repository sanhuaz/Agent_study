"""重构前的旅行规划行为基线测试。

这些测试使用假 Agent 固定原实现的调用轨迹和返回契约，不会连接真实
LLM、高德 MCP 或其他外部服务。
"""

from __future__ import annotations

import json
import io
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# 原模块在导入阶段引用 HelloAgents 类型。基线测试不测试初始化，因此使用
# 最小替身隔离外部依赖，确保测试绝不会启动 MCP 子进程或真实 LLM。
hello_agents_stub = types.ModuleType("hello_agents")
hello_agents_stub.SimpleAgent = type("SimpleAgent", (), {})
hello_agents_stub.HelloAgentsLLM = type("HelloAgentsLLM", (), {})
hello_agents_tools_stub = types.ModuleType("hello_agents.tools")
hello_agents_tools_stub.MCPTool = type("MCPTool", (), {})
sys.modules.setdefault("hello_agents", hello_agents_stub)
sys.modules.setdefault("hello_agents.tools", hello_agents_tools_stub)


from app.agents.trip_planner_agent import MultiAgentTripPlanner  # noqa: E402
from app.models.schemas import TripPlan, TripRequest  # noqa: E402


class FakeAgent:
    """记录查询并返回固定文本的假 Agent。"""

    def __init__(
        self,
        name: str,
        calls: list[tuple[str, str]],
        response: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.response = response
        self.error = error

    def run(self, query: str) -> str:
        self.calls.append((self.name, query))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def make_request() -> TripRequest:
    return TripRequest(
        city="杭州",
        start_date="2026-09-01",
        end_date="2026-09-02",
        travel_days=2,
        transportation="公共交通",
        accommodation="经济型",
        preferences=["历史文化", "美食"],
        free_text_input="步行不要太多",
    )


def valid_plan_data() -> dict:
    return {
        "city": "杭州",
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
        "days": [],
        "weather_info": [],
        "overall_suggestions": "测试建议",
        "budget": {
            "total_attractions": 0,
            "total_hotels": 0,
            "total_meals": 0,
            "total_transportation": 0,
            "total": 0,
        },
    }


def valid_plan_json() -> str:
    return json.dumps(valid_plan_data(), ensure_ascii=False)


def expected_planner_query() -> str:
    return """请根据以下信息生成杭州的2天旅行计划:

**基本信息:**
- 城市: 杭州
- 日期: 2026-09-01 至 2026-09-02
- 天数: 2天
- 交通方式: 公共交通
- 住宿: 经济型
- 偏好: 历史文化, 美食

**景点信息:**
景点原始结果

**天气信息:**
天气原始结果

**酒店信息:**
酒店原始结果

**要求:**
1. 每天安排2-3个景点
2. 每天必须包含早中晚三餐
3. 每天推荐一个具体的酒店(从酒店信息中选择)
3. 考虑景点之间的距离和交通方式
4. 返回完整的JSON格式数据
5. 景点的经纬度坐标要真实准确

**额外要求:** 步行不要太多"""


def make_planner(
    calls: list[tuple[str, str]],
    planner_response: str | None = None,
    attraction_error: Exception | None = None,
) -> MultiAgentTripPlanner:
    planner = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    planner.attraction_agent = FakeAgent(
        "attraction", calls, "景点原始结果", attraction_error
    )
    planner.weather_agent = FakeAgent("weather", calls, "天气原始结果")
    planner.hotel_agent = FakeAgent("hotel", calls, "酒店原始结果")
    planner.planner_agent = FakeAgent(
        "planner", calls, planner_response or valid_plan_json()
    )
    return planner


def call_without_console_output(function: Callable, *args):
    """隔离原项目的 emoji 日志，避免 Windows GBK 控制台影响业务测试。"""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return function(*args)


class TripPlannerBaselineTests(unittest.TestCase):
    def test_plan_trip_preserves_order_queries_and_success_result(self) -> None:
        calls: list[tuple[str, str]] = []
        planner = make_planner(calls)

        result = call_without_console_output(planner.plan_trip, make_request())

        self.assertEqual(
            [name for name, _ in calls],
            ["attraction", "weather", "hotel", "planner"],
        )
        self.assertEqual(
            calls[0][1],
            "请使用amap_maps_text_search工具搜索杭州的历史文化相关景点。\n"
            "[TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=杭州]",
        )
        self.assertEqual(calls[1][1], "请查询杭州的天气信息")
        self.assertEqual(calls[2][1], "请搜索杭州的经济型酒店")
        self.assertEqual(calls[3][1], expected_planner_query())
        self.assertEqual(result.model_dump(), TripPlan(**valid_plan_data()).model_dump())

    def test_plan_trip_agent_error_returns_existing_fallback(self) -> None:
        calls: list[tuple[str, str]] = []
        planner = make_planner(calls, attraction_error=RuntimeError("景点服务失败"))

        result = call_without_console_output(planner.plan_trip, make_request()).model_dump()

        self.assertEqual([name for name, _ in calls], ["attraction"])
        self.assertEqual(result["city"], "杭州")
        self.assertEqual(result["start_date"], "2026-09-01")
        self.assertEqual(result["end_date"], "2026-09-02")
        self.assertEqual(result["weather_info"], [])
        self.assertIsNone(result["budget"])
        self.assertEqual(len(result["days"]), 2)
        self.assertEqual(
            [item["name"] for item in result["days"][0]["attractions"]],
            ["杭州景点1", "杭州景点2"],
        )
        self.assertEqual(
            result["days"][0]["attractions"][0]["location"],
            {"longitude": 116.4, "latitude": 39.9},
        )

    def test_parse_response_accepts_all_existing_json_forms(self) -> None:
        request = make_request()
        planner = make_planner([])
        raw_json = valid_plan_json()
        cases = {
            "json_markdown": f"说明\n```json\n{raw_json}\n```",
            "plain_markdown": f"说明\n```\n{raw_json}\n```",
            "embedded_object": f"生成结果如下：{raw_json}，请查收",
        }

        for name, response in cases.items():
            with self.subTest(name=name):
                result = call_without_console_output(
                    planner._parse_response, response, request
                )
                self.assertEqual(result.model_dump(), TripPlan(**valid_plan_data()).model_dump())

    def test_parse_response_failures_use_existing_fallback(self) -> None:
        request = make_request()
        planner = make_planner([])
        invalid_model = valid_plan_data()
        invalid_model.pop("city")
        cases: dict[str, str | Callable[[], str]] = {
            "no_json": "没有结构化数据",
            "invalid_json": "```json\n{不是合法JSON}\n```",
            "invalid_model": lambda: json.dumps(invalid_model, ensure_ascii=False),
        }

        for name, response_or_factory in cases.items():
            with self.subTest(name=name):
                response = (
                    response_or_factory()
                    if callable(response_or_factory)
                    else response_or_factory
                )
                result = call_without_console_output(
                    planner._parse_response, response, request
                )
                self.assertEqual(result.city, request.city)
                self.assertEqual(result.weather_info, [])
                self.assertIsNone(result.budget)
                self.assertEqual(len(result.days), request.travel_days)


if __name__ == "__main__":
    unittest.main()
