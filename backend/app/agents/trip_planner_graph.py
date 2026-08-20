"""旅行规划 LangGraph 工作流。

该模块只负责显式编排现有四个 Agent 和结果解析逻辑，不创建 LLM、MCP
工具或子 Agent。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from ..models.schemas import TripPlan, TripRequest


class TripPlannerState(TypedDict, total=False):
    """单次旅行规划请求在图中的独立状态。"""

    request: TripRequest
    attraction_response: str
    weather_response: str
    hotel_response: str
    planner_response: str
    trip_plan: TripPlan


class TripPlannerDependencies(Protocol):
    """Graph 对现有旅行规划器能力的最小依赖接口。"""

    attraction_agent: Any
    weather_agent: Any
    hotel_agent: Any
    planner_agent: Any

    def _build_attraction_query(self, request: TripRequest) -> str: ...

    def _build_planner_query(
        self,
        request: TripRequest,
        attractions: str,
        weather: str,
        hotels: str = "",
    ) -> str: ...

    def _parse_response(self, response: str, request: TripRequest) -> TripPlan: ...


class TripPlannerGraph:
    """将旅行规划流程编译为可复用的 LangGraph。"""

    def __init__(self, dependencies: TripPlannerDependencies) -> None:
        self._dependencies = dependencies
        # Graph 只在包装器初始化时编译一次；每次 invoke 仅创建新的状态字典。
        self.compiled_graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(TripPlannerState)
        builder.add_node("attraction", self.attraction_node)
        builder.add_node("weather", self.weather_node)
        builder.add_node("hotel", self.hotel_node)
        builder.add_node("planner", self.planner_node)
        builder.add_node("parse", self.parse_node)

        # 三个数据 Agent 互不依赖，由 LangGraph 并行调度；规划节点只有在
        # 三个分支全部写入状态后才会执行。
        builder.add_edge(START, "attraction")
        builder.add_edge(START, "weather")
        builder.add_edge(START, "hotel")
        builder.add_edge(["attraction", "weather", "hotel"], "planner")
        builder.add_edge("planner", "parse")
        builder.add_edge("parse", END)
        return builder.compile()

    def attraction_node(self, state: TripPlannerState) -> dict[str, str]:
        """调用现有景点 Agent，只写入景点原始响应。"""
        started_at = perf_counter()
        try:
            print("📍 步骤1: 搜索景点...")
            query = self._dependencies._build_attraction_query(state["request"])
            response = self._dependencies.attraction_agent.run(query)
            print(f"景点搜索结果: {response[:200]}...\n")
            return {"attraction_response": response}
        except Exception as error:
            self._report_node_error("景点搜索", error)
            raise
        finally:
            self._report_node_timing("景点搜索", started_at)

    def weather_node(self, state: TripPlannerState) -> dict[str, str]:
        """调用现有天气 Agent，只写入天气原始响应。"""
        started_at = perf_counter()
        try:
            print("🌤️  步骤2: 查询天气...")
            request = state["request"]
            query = (
                f"请使用amap_maps_weather工具查询{request.city}的天气信息。\n"
                f"[TOOL_CALL:amap_maps_weather:city={request.city}]"
            )
            response = self._dependencies.weather_agent.run(query)
            print(f"天气查询结果: {response[:200]}...\n")
            return {"weather_response": response}
        except Exception as error:
            self._report_node_error("天气查询", error)
            raise
        finally:
            self._report_node_timing("天气查询", started_at)

    def hotel_node(self, state: TripPlannerState) -> dict[str, str]:
        """调用现有酒店 Agent，只写入酒店原始响应。"""
        started_at = perf_counter()
        try:
            print("🏨 步骤3: 搜索酒店...")
            request = state["request"]
            query = (
                f"请使用amap_maps_text_search工具搜索{request.city}的"
                f"{request.accommodation}酒店。\n"
                f"[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={request.city}]"
            )
            response = self._dependencies.hotel_agent.run(query)
            print(f"酒店搜索结果: {response[:200]}...\n")
            return {"hotel_response": response}
        except Exception as error:
            self._report_node_error("酒店推荐", error)
            raise
        finally:
            self._report_node_timing("酒店推荐", started_at)

    def planner_node(self, state: TripPlannerState) -> dict[str, str]:
        """整合前三个原始响应并调用现有行程规划 Agent。"""
        started_at = perf_counter()
        try:
            print("📋 步骤4: 生成行程计划...")
            query = self._dependencies._build_planner_query(
                state["request"],
                state["attraction_response"],
                state["weather_response"],
                state["hotel_response"],
            )
            response = self._dependencies.planner_agent.run(query)
            print(f"行程规划结果: {response[:300]}...\n")
            return {"planner_response": response}
        except Exception as error:
            self._report_node_error("行程规划", error)
            raise
        finally:
            self._report_node_timing("行程规划", started_at)

    def parse_node(self, state: TripPlannerState) -> dict[str, TripPlan]:
        """解析规划 Agent 响应，只写入最终 TripPlan。"""
        try:
            trip_plan = self._dependencies._parse_response(
                state["planner_response"], state["request"]
            )
            return {"trip_plan": trip_plan}
        except Exception as error:
            self._report_node_error("结果解析", error)
            raise

    def invoke(self, request: TripRequest) -> TripPlan:
        """使用新的初始状态同步执行已编译 Graph。"""
        final_state = self.compiled_graph.invoke({"request": request})
        return final_state["trip_plan"]

    @staticmethod
    def _report_node_error(node_name: str, error: Exception) -> None:
        """记录失败节点和原异常，不输出配置或敏感信息。"""
        print(f"节点[{node_name}]执行失败: {error}")

    @staticmethod
    def _report_node_timing(node_name: str, started_at: float) -> None:
        """记录节点耗时，不输出请求内容或敏感配置。"""
        print(f"[PERF][NODE] name={node_name} elapsed={perf_counter() - started_at:.2f}s")
