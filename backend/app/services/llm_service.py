"""OpenAI 兼容 LLM 服务模块。"""

import os
from time import perf_counter
from typing import Any

from openai import OpenAI

from ..config import get_settings


class OpenAICompatibleLLM:
    """项目内部使用的最小 OpenAI 兼容模型客户端。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.model = os.getenv("LLM_MODEL_ID") or settings.openai_model
        self.api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or settings.openai_api_key
        )
        self.base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or settings.openai_base_url
        )
        self.timeout = int(os.getenv("LLM_TIMEOUT", "60"))
        self.temperature = 0.7
        self.max_tokens = None

        if not self.api_key or not self.base_url:
            raise RuntimeError("API密钥和服务地址必须被提供或在.env文件中定义。")

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            # 旅行接口已经约定外部调用失败时直接返回失败，关闭 SDK 的两次
            # 隐式重试，避免单次请求因连续超时被放大到数分钟。
            max_retries=0,
        )

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """同步调用聊天补全接口，保持原有模型参数。"""
        started_at = perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                **{
                    key: value
                    for key, value in kwargs.items()
                    if key not in ("temperature", "max_tokens")
                },
            )
            content = response.choices[0].message.content
            print(
                "[PERF][LLM] "
                f"elapsed={perf_counter() - started_at:.2f}s "
                f"messages={len(messages)} response_chars={len(content or '')}"
            )
            return content
        except Exception as error:
            print(f"[PERF][LLM] failed elapsed={perf_counter() - started_at:.2f}s")
            raise RuntimeError(f"LLM调用失败: {error}") from error

# 全局LLM实例
_llm_instance = None


def get_llm() -> OpenAICompatibleLLM:
    """
    获取LLM实例(单例模式)
    
    Returns:
        OpenAI 兼容 LLM 实例
    """
    global _llm_instance
    
    if _llm_instance is None:
        _llm_instance = OpenAICompatibleLLM()
        
        print(f"✅ LLM服务初始化成功")
        print("   提供商: OpenAI兼容接口")
        print(f"   模型: {_llm_instance.model}")
    
    return _llm_instance


def reset_llm():
    """重置LLM实例(用于测试或重新配置)"""
    global _llm_instance
    _llm_instance = None
