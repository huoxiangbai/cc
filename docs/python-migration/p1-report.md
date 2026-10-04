# P1 实现与验收记录

日期：2026-10-03（Asia/Shanghai）。本轮只执行 P1，原 Java/default 入口保留。已完成独立 Python 后端纵向链路的实现和隔离验收；真实供应商模型及真实旧用户数据验收未验证，不得据此正式切换或宣称全部后端迁移完成。

## P0 门槛与保护边界

复用既有审计、fixture、schema、模块说明。原 P0 golden/source 契约对照及选定 **102 Java JUnit、9 Python harness** 通过，无本轮需修复的 P0 确定性失败。已读 A2/A3 权限和恢复证据；具体 stop/answer/expiry/restart 外部协议仍按原方案等待具体决策，未重复请求已确认架构批准，也未提前移植这些入口。

本轮仅新增 backend 和更新迁移文档；保留开始时 `.github/workflows/ocr-review.yml`、`.gitignore`、P0文档/测试改动。工作流差异 SHA-256 前后均为 `2b9ffa4e9d16807d67b6605b7e90de5c2c87130b94760ec7c44b828db944d6ad`。没有 push、PR、远端变更、云仓库、生产连接、加载/覆盖 .env、DROP 或旧清库脚本。H2 未删、未换数据库。

## 实现位置与行为

| 位置（相对项目根） | 实现与契约 |
|---|---|
| `reactor-backend/pyproject.toml` / `uv.lock` / `__main__` | 独立包与锁定依赖、缺省 8101/127.0.0.1、worker=1；Tool 测试依赖单独组 |
| `reactor_backend/bootstrap` | 显式配置/装配、AsyncClient/SQL池 lifespan、单 workspace owner 文件锁；不读取旧环境配置 |
| `models` / `application/query.py` | 无框架领域值/ports；P0 requestId/trace/user/deepThink/model/effort 默认与归一化 |
| `adapters/model.py` | 原 MySQL 模型绑定优先，真实 JSON/SSE Chat Completions、tool-call 分片/usage/reasoning、瞬态重试、空流救援；无假终答、无响应体/密钥日志 |
| `runtime/react.py` / `application/runs.py` | 多轮真实工具→observation→final；先登记工具、并行执行、按 dispatch 顺序回填；批异常先等工具收口，再提交失败；single visitor gate/有限容量/128帧缓冲、断线不取消 |
| `adapters/tool_api.py` / `tools/schemas.json` | 从 P0 原工厂复制的 text_processor/csv_processor/data_transform schema，调用原 `/v1/tool/{name}`，注入可信 session workspace，结构化 observation、错误/超时、产物注册 |
| `adapters/mysql.py` / `delivery/artifacts.py` | 原 Run/LLM/tool/artifact/visitor/session/working_memory 表、ID/status/link/元数据；MySQL SQL/Core + 受限线程池，事务写入，原错拼列 `llm_oberserve` 保留 |
| `projection/events.py` / `history.py` / `tool_history.py` / `genui.py` | 原 Builder/null/data-only SSE、顺序/heartbeat/idle/pending；列表/详情、通用及专用工具/GenUI tree/patch 的只读回放，历史结论来自 Run 总结 |
| `transport/http.py` | 原 bootstrap/naming、query 路径和 `/1/` alias、health、sessions/detail/follow；JSON 绑定错误400、旧业务 envelope、访客归属/cookie/CORS |
| `tests/` | 隔离 doubles/固定模型 HTTP fixture、原 Tool routers 服务、全新 MySQL/SQLite/目录启动器、原 Java read-side 对照、显式供应商实测入口 |

未实现的策略明确失败，不把 PlanSolve/dataAgent/forcePlanMode 静默转为 ReAct。Python 不接管原 Sandbox，不重做 React，不向生产表自动执行 DDL。SSE 结束以账本/必要 working-memory 事务完成为先。

审计补充 F07：当前 Java WebFetch 是直接抓取 + 二次 LLM 提取，没有调用 Python web_fetcher、没有自动登记 Markdown artifact。旧 inventory 中 Python 能力与 Java 运行路径的混写已纠正。本轮采用无需外部凭证的原 text_processor，实际文件处理没有替身。

## 可复现命令

从 `/Users/cuimingkai/Documents/claw-agent/ai-agent`：

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
.venv/bin/python tests/python_migration/run_baseline.py
.venv/bin/python -m unittest discover -s tests/python_migration -p test_harness.py -v
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py
```

启动原 React 的独立隔离测试链路：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --serve
# 在 ui/ 使用脚本输出的 SERVICE_BASE_URL/REACTOR_TOOL_BASE_URL：
# SERVICE_BASE_URL=http://127.0.0.1:<backend端口> REACTOR_TOOL_BASE_URL=http://127.0.0.1:<tool端口> npm run dev
```

生产 adapter 的独立入口（仅在显式配置授权测试副本后）：

```bash
REACTOR_BACKEND_PORT=8101 reactor-backend/.venv/bin/python -m reactor_backend
```

必需环境项、模型来源、单 worker、本机 cookie 设置、原工作台配置及 `--live-model` 实测入口详见 [backend README](../../reactor-backend/README.md)。新 backend 不提供 DB 初始化“便捷生产命令”；隔离脚本始终新建 datadir，无 TCP MySQL，不能自动复用疑似生产连接。

UI 相关用例：

```bash
cd ui
npm test -- src/utils/agentRequest.test.ts src/utils/querySSE.test.ts src/utils/chat/agentRuntimeProjector.test.ts src/pages/Home/VisitorLoginGate.test.tsx src/pages/Home/VisitorBootstrapScreen.test.tsx
```

## 用户流程与数据关联证据

真实 TCP 集成中，`session-real-p1` / `request-real-p1` 的 **Run id=1 → LLM ids=1,2,3 → tool ids=1,2 → artifact id=1**。工具1关联LLM1及artifact1，工具2关联LLM2；每项 requestId/runId/toolCallId 与原关系一致。三次 LLM 账本 token 总量90来自固定 HTTP fixture usage，不能当供应商计费证据。

实际原 text_processor 写入再读取 `报告.md`，内容为中文验收标题和销售额125；workspace文件、SQLite登记、HTTP preview/download均为 **74字节**。SSE种类：`tool_thought → tool_call → file → tool_result → tool_thought → tool_call → tool_result → result`，递增 seq，data-only，没有 event/id/[DONE]。第二轮从 MySQL working_memory 读取第一轮 assistant/tool 成对上下文；不是进程内对话缓存。

真实 TCP 断线后 follow 成功，最终历史 SUCCESS、runCount仍1；没有重新提交原 query。真实缺文件错误登记 tool FAILED/observation，再由固定模型处理并结束；模型401记录 LLM/Run FAILED。访客越权历史/query 被拒绝，坏 DTO 为400。

原 React 浏览器（`reactor-p1-gcon5v70` 独立环境）：bootstrap匿名→命名“P1隔离验收”→输入文件任务→原工具写/读过程→终答/预览→刷新页面→侧栏选近期会话→回放工具卡→文件栏再预览中文文件，全部观察成功。截图：[刷新历史与文件预览](../../target/python-migration-p1/workbench-history.jpg)。工作台其他 pending/管理相关请求404属于未迁移入口，已记录，没有假造空结果。浏览器下载事件捕获超时，所以浏览器下载仍U；原 download HTTP 字节验证V。

原 Java projector 读取导出的 Python实际MySQL行，通用链路 **5帧**、GenUI旧表 tree/输入恢复patch **2帧**逐字段相同，只归一动态taskId。专用旧表的研究/代码/分析/多模态/图片/Canvas/提问读侧 **11帧（含产物）**逐字段对照；不代表真实旧用户数据副本已验收。

## 测试结果和失败记录

最终 **28项契约、10项MySQL/TCP、14项UI相关用例通过**；原Java对照5+2+11帧通过。sdist/wheel构建和运行资源检查、compileall、文档链接/Git diff检查通过。原Tool测试宿主在导入原router前禁用dotenv自动发现，并用审计hook阻止.env读取；核验原源码祖先无.env文件候选。DB模型配置trim、空completionsPath缺省`/chat/completions`、max_tokens16384/temperature0.0已按原Java校准并覆盖。所有本轮创建的服务已停止，保留日志/数据。

最终结果及 root 定位见 [P1证据索引](fixtures/p1-evidence.json)，原始日志/事实/JUnit 保留在 `target/python-migration-p1/latest-integration.json` 指向的临时目录。测试矩阵最后更新于 progress。

初次问题保留证据：沙箱内 mysqld 初始化崩溃，改在同机新隔离环境运行成功；第一次 readiness 因测试 HTTPX 继承代理而超时，改为显式 trust_env=False；原 Tool async SQLite 关闭需要 greenlet，已锁入 integration 组。GenUI新增用例曾误用原目录不支持的Text、种子缺少NOT NULL llm_id、Java测试反序列化抽象ToolStructuredOutput，分别修正测试数据和捕获器；没有修改原schema/Java来迎合测试。生产中发现的并行批提前失败、context异常不在失败边界、follow越层读取均已修复并覆盖。

## 未验证与下一入口

- 真实供应商模型凭证未提供；完整生产HTTP adapter 已实现，`integration.py --live-model` 可执行严格实测，没有demo降级。
- 真实旧MySQL/SQLite/文件副本未提供；本轮为原schema上的新写入和合成旧Java历史。 MySQL9.3 Unixsocket已测；部署使用的MySQL版本/TLS/RSA远端握手未测。
- 全 Tool server 的 OCR/RAG、Sandbox/E2B、代理/TLS部署、H2实际部署、全量模型fallback/struct_parse、压缩、富工具执行、管理与GenUI生成/导出尚不属已完成P1能力。
- A2/A3 外部权限/expiry/claim/restart修复未批准的具体协议不在本轮擅自变更；生产入口不可正式切换。强杀后的RUNNING记录修复/恢复待P2，当前进程退出drain及断线follow不等同重启恢复。

下一入口：在新阶段授权后按 [plan.md](plan.md) P2（完整编排/模型回退/运行控制/HITL）推进，复用本轮 adapters/账本/投影/fixture；涉及 A2/A3 的外部协议先按现有具体方案确认。本轮在 P1 停止。
