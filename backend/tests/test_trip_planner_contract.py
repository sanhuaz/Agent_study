"""旅行规划 API、依赖共享和单例初始化契约测试。"""

from __future__ import annotations

import asyncio
import io
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents import trip_planner_agent as agent_module  # noqa: E402
from app.api.main import app as fastapi_app  # noqa: E402
from app.api.routes import trip as trip_route  # noqa: E402
from app.models.schemas import (  # noqa: E402
    TripPlan,
    TripPlanResponse,
    TripRequest,
)


def make_request() -> TripRequest:
    return TripRequest(
        city="杭州",
        start_date="2026-09-01",
        end_date="2026-09-01",
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型",
        preferences=["历史文化"],
        free_text_input="",
    )


def make_plan() -> TripPlan:
    return TripPlan(
        city="杭州",
        start_date="2026-09-01",
        end_date="2026-09-01",
        days=[],
        weather_info=[],
        overall_suggestions="测试建议",
    )


class FakePlanner:
    def __init__(self, plan: TripPlan) -> None:
        self.plan = plan
        self.requests: list[TripRequest] = []

    def plan_trip(self, request: TripRequest) -> TripPlan:
        self.requests.append(request)
        return self.plan


class RaisingPlanner:
    def plan_trip(self, request: TripRequest) -> TripPlan:
        raise RuntimeError("未预期的服务错误")


class FakeLangGraphAgent:
    instances: list["FakeLangGraphAgent"] = []

    def __init__(self, name, llm, system_prompt, tool_client=None) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.tool_client = tool_client
        self.__class__.instances.append(self)

    def list_tools(self) -> list[str]:
        return self.tool_client.list_tools() if self.tool_client else []


class FakeStdioMCPClient:
    instances: list["FakeStdioMCPClient"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self._available_tools = [{"name": "maps_weather"}]
        self.__class__.instances.append(self)

    def list_tools(self) -> list[str]:
        return ["amap_maps_weather"]


class TripPlannerContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        agent_module._multi_agent_planner = None
        FakeLangGraphAgent.instances.clear()
        FakeStdioMCPClient.instances.clear()

    def test_api_path_method_and_models_are_unchanged(self) -> None:
        plan_route = next(route for route in trip_route.router.routes if route.path == "/trip/plan")
        openapi_paths = fastapi_app.openapi()["paths"]

        self.assertEqual(plan_route.methods, {"POST"})
        self.assertIn("/api/trip/plan", openapi_paths)
        self.assertIn("post", openapi_paths["/api/trip/plan"])
        self.assertIs(plan_route.response_model, TripPlanResponse)
        self.assertEqual(
            list(TripRequest.model_fields),
            [
                "city",
                "start_date",
                "end_date",
                "travel_days",
                "transportation",
                "accommodation",
                "preferences",
                "free_text_input",
            ],
        )
        self.assertEqual(
            list(TripPlanResponse.model_fields), ["success", "message", "data"]
        )

    def test_api_success_response_keeps_existing_shape(self) -> None:
        request = make_request()
        fake_planner = FakePlanner(make_plan())

        with patch.object(
            trip_route, "get_trip_planner_agent", return_value=fake_planner
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            response = asyncio.run(trip_route.plan_trip(request))

        self.assertEqual(fake_planner.requests, [request])
        self.assertEqual(
            response.model_dump(),
            {
                "success": True,
                "message": "旅行计划生成成功",
                "data": make_plan().model_dump(),
            },
        )

    def test_api_unexpected_error_keeps_http_500_semantics(self) -> None:
        with patch.object(
            trip_route, "get_trip_planner_agent", return_value=RaisingPlanner()
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(trip_route.HTTPException) as raised:
                asyncio.run(trip_route.plan_trip(make_request()))

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail, "生成旅行计划失败: 未预期的服务错误"
        )

    def test_singleton_initializes_shared_dependencies_and_graph_once(self) -> None:
        fake_llm = object()
        fake_settings = types.SimpleNamespace(amap_api_key="test-key")
        graph_factory = MagicMock(side_effect=lambda planner: object())

        with (
            patch.object(agent_module, "get_llm", return_value=fake_llm),
            patch.object(agent_module, "get_settings", return_value=fake_settings),
            patch.object(agent_module, "LangGraphAgent", FakeLangGraphAgent),
            patch.object(agent_module, "StdioMCPClient", FakeStdioMCPClient),
            patch.object(agent_module, "resolve_uvx_command", return_value="uvx"),
            patch.object(agent_module, "TripPlannerGraph", graph_factory),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            first = agent_module.get_trip_planner_agent()
            second = agent_module.get_trip_planner_agent()

        self.assertIs(first, second)
        self.assertEqual(len(FakeLangGraphAgent.instances), 4)
        self.assertTrue(
            all(agent.llm is fake_llm for agent in FakeLangGraphAgent.instances)
        )
        self.assertEqual(len(FakeStdioMCPClient.instances), 1)
        shared_tool = FakeStdioMCPClient.instances[0]
        self.assertEqual(
            [agent.tool_client for agent in FakeLangGraphAgent.instances],
            [shared_tool, shared_tool, shared_tool, None],
        )
        self.assertTrue(shared_tool.kwargs["auto_expand"])
        self.assertEqual(shared_tool.kwargs["server_command"], ["uvx", "amap-mcp-server"])
        graph_factory.assert_called_once_with(first)


if __name__ == "__main__":
    unittest.main()
