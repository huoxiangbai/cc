# P3 收尾报告

2026-10-03，Asia/Shanghai。**P3 实现与隔离验收已闭合，可以接续 P4；本轮停止，不实施 P4，不代表生产切换或全量外部集成验收。** 用户最新授权已执行：独立 SQLite 替代 H2 的业务问数角色，可信访客身份、持久 owner 和 Tool 内部认证；原 Java/H2 保留对照回滚。Reactor MySQL 账本、Tool SQLite 和业务 SQLite 三者独立。

## 实现与覆盖

| 范围 | 实现位置 | 最终验收 |
|---|---|---|
| SQLite 连接/发现/元数据初始化同步 | `reactor-backend/reactor_backend/adapters/sqlite_business.py`、`business_db.py`、`data_catalog.py` | 新隔离库真实执行；TABLE/SQL metadata、刷新及失败保留旧 active；ES/Qdrant 真实请求路径与失败契约测试 |
| NL2SQL/自动分析 | `data_query/`、`transport/data.py`，原 Tool `analysis_component/schema_data.py` | schema→原生成器→AST/模型关系/SQLite 方言→实际 SQL→表格/图表/CSV/来源；get_data 返回真实 DataFrame |
| 私有 file/KB/document/history/data | `adapters/private_resources.py`、`transport/private_tool.py`、`reactor-backend/migrations/001_private_resource_acl.sql` | 原资源 URL/ID/路径关系；同访客正常、跨访客403、缺身份/伪 owner/错误内部认证拒绝、旧无 owner 不认领、强杀重启映射保留 |
| 内部认证与分析回调 | 原 Tool `util/internal_auth.py`、`util/file_util.py`、`mrag/utils/download_utils.py` | 独立服务凭证和带身份/范围/期限的签名；任意外部 URL 不获内部凭证 |
| 原 React 文件/KB 入口 | 原 `mragWorkspace.ts`、文件 renderer/FileList | 现有 fetch/SSE 补 credentials；问数、分析、报告预览、刷新恢复、建库上传和原文预览实测 |
| 研究/搜索/三社媒/MRAG/数据处理/CodeAct/SOP | 既有 P3 adapters、research、原 reactor-tool | 复用现有实现及专用账本，保留 Tool/Data/主 Agent 三类 SSE 与错误/超时/取消；外部状态分别保留 |
| Sandbox | 原 executor/runner/runtime guard | 两次已批准守卫接线回归；越界拒绝和真实 local 文件执行通过 |

SQLite 兼容覆盖 JOIN、聚合、CTE 具名列、UNION、日期、NULL、Unicode、大小写、大整数与金额。Decimal 文本精确计算、排序/分组和作用域解析已接入；不可靠的 NUMERIC/REAL 精度及不可无损 JSON 数值明确失败，可显式 CAST TEXT，不静默四舍五入。原 Java 未显式 alias 的聚合 DTO 行为保留，四组 Java 对照通过。详见 [数据兼容/副本核对/回滚](h2-evidence.md)。

## 可复现命令与结果

在项目根目录执行；harness 每次新建隔离 MySQL datadir、独立业务库、Tool SQLite 和文件目录，禁止自动读取 .env。模型仅测试 HTTP fixture，原 Tool、SQL、DataFrame 和文件是真实执行。

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py reactor-backend/tests/test_p2_runtime.py reactor-backend/tests/test_p2_models.py reactor-backend/tests/test_p3_tools.py reactor-backend/tests/test_p3_sandbox.py reactor-backend/tests/test_p3_sqlite.py reactor-backend/tests/test_p3_private_auth.py -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db sqlite
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db mysql
reactor-backend/.venv/bin/python reactor-backend/tests/run_tool_tests.py
reactor-backend/.venv/bin/python reactor-backend/tests/verify_tool_failures.py
```

- Backend：118 项确定性测试通过，含 P1/P2 回归、SQLite12与私有认证/索引4。
- SQLite：42 项真实隔离集成通过；保留 MySQL 业务源同一套42项通过，不是84项不同测试。原 Java 读取 Python 账本5+2+11帧通过。
- 原 Tool：24文件127项，114通过/13失败；Git HEAD 原源码新副本逐项复现相同13失败。等价检查通过不等于原13项通过。
- 原 UI：436项，434通过/2失败，Git HEAD新副本同样失败；原 UI 构建通过（保留既有 lottie/chunk 警告）。uv 离线锁检查、wheel/sdist资源打包检查通过。

启动配置、SQLite新文件初始化、001加法迁移和真实 adapter 必需配置见 [backend README](../../reactor-backend/README.md)。迁移命令仅在明确授权副本运行；本轮只有新隔离库，不执行旧 DROP。浏览器复现两个终端：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db sqlite --serve
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /printed/fresh/reactor-p3-root
```

## 真实用户流程与完整产物

原工作台命名→勾选数据分析输入 P3_DATA→真实 SQLite sales 三行查询 A=30、B=7.5，表格/柱图可见。新 ReAct 会话输入“P3_DATA 通过数据分析工具查询分类销售额并交付完整来源报告”→原 auto_analysis/get_data/NL2SQL→实际 SQLite→真实 DataFrame→`分类销售分析.md`→预览→刷新→近期会话恢复→同报告预览成功。完整 CSV、图表配置、来源 SQL/模型/文件/ID 和原始 SSE 已复制留档。

独立 `/data/chatQuery` 是原问数 SSE，本身不创建主 Agent Run；不能声称此临时问数页面具有主 Agent 历史恢复。上面的恢复证据属于主 Agent 自动分析真实流程。

原 MRAG→知识源→建库“P3 SQLite 私有来源库”→上传 ui-source.txt→原 URL 预览实际原文；owner 持久化，另一访客请求浏览器生成的 KB、document、分析文件均403。文档后台入库因缺 embedding 配置明确失败，页面显示失败/未完成切片，不伪造向量入库成功。

[机器证据索引](fixtures/p3-closure-evidence.json)记录新库根路径、资源关系、B403、完整产物大小/SHA256、JUnit与原始事件；[产物目录](fixtures/p3-closure-artifacts)保留副本。浏览器截图： [表格](fixtures/p3-closure-ui-table.png)、[图表](fixtures/p3-closure-ui-chart.png)、[恢复后报告](fixtures/p3-closure-ui-restored-file.png)、[KB](fixtures/p3-closure-ui-kb.png)、[入库明确失败](fixtures/p3-closure-ui-document-failed.png)、[原文预览](fixtures/p3-closure-ui-document-preview.png)。前轮真实公开 Python 教程 WebFetch 全文/URL/SHA 与真实 CodeAct total=37.5 文件仍见 [前轮报告](p3-report.md)及其证据，不作为付费搜索或模型供应商实测。

## 原 Tool 13 项失败的逐项处置

原测试全部保留且仍返回非零；[原/现源码失败比对](fixtures/p3-closure-artifacts/failure-baseline.json)包含完整测试名和日志。以下是用例方法名；类及文件见机器记录。

| 用例 | 已复现原因/验收处置 |
|---|---|
| test_analysis_profile_should_allow_build_output_path_helper | Windows D:\temp fixture 在 macOS 路径语义不同；原HEAD同失败，需目标平台复验 |
| test_analysis_profile_should_allow_pathlib_import_with_safe_output_path | 同上；实际隔离合法文件执行另已通过 |
| test_analysis_profile_should_block_pathlib_write_outside_output_dir | 原测试未开启既有 guard，原默认允许；部署显式开启，真实越界拒绝另已通过 |
| test_analysis_profile_should_block_write_outside_output_dir | 同上；不把原测试改成通过 |
| test_workspace_profile_should_allow_workspace_local_write | Windows fixture 与 macOS 实际目录不一致；保留平台验收项 |
| test_guard_should_normalize_relative_output_write_for_pathlib | Windows/Mac 路径前缀假设；HEAD同失败，原目录协议保留 |
| test_e2b_keeps_kernel_state_across_executes | fake SDK 在 macOS 创建 Linux /home/user，OSError45；Linux/live E2B 单独待验 |
| test_executor_facade_routes_to_e2b_and_downloads_outputs | 同上，保留原失败及真实 SDK 路径 |
| test_executor_passes_configured_proxy_to_sandbox_factory | 同上 |
| test_injects_file_and_main_name | 同上 |
| test_uploads_local_input_files | 同上 |
| test_should_return_explicit_failure_chunk_when_upstream_error | 原 Tool 首帧 error+DONE，旧断言要求 choices；保持不同 SSE 协议，错误路径另已验 |
| test_should_list_nested_image_files_without_returning_directories | 文件真实存在；macOS /var 与 resolve 后 /private/var 字符串差异，原HEAD同失败 |

原 UI 两失败也保留：GeneralInput旧断言期待“深度思考”，现实现为 ReAct/PlanExecute；WorkspaceMRag utils旧断言期待 http://127.0.0.1:1601，原现实现默认 /tool。[UI基线证据](fixtures/p3-closure-artifacts/ui-failure-baseline.json)。未删除、跳过或计为通过。

## 服务分别记录与正式切换前限制

V表示这里注明的实际或隔离验证，U表示真实集成未验证；配置存在不等于 live 启用。

| 服务/渠道 | 实现/配置启用 | 本轮独立实际状态 |
|---|---|---|
| Grok、GPT/Responses、Exa、Tavily、Brave 原生 WebSearch | 五真实 adapter；无key | 每渠道请求/错误 fixture V；各 live U |
| DeepSearch DDG/Bing/Jina/Sogou/Serper/Exa | 原六 engine；隔离默认 DDG，其余未选/缺key | 进度/章节/来源/错误 V；各完整网络研究 U |
| WebFetch direct | 原真实 HTTP/parser；公开 Python 教程 | 全文文件 V；供应商提炼 U |
| Twitter/Reddit/雪球 | 原三只读路由；无凭证 | 缺凭证明确失败 V；各 live U |
| MRAG KB/doc/history SQLite | 原 Tool store；新库启用 | 建库/上传/原文/历史/ACL V；向量入库明确失败 |
| MRAG Qdrant、文本/图片/页面 embedding、VLM/rerank | 真实 adapter 保留；未配服务 | 请求/错误契约 V；各 live U |
| MinerU/OCR、URL/crawl4ai | 原桥接保留；无完整服务 | 原路由测试 V；PDF/图片/URL完整入库引用 U |
| OSS/S3 | 原 SDK 保留；无凭证 | 私有公开永久URL未获认证网关实证，protected上传503；live U |
| SOP Qdrant/embedding/rerank | 原 CRUD/recall；未配 | 隔离契约 V；TCP/UI明确失败，完整 live U |
| TableRAG ES/Qdrant | 真实元数据/数值/向量同步召回；隔离关闭，启用协议测试 | SQL实际发现和协议/失败 V；各真实服务 U |
| MySQL ledger/metadata/owner、SQLite业务、Tool SQLite | 三角色独立新库启用；保留业务MySQLadapter | 实际 SQL/账本/owner/文件/恢复 V；旧副本 U |
| ClickHouse | 真实 HTTP/方言/metadata adapter；无实例 | 请求/FORMAT JSON fixture V；live U |
| H2 | Java/P0实现保留；Python业务由SQLite替代 | P0原mem V；旧H2副本迁移 U，不采用 JDBC 过渡 |
| local CodeAct/Sandbox | 原 executor，三个 guard 显式 true | 实际代码/文件/超时/越界拒绝 V；不是OS容器隔离证明 |
| E2B | 原 SDK/config保留；未选/无key | 配置 V；5 fake 平台失败，真实 remote U |
| 模型供应商 | 真实 adapter 保留；测试 HTTP fixture | 确定性协议 V；各供应商 live U |
| Skill/MCP | 原渠道类/资源保留；完整 runtime 留 P4 | 不称全部原生内置，未跨阶段实现 |

还需正式环境逐项验证凭证/模型/搜索/向量/OCR/SOP/ClickHouse/E2B、私有对象网关、旧数据副本与 HTTPS/代理。metadata与ES/Qdrant不提供跨服务分布式事务；正式同步须先备份与失败重同步。旧 H2 仅准备副本导出/精度与PK/FK核对/回滚方案，未操作旧数据。这些保留为正式切换前验收，不重新阻止本轮代码收尾。

## 停止点与 P4 接续

本轮仅本地改动、隔离环境验证；未 push/PR/更改 origin/创建云仓库/触碰生产数据/覆盖 .env/执行旧 DROP；已有 workflow 与 .gitignore 改动保留。测试日志和新数据库保留，关闭本轮服务与测试标签。

下一轮从 [progress](progress.md) 当前检查点和 [plan P4](plan.md) 接续：跨 turn working memory、压缩/长期记忆、flush/review、完整 Skill package/runtime、MCP STDIO/SSE/Streamable HTTP、ToolSearch/延迟加载及相关原入口、权限和恢复契约。复用 P0–P3 清单与证据，不重启整轮审计、不重复请求已经批准的SQLite/ACL/守卫方案；发现新增协议缺口按P0证据提出具体方案。P4实施需要下一轮明确任务，本轮收尾停止。
