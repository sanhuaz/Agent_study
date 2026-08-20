"""OpenAI 兼容 LLM 客户端的离线配置测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.services import llm_service  # noqa: E402


def test_llm_client_disables_hidden_retries() -> None:
    settings = SimpleNamespace(
        openai_model="test-model",
        openai_api_key="test-key",
        openai_base_url="https://example.invalid",
    )
    empty_environment = {
        "LLM_MODEL_ID": "",
        "LLM_API_KEY": "",
        "OPENAI_API_KEY": "",
        "LLM_BASE_URL": "",
        "OPENAI_BASE_URL": "",
        "LLM_TIMEOUT": "60",
    }

    with (
        patch.dict(os.environ, empty_environment, clear=False),
        patch.object(llm_service, "get_settings", return_value=settings),
        patch.object(llm_service, "OpenAI") as openai_client,
    ):
        llm_service.OpenAICompatibleLLM()

    openai_client.assert_called_once_with(
        api_key="test-key",
        base_url="https://example.invalid",
        timeout=60,
        max_retries=0,
    )
