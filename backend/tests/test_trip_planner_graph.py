"""旅行规划 LangGraph 节点与固定流程测试。"""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

hello_agents_stub = types.ModuleType("hello_agents")
hello_agents_stub.SimpleAgent = type("SimpleAgent", (), {})
hello_agents_stub.HelloAgentsLLM = type("HelloAgentsLLM", (), {})
hello_agents_tools_stub = types.ModuleType("hello_agents.tools")
hello_agents_tools_stub.MCPTool = type("MCPTool", (), {})
sys.modules.setdefault("hello_agents", hello_agents_stub)
sys.modules.setdefault("hello_agents.tools", hello_agents_tools_stub)


from app.agents.trip_planner_graph import TripPlannerGraph  # noqa: E402
from app.models.schemas import TripPlan, TripRequest  # noqa: E402


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


def plan_json() -> str:
    return json.dumps(
        {
            "city": "杭州",
            "start_date": "2026-09-01",
            "end_date": "2026-09-02",
            "days": [],
            "weather_info": [],
            "overall_suggestions": "测试建议",
        },
        ensure_ascii=False,
    )


class RecordingAgent:
    def __init__(
        self,
        name: str,
        calls: list[tuple[str, str]],
        response: str,
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
        return self.response


class FakeDependencies:
    def __init__(self, attraction_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.attraction_agent = RecordingAgent(
            "attraction", self.calls, "景点原始结果", attraction_error
        )
        self.weather_agent = RecordingAgent("weather", self.calls, "天气原始结果")
        self.hotel_agent = RecordingAgent("hotel", self.calls, "酒店原始结果")
        self.planner_agent = RecordingAgent("planner", self.calls, plan_json())

    def _build_attraction_query(self, request: TripRequest) -> str:
        keywords = request.preferences[0] if request.preferences else "景点"
        return (
            f"请使用amap_maps_text_search工具搜索{request.city}的{keywords}相关景点。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={request.city}]"
        )

    def _build_planner_query(
        self,
        request: TripRequest,
        attractions: str,
        weather: str,
        hotels: str = "",
    ) -> str:
        return f"{request.city}|{attractions}|{weather}|{hotels}"

    def _parse_response(self, response: str, request: TripRequest) -> TripPlan:
        return TripPlan(**json.loads(response))


def quiet_call(function, *args):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return function(*args)


class TripPlannerGraphTests(unittest.TestCase):
    def test_nodes_only_return_their_own_state_update(self) -> None:
        dependencies = FakeDependencies()
        workflow = TripPlannerGraph(dependencies)
        request = make_request()

        attraction = quiet_call(workflow.attraction_node, {"request": request})
        weather = quiet_call(workflow.weather_node, {"request": request})
        hotel = quiet_call(workflow.hotel_node, {"request": request})
        planner = quiet_call(
            workflow.planner_node,
            {
                "request": request,
                "attraction_response": attraction["attraction_response"],
                "weather_response": weather["weather_response"],
                "hotel_response": hotel["hotel_response"],
            },
        )
        parsed = quiet_call(
            workflow.parse_node,
            {
                "request": request,
                "planner_response": planner["planner_response"],
            },
        )

        self.assertEqual(set(attraction), {"attraction_response"})
        self.assertEqual(set(weather), {"weather_response"})
        self.assertEqual(set(hotel), {"hotel_response"})
        self.assertEqual(set(planner), {"planner_response"})
        self.assertEqual(set(parsed), {"trip_plan"})

    def test_compiled_graph_runs_fixed_serial_flow_once(self) -> None:
        dependencies = FakeDependencies()
        workflow = TripPlannerGraph(dependencies)
        compiled_graph = workflow.compiled_graph

        result = quiet_call(workflow.invoke, make_request())

        self.assertIs(workflow.compiled_graph, compiled_graph)
        self.assertEqual(
            [name for name, _ in dependencies.calls],
            ["attraction", "weather", "hotel", "planner"],
        )
        self.assertEqual(dependencies.calls[1][1], "请查询杭州的天气信息")
        self.assertEqual(dependencies.calls[2][1], "请搜索杭州的经济型酒店")
        self.assertEqual(
            dependencies.calls[3][1],
            "杭州|景点原始结果|天气原始结果|酒店原始结果",
        )
        self.assertEqual(result.city, "杭州")

    def test_node_error_is_logged_and_reraised_without_extra_calls(self) -> None:
        dependencies = FakeDependencies(RuntimeError("景点服务失败"))
        workflow = TripPlannerGraph(dependencies)

        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaisesRegex(
            RuntimeError, "景点服务失败"
        ):
            workflow.invoke(make_request())

        self.assertEqual([name for name, _ in dependencies.calls], ["attraction"])
        self.assertIn("节点[景点搜索]执行失败: 景点服务失败", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
