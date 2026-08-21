# LangGraph 多智能体旅行规划助手 🌍✈️

基于 LangGraph 构建的多智能体旅行规划应用。系统根据目的地、日期、交通方式、住宿偏好和旅行偏好，并行完成景点搜索、天气查询和酒店推荐，再生成多日行程，通过 Vue 3 页面展示地图、景点图片、每日安排和预算信息。

当前版本：`v0.4.0`

## 功能概览

- 通过4个职责独立的 Agent 协作生成旅行计划
- 使用 LangGraph `StateGraph` 显式管理节点、状态和执行顺序
- 通过 FastMCP 调用高德地图 MCP 服务，查询景点、天气和酒店信息
- 使用 OpenAI 兼容接口接入大语言模型
- 使用 FastAPI 提供类型安全的 HTTP API
- 使用 Vue 3、TypeScript 和 Ant Design Vue 构建前端
- 支持高德地图展示、POI 图片和预算信息
- Agent、MCP、模型或结果解析失败时直接返回失败，不生成占位计划

## 四个 Agent

1. **景点搜索 Agent**：根据目的地与用户偏好，通过高德地图 MCP 搜索相关景点。
2. **天气查询 Agent**：查询目的地天气，为行程安排和出行建议提供信息。
3. **酒店推荐 Agent**：结合目的地与住宿偏好搜索酒店。
4. **行程规划 Agent**：汇总景点、天气、酒店和用户需求，生成结构化多日旅行计划。

前三个 Agent 共享同一个高德 MCP 客户端；行程规划 Agent 只调用模型，不调用地图工具。

## 系统架构

```mermaid
flowchart TD
    U[用户填写旅行需求] --> V[Vue 3 前端]
    V --> API[POST /api/trip/plan]
    API --> F[MultiAgentTripPlanner]
    F --> G[旅行规划主 LangGraph]

    G --> A[景点搜索节点]
    G --> W[天气查询节点]
    G --> H[酒店推荐节点]
    A --> P[行程规划节点]
    W --> P
    H --> P
    P --> R[JSON 解析节点]

    A --> AG1[景点 Agent 子图]
    W --> AG2[天气 Agent 子图]
    H --> AG3[酒店 Agent 子图]
    P --> AG4[规划 Agent 子图]

    AG1 --> MCP[共享 FastMCP 客户端]
    AG2 --> MCP
    AG3 --> MCP
    MCP --> AMCP[uvx amap-mcp-server]
    AMCP --> AMAP[高德地图服务]

    AG1 --> LLM[OpenAI 兼容模型接口]
    AG2 --> LLM
    AG3 --> LLM
    AG4 --> LLM

    R --> PLAN[TripPlan]
    PLAN --> V
```

旅行主流程是固定图：

```text
                    ┌→ 景点搜索 ─┐
START ───────────────┼→ 天气查询 ──┼→ 行程规划 → JSON 解析 → END
                    └→ 酒店推荐 ─┘
```

每个 Agent 也是一个已编译的 LangGraph 子图。带工具的 Agent 收到明确工具指令时会直接调用 MCP；没有明确工具指令时才由模型选择工具。工具结果回填后由模型生成回答，工具调用最多执行三轮。

> 当前项目没有自动重试、Checkpointer、长期记忆、人工确认或流式进度；三个数据 Agent 的并行执行已由主 LangGraph 实现。

## 技术栈

### 后端

- Python 3.13（项目验证环境）
- LangGraph 1.1.x
- OpenAI Python SDK（兼容 OpenAI 协议的模型服务）
- FastMCP 2.x
- FastAPI
- Pydantic V2
- Uvicorn

### 前端

- Vue 3
- TypeScript
- Vite
- Ant Design Vue
- Axios
- 高德地图 JavaScript API

## 项目结构

```text
Travel_Plan/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── langgraph_agent.py       # Agent 状态、节点和工具循环子图
│   │   │   ├── trip_planner_agent.py    # 提示词、依赖初始化和结果解析
│   │   │   └── trip_planner_graph.py    # 旅行规划主 StateGraph
│   │   ├── api/
│   │   │   ├── main.py                  # FastAPI 应用入口
│   │   │   └── routes/                  # 旅行、POI 和地图接口
│   │   ├── models/
│   │   │   └── schemas.py               # Pydantic 请求、响应和业务模型
│   │   ├── services/
│   │   │   ├── llm_service.py           # OpenAI 兼容模型客户端
│   │   │   ├── mcp_client.py            # FastMCP stdio 客户端
│   │   │   ├── amap_service.py          # 高德地图服务封装
│   │   │   └── amap_photo_service.py    # 高德 POI 图片查询
│   │   └── config.py
│   ├── tests/                            # 离线行为、Graph、MCP 和 API 契约测试
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── services/api.ts
│   │   ├── types/index.ts
│   │   └── views/
│   │       ├── Home.vue
│   │       └── Result.vue
│   ├── package.json
│   └── .env.example
└── README.md
```

## 环境要求

- Windows 10/11
- Python 3.13
- Node.js 18 或更高版本
- 可用的 OpenAI 兼容模型 API
- 高德地图 Web 服务 Key
- 高德地图 Web 端 JavaScript API Key 与安全密钥
- `uvx`，用于启动 `amap-mcp-server`

## 快速开始

以下命令使用 PowerShell。

```powershell
git clone https://github.com/sanhuaz/Travel_Plan.git
Set-Location ".\Travel_Plan"
```

除克隆命令外，下面各段命令均从仓库根目录执行。后端和前端需要分别在两个 PowerShell 窗口运行。

### 1. 首次配置后端

```powershell
Set-Location ".\backend"

python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Copy-Item ".\.env.example" ".\.env"
# 编辑 .env，填入自己的模型和高德地图配置

Set-Location ".."
```

### 2. 启动后端

```powershell
Set-Location ".\backend"

# 避免 Windows GBK 控制台无法输出日志中的 Unicode 字符
$env:PYTHONIOENCODING = "utf-8"

# 为 uvx/amap-mcp-server 使用当前用户可写的独立缓存目录
$env:LOCALAPPDATA = Join-Path $env:TEMP "agent-study-localappdata"
$env:APPDATA = Join-Path $env:TEMP "agent-study-appdata"
New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA, $env:APPDATA | Out-Null

& ".\.venv\Scripts\python.exe" -m uvicorn app.api.main:app `
  --host 0.0.0.0 `
  --port 8000 `
  --log-level info
```

后端地址：

- API 根地址：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

### 3. 首次配置并启动前端

```powershell
Set-Location ".\frontend"

npm install
Copy-Item ".\.env.example" ".\.env.local"
# 编辑 .env.local，填入自己的前端配置

npm run dev -- --host 0.0.0.0 --port 5173
```

访问：`http://127.0.0.1:5173`

完成首次配置后，日常启动前端只需执行：

```powershell
Set-Location ".\frontend"
npm run dev -- --host 0.0.0.0 --port 5173
```

停止服务时，在对应窗口按 `Ctrl+C`。

## 环境变量

### 后端 `backend/.env`

| 变量 | 说明 |
|---|---|
| `LLM_MODEL_ID` | OpenAI 兼容模型名称 |
| `LLM_API_KEY` | 模型服务 API Key |
| `LLM_BASE_URL` | 模型服务 Base URL |
| `LLM_TIMEOUT` | 模型请求超时秒数 |
| `AMAP_API_KEY` | 高德地图 Web 服务 Key，同时传递给 MCP 服务 |
| `HOST` / `PORT` | 后端监听地址与端口 |
| `CORS_ORIGINS` | 允许访问后端的前端地址 |
| `LOG_LEVEL` | 日志级别 |

### 前端 `frontend/.env.local`

| 变量 | 说明 |
|---|---|
| `VITE_API_BASE_URL` | 后端 API 地址 |
| `VITE_AMAP_WEB_KEY` | 高德地图 Web 端 JavaScript API Key |
| `VITE_AMAP_WEB_JS_KEY` | 高德地图安全密钥 |

真实 `.env` 和 `.env.local` 已由 `.gitignore` 忽略。不要把 Key 写入源码、README、日志或提交历史。

## 使用流程

1. 在首页填写目的地、日期、交通方式、住宿偏好和旅行偏好。
2. 前端向 `POST /api/trip/plan` 提交 `TripRequest`。
3. LangGraph 并行调用景点、天气和酒店 Agent，三者完成后调用规划 Agent。
4. 规划 Agent 返回 JSON，解析节点将其校验为 `TripPlan`。
5. 前端展示每日行程、天气、酒店、餐饮、预算、地图和景点图片。
6. Agent 执行或 JSON 解析失败时，后端返回 HTTP 500，前端显示生成失败。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/trip/plan` | 生成旅行计划 |
| `GET` | `/api/poi/photo` | 根据景点名称查询高德 POI 图片 |
| `GET` | `/api/poi/search` | 搜索 POI |
| `GET` | `/api/poi/detail/{poi_id}` | 查询 POI 详情 |
| `GET` | `/api/map/poi` | 地图 POI 搜索接口 |
| `GET` | `/api/map/weather` | 天气查询接口 |
| `POST` | `/api/map/route` | 路线规划接口 |

## 测试与验证

后端离线测试不会调用真实 LLM 或高德地图服务：

```powershell
Set-Location ".\backend"
python -m pip install pytest
python -m pytest -q
```

`v0.3.0` 发布时记录：

- Pytest：`19 passed, 11 subtests passed`
- 项目虚拟环境在卸载 `hello-agents` 后仍可正常导入并运行离线测试
- `pip check` 未发现依赖冲突
- Vite 直接生产构建完成，共转换 3482 个模块
- 没有执行真实 LLM 与高德地图端到端调用
- v0.4.0 离线回归：`22 passed, 11 subtests passed`

### v0.4.0 真实端到端测速

测试使用模型 `deepseek-v4-flash`、相同广州一日游请求、相同已预热的 `uvx/amap-mcp-server` 缓存和全新后端进程。计时范围为发送 `POST /api/trip/plan` 到收到完整 HTTP 响应；表中有效样本均返回 HTTP 200、`success=true` 和非占位 `TripPlan`。

固定请求：广州，`2026-09-01`，1 天，公共交通，经济型酒店，偏好“历史文化/美食”，额外要求“步行不要太多”。

| 样本 | 工作流 | 完整响应耗时 | 结果 |
|---|---|---:|---|
| v0.3.0 串行基准 | 景点 → 天气 → 酒店 → 规划 | 95.20 秒 | 有效计划 |
| v0.4.0 首次并行样本 | 景点/天气/酒店并行 → 规划 | 251.54 秒 | 有效计划，外部长尾样本 |
| v0.4.0 计时诊断样本 | 景点/天气/酒店并行 → 规划 | 55.71 秒 | 有效计划 |
| v0.4.0 最终优化样本 | 明确工具直达 + 三 Agent 并行 → 规划 | 60.10 秒 | 有效计划 |

计时诊断确认 LangGraph 会并发启动三个数据 Agent。高德 MCP 单次调用约为 `1.5～2.4` 秒，主要耗时来自模型调用和最终 JSON 生成。优化后，明确写在请求中的工具调用会直接进入工具节点，不再先调用模型重复判断；三个数据 Agent 的模型调用总数由 6 次降为 3 次，完整流程由约 7 次降为 4 次。同时关闭 OpenAI SDK 默认的两次隐式重试，使超时或限流按照项目既有失败语义直接返回失败，避免把失败请求放大到数分钟。

最终优化样本相对串行基准的计算结果为：`(95.20 - 60.10) / 95.20 × 100% = 36.86%`。

## 已知边界

- 三个数据 Agent 并行执行，但完整响应时间仍受最慢分支、行程规划模型调用和高德服务网络状况影响。
- Graph 没有节点级自动重试、持久化、流式进度或中断恢复。
- `plan_trip()` 或结果解析发生异常时，API 返回 HTTP 500，不再返回备用计划或占位数据。
- `AmapService` 的部分结构化地图接口仍保留占位解析逻辑；旅行主流程直接消费 MCP 文本结果。
- 前端完整 `npm run build` 仍受既有 TypeScript 类型问题影响；Vite 直接生产构建已验证通过。

## 版本历史

- `v0.1.0`：使用 LangGraph 显式编排旅行规划主流程。
- `v0.2.0`：修复 MCP 工具发现，迁移高德 POI 图片源并清理敏感配置。
- `v0.3.0`：将4个 Agent 改造为 LangGraph 子图，使用 OpenAI SDK 与 FastMCP 完全移除 HelloAgents 运行时依赖。
- `v0.4.0`：并行执行景点、天气和酒店 Agent；明确工具调用直接进入工具节点并关闭模型 SDK 隐式重试；移除备用计划与结果导出功能。

## 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [高德地图开放平台](https://lbs.amap.com/)
- [amap-mcp-server](https://github.com/sugarforever/amap-mcp-server)

---

**LangGraph 多智能体旅行规划助手** — 让旅行计划生成过程更清晰、可测试、可维护。
