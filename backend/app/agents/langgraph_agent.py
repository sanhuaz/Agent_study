"""基于 LangGraph 的轻量 Agent 子图。"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph


class ChatModel(Protocol):
    """Agent 对 OpenAI 兼容模型的最小依赖。"""

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


class ToolClient(Protocol):
    """Agent 对 MCP 客户端的最小依赖。"""

    def list_tools(self) -> list[str]: ...

    def get_tool(self, tool_name: str) -> dict[str, Any] | None: ...

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str: ...


class ParsedToolCall(TypedDict):
    tool_name: str
    parameters: str
    original: str


class AgentState(TypedDict, total=False):
    """单次 Agent 调用在子图中的独立状态。"""

    input_text: str
    history: list[dict[str, str]]
    messages: list[dict[str, str]]
    response: str
    tool_calls: list[ParsedToolCall]
    iteration: int
    max_tool_iterations: int
    final_response: str


class LangGraphAgent:
    """保持原有文本工具协议的 LangGraph Agent。"""

    _TOOL_CALL_PATTERN = re.compile(r"\[TOOL_CALL:([^:]+):([^\]]+)\]")

    def __init__(
        self,
        name: str,
        llm: ChatModel,
        system_prompt: str | None = None,
        tool_client: ToolClient | None = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.tool_client = tool_client
        self._history: list[dict[str, str]] = []
        self._history_lock = threading.Lock()
        self.compiled_graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("prepare", self.prepare_node)
        builder.add_node("model", self.model_node)
        builder.add_node("tools", self.tools_node)
        builder.add_node("final_model", self.final_model_node)
        builder.add_node("finish", self.finish_node)

        builder.add_edge(START, "prepare")
        builder.add_conditional_edges(
            "prepare",
            self.route_after_prepare,
            {"tools": "tools", "model": "model"},
        )
        builder.add_conditional_edges(
            "model",
            self.route_after_model,
            {"tools": "tools", "finish": "finish"},
        )
        builder.add_conditional_edges(
            "tools",
            self.route_after_tools,
            {"model": "model", "final_model": "final_model"},
        )
        builder.add_edge("final_model", "finish")
        builder.add_edge("finish", END)
        return builder.compile()

    def prepare_node(self, state: AgentState) -> dict[str, Any]:
        messages = [{"role": "system", "content": self._enhanced_system_prompt()}]
        messages.extend(state.get("history", []))
        messages.append({"role": "user", "content": state["input_text"]})
        explicit_tool_calls = self._parse_tool_calls(state["input_text"])
        return {
            "messages": messages,
            "response": state["input_text"],
            "tool_calls": explicit_tool_calls,
            "iteration": 0,
        }

    def route_after_prepare(self, state: AgentState) -> Literal["tools", "model"]:
        """明确指定工具时直接执行，避免再次让模型决定同一工具。"""
        if (
            self.tool_client is not None
            and state.get("tool_calls")
            and state["max_tool_iterations"] > 0
        ):
            return "tools"
        return "model"

    def model_node(self, state: AgentState) -> dict[str, Any]:
        response = self.llm.invoke(state["messages"])
        return {
            "response": response,
            "tool_calls": self._parse_tool_calls(response),
        }

    def route_after_model(self, state: AgentState) -> Literal["tools", "finish"]:
        if (
            self.tool_client is not None
            and state.get("tool_calls")
            and state["max_tool_iterations"] > 0
        ):
            return "tools"
        return "finish"

    def tools_node(self, state: AgentState) -> dict[str, Any]:
        response = state["response"]
        clean_response = response
        tool_results = []

        for call in state["tool_calls"]:
            tool_results.append(
                self._execute_tool_call(call["tool_name"], call["parameters"])
            )
            clean_response = clean_response.replace(call["original"], "")

        messages = list(state["messages"])
        messages.append({"role": "assistant", "content": clean_response})
        messages.append(
            {
                "role": "user",
                "content": (
                    "工具执行结果：\n"
                    + "\n\n".join(tool_results)
                    + "\n\n请基于这些结果给出完整的回答。"
                ),
            }
        )
        return {"messages": messages, "iteration": state["iteration"] + 1}

    def route_after_tools(
        self, state: AgentState
    ) -> Literal["model", "final_model"]:
        if state["iteration"] >= state["max_tool_iterations"]:
            return "final_model"
        return "model"

    def final_model_node(self, state: AgentState) -> dict[str, str]:
        return {"final_response": self.llm.invoke(state["messages"])}

    def finish_node(self, state: AgentState) -> dict[str, str]:
        if "final_response" in state:
            return {"final_response": state["final_response"]}
        return {"final_response": state["response"]}

    def run(self, input_text: str, max_tool_iterations: int = 3, **_: Any) -> str:
        """同步执行已编译子图，并保留原有 Agent 历史行为。"""
        with self._history_lock:
            history = list(self._history)

        final_state = self.compiled_graph.invoke(
            {
                "input_text": input_text,
                "history": history,
                "max_tool_iterations": max_tool_iterations,
            }
        )
        final_response = final_state["final_response"]

        with self._history_lock:
            self._history.extend(
                [
                    {"role": "user", "content": input_text},
                    {"role": "assistant", "content": final_response},
                ]
            )
        return final_response

    def list_tools(self) -> list[str]:
        if self.tool_client is None:
            return []
        return self.tool_client.list_tools()

    def _enhanced_system_prompt(self) -> str:
        base_prompt = self.system_prompt or "你是一个有用的AI助手。"
        if self.tool_client is None:
            return base_prompt

        descriptions = []
        for tool_name in self.tool_client.list_tools():
            tool = self.tool_client.get_tool(tool_name) or {}
            description = tool.get("description", "")
            descriptions.append(f"- {tool_name}: {description}")

        if not descriptions:
            return base_prompt

        tools_section = "\n\n## 可用工具\n"
        tools_section += "你可以使用以下工具来帮助回答问题：\n"
        tools_section += "\n".join(descriptions) + "\n"
        tools_section += "\n## 工具调用格式\n"
        tools_section += "当需要使用工具时，请使用以下格式：\n"
        tools_section += "`[TOOL_CALL:{tool_name}:{parameters}]`\n\n"
        tools_section += "### 参数格式说明\n"
        tools_section += "1. **多个参数**：使用 `key=value` 格式，用逗号分隔\n"
        tools_section += "   示例：`[TOOL_CALL:calculator_multiply:a=12,b=8]`\n"
        tools_section += "   示例：`[TOOL_CALL:filesystem_read_file:path=README.md]`\n\n"
        tools_section += "2. **单个参数**：直接使用 `key=value`\n"
        tools_section += "   示例：`[TOOL_CALL:search:query=Python编程]`\n\n"
        tools_section += "3. **简单查询**：可以直接传入文本\n"
        tools_section += "   示例：`[TOOL_CALL:search:Python编程]`\n\n"
        tools_section += "### 重要提示\n"
        tools_section += "- 参数名必须与工具定义的参数名完全匹配\n"
        tools_section += "- 数字参数直接写数字，不需要引号：`a=12` 而不是 `a=\"12\"`\n"
        tools_section += "- 文件路径等字符串参数直接写：`path=README.md`\n"
        tools_section += "- 工具调用结果会自动插入到对话中，然后你可以基于结果继续回答\n"
        return base_prompt + tools_section

    def _parse_tool_calls(self, text: str) -> list[ParsedToolCall]:
        return [
            {
                "tool_name": tool_name.strip(),
                "parameters": parameters.strip(),
                "original": f"[TOOL_CALL:{tool_name}:{parameters}]",
            }
            for tool_name, parameters in self._TOOL_CALL_PATTERN.findall(text)
        ]

    def _execute_tool_call(self, tool_name: str, parameters: str) -> str:
        if self.tool_client is None:
            return "❌ 错误：未配置工具客户端"

        if self.tool_client.get_tool(tool_name) is None:
            return f"❌ 错误：未找到工具 '{tool_name}'"

        try:
            arguments = self._parse_tool_parameters(tool_name, parameters)
            result = self.tool_client.call_tool(tool_name, arguments)
            return f"🔧 工具 {tool_name} 执行结果：\n{result}"
        except Exception as error:
            return f"❌ 工具调用失败：{error}"

    def _parse_tool_parameters(
        self, tool_name: str, parameters: str
    ) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        stripped = parameters.strip()

        if stripped.startswith("{"):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    return self._convert_parameter_types(tool_name, loaded)
            except json.JSONDecodeError:
                pass

        if "=" not in parameters:
            return {"input": parameters}

        for pair in parameters.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                parsed[key.strip()] = value.strip()
        return self._convert_parameter_types(tool_name, parsed)

    def _convert_parameter_types(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if self.tool_client is None:
            return parameters

        tool = self.tool_client.get_tool(tool_name) or {}
        schema = tool.get("input_schema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        converted = {}

        for key, value in parameters.items():
            parameter_type = properties.get(key, {}).get("type")
            try:
                if parameter_type == "number" and isinstance(value, str):
                    converted[key] = float(value)
                elif parameter_type == "integer" and isinstance(value, str):
                    converted[key] = int(value)
                elif parameter_type == "boolean" and isinstance(value, str):
                    converted[key] = value.lower() in ("true", "1", "yes")
                else:
                    converted[key] = value
            except (TypeError, ValueError):
                converted[key] = value
        return converted
