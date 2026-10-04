# Reactor Python backend — P5

独立 Python Agent backend，保留原 Java、React、Tool API、Sandbox、MySQL/SQLite 和文件目录。默认部署不切换。在 P2 上实现研究/搜索/三社媒/MRAG/问数/代码和分析工具桥接与原专用账本；全部迁移尚未完成。P3收尾已完成独立SQLite业务源与私有Tool ACL；P4完成工作记忆/压缩、curated与原可选provider、Skill及三传输MCP。真实外部服务/正式切换仍未验证，P5完成GenUI、原文档工具、图片gateway、全部管理与精选；见[P5报告](../docs/python-migration/p5-report.md)。

## 显式环境与启动

Python 3.11–3.13，本轮 Python 3.12.13；使用项目独立虚拟环境与 uv.lock。backend 不发现或加载 `.env`，不创建/迁移表，不执行 DROP/seed。

```bash
# 项目根目录
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --no-dev
# 当前 shell 中显式提供已授权测试副本的配置后启动：
REACTOR_BACKEND_PORT=8101 reactor-backend/.venv/bin/python -m reactor_backend
```

必需：`REACTOR_MYSQL_URL`（mysql+pymysql）、`REACTOR_TOOL_URL`、`REACTOR_WORKSPACE_ROOT`、`REACTOR_TOOL_SERVICE_TOKEN`（独立32+字符内部凭证，backend和Tool一致）；owner加法表须显式迁移，Tool须开启认证。不得因本机已有服务而自动借用连接。模型读取原启用 `ai_client_model/ai_client_api` 绑定；无可用绑定时要求显式 `REACTOR_MODEL_BASE_URL/MODEL_NAME/MODEL_API_KEY`。支持 modelId/modelName/`__db_binding__:id`、重复 ID 与 default 优先级、备用模型用途标记。

默认 `127.0.0.1:8101`、单 worker；`REACTOR_BACKEND_HOST/PORT` 可覆盖。启动同时获取 workspace 文件锁和 MySQL 当前数据库的独占 GET_LOCK；不同 workspace 不能绕过同 DB Python owner。`WEB_CONCURRENCY/REACTOR_BACKEND_WORKERS` 非 1 拒绝启动。Cookie 默认 Secure；本机隔离 HTTP 用 `REACTOR_COOKIE_SECURE=false`。

| 参数 | 行为 |
|---|---|
| REACTOR_PLANNER_MODEL | PlanSolve 独立模型覆盖；为空沿用请求模型 |
| REACTOR_PLANNER_MAX_STEPS | 默认 400，与原 ReactorConfig 对齐 |
| REACTOR_PLANNER_TOOLS | 逗号分隔主 Agent 白名单；缺省原 Java 白名单 |
| REACTOR_MAX_STEPS | ReAct 默认 150 |
| REACTOR_MODEL_PROTOCOL | function_call / struct_parse |
| REACTOR_FALLBACK_MODELS | 额外备用引用，逗号分隔；与 DB 备用链去重 |
| REACTOR_LLM_SETTINGS_FILE | 显式 JSON 文件；每模型采样参数、文本协议和 extParams |
| REACTOR_MAX_SUBAGENTS / REACTOR_SUBAGENT_WAIT_SECONDS | 子 Agent 全局许可默认 4；排队默认 30 秒，超时真实失败 |
| REACTOR_SKILL_ROOT | 显式共享 Skill 库，访客读/物化到会话副本；原脚本实际执行 |
| REACTOR_RECOVER_EXCLUSIVE | 默认 false；**确认旧 Java/Python owner 已退出、该 DB 排他后**才启用 true |
| REACTOR_SYSTEM_PROMPT_FILE | 显式覆盖原 ReAct prompt；PlanSolve 使用原编排 prompt |

`REACTOR_LLM_SETTINGS_FILE` 示例（不含凭证）：

```json
{"default":{"max_tokens":16384,"temperature":0.0,"max_input_tokens":100000,"functionCallType":"function_call","reasoning_effort":"medium","extParams":{"top_p":0.9}}}
```

文件按请求引用/上游模型名匹配；DB 正数 context_window 优先，参数支持标准别名和供应商额外字段。思考开关只对 supports_thinking 模型发送；请求协议字段不会被采样 extras 覆盖。每模型最多初次+5次瞬态重试、一次空流非流式补救；失败按分类决定是否尝试备用，取消直接传播。生产始终调用真实 HTTP adapter。

排他恢复只把孤儿 RUNNING/后台任务/RESUMING claim 收口，保留 ID 和成功/停止事实，**不自动重新调用模型或工具**。RunB SUCCESS 或 WAITING_INPUT 已落库的 claim 标 ANSWERED；无 RunB 或失败标 FAILED。多主机/Java 活跃时不能启用这个无 lease 的恢复窗口。

## 自动创建隔离环境的验证

每次新建临时 root、MySQL datadir（Unix socket、无 TCP）、SQLite 和文件。仅提取原 schema 的 33 个 CREATE TABLE；不会读取 dotenv、接受旧 MySQL URL 或执行 DROP。需本机 mysqld（本轮 9.3）和 P0 缓存 JDK/Maven。

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py reactor-backend/tests/test_p2_models.py reactor-backend/tests/test_p2_runtime.py -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p2
```

确定性测试 59 项；集成结果以 [P2 报告](../docs/python-migration/p2-report.md)为准。集成包含真实 TCP、MySQL claim 竞争、12 路 resume、强杀/重启、原 Tool 文件/SQLite，以及原 Java projector 回放。**只有模型上游是 tests/ 中的 HTTP fixture**。每次结束停止自己创建的进程，保留日志/JUnit/SQL事实；最新路径 `target/python-migration-p2/latest-integration.json`。P1 回归仍可用 `integration.py` 默认 phase p1。

原工作台浏览器流程，两个终端：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p2 --serve
# 在第二个终端把下列路径替换为第一条命令打印的 isolation_root：
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /printed/fresh/reactor-p1-root
```

UI helper 只接受本 harness 新建 root；复制原 UI 源码，排除 `.env*`，依赖复用已安装 node_modules，Vite cache 写隔离目录。端口 3000 忙时明确失败，不停止别人服务。访问 `http://127.0.0.1:3000`，命名后：

- ReAct 输入 `P2_ASK` → 等待 → 刷新 → 侧栏恢复 → 选择答案 → 提交 → 实际报告预览。
- PlanExecute 输入 `P2_PLAN` → 刷新恢复审批 → 修改计划并反馈 → 修订审批 → 编辑 Markdown → 执行计划 → 实际报告。
- 新会话输入 `P2_BG browserbackground` → 根返回 → 刷新恢复 → 子 Agent 面板 Completed/工具产物。
- `P2_STOP` 可验证显式停止；浏览器断开不会自动 stop。

原 UI 源码未改；精选、管理 CRUD、完整工具/研究/GenUI 生成等后续阶段入口会明确 404，不返回伪空成功。测试固定 token 仅用于上述隔离 fixture，不是生产业务功能。

真实供应商验收：显式提供三项 REACTOR_MODEL_* 后执行 `integration.py --live-model`；它仍新建 DB/Tool/文件，只改模型上游。缺凭证会失败，不切替身。当前真实供应商、多供应商 fallback、真实旧数据副本、Nginx/HTTPS、外部 Sandbox/搜索/RAG/MCP 均**未验证**；本机真实 Skill 脚本和三种 MCP 端点已在 P4 验证。

## P3 收尾配置与验收

生产backend只有真实adapter；替身仅在tests。三个数据角色分开：Reactor ledger/metadata/owner仍MySQL，原Tool SQLite仍fileInfo/KB/history，新的绝对路径SQLite只作为H2原业务问数源。

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py reactor-backend/tests/test_p2_models.py reactor-backend/tests/test_p2_runtime.py reactor-backend/tests/test_p3_tools.py reactor-backend/tests/test_p3_sandbox.py reactor-backend/tests/test_p3_sqlite.py reactor-backend/tests/test_p3_private_auth.py -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db sqlite
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db mysql
reactor-backend/.venv/bin/python reactor-backend/tests/run_tool_tests.py
reactor-backend/.venv/bin/python reactor-backend/tests/verify_tool_failures.py
```

收尾118项确定性测试通过；SQLite和保留MySQL业务源各42项真实隔离TCP/Tool/账本集成通过（非84项不同用例）；Java账本5+2+11帧/4组SQL DTO对照通过。原Tool24文件127项114通过/13失败，run_tool_tests仍非零；HEAD原源码在新副本逐项复现同13项，不能算通过。全套UI436项434通过/2个相同HEAD失败，原UI构建通过；明细见 [收尾报告](../docs/python-migration/p3-closure-report.md)。

```bash
# 以下只可在明确授权副本配置好REACTOR_MYSQL_URL后执行；当前仅新隔离库演练。
reactor-backend/.venv/bin/python -m reactor_backend.maintenance acl-migrate --authorized-copy
# business.sqlite必须是绝对新路径，已有文件拒绝；不执行旧schema/DROP。
reactor-backend/.venv/bin/python -m reactor_backend.maintenance sqlite-init --path /absolute/new/isolation/business.sqlite --schema reactor-backend/examples/sqlite-business-schema.sql --authorized-copy
```

复制 [examples-p3-sqlite.json](examples-p3-sqlite.json) 到新隔离目录，替换path为该新库，显式设置 `REACTOR_DATA_CONFIG_FILE=/absolute/new/isolation/data-config.json`。backend启动只读连接/发现并幂等初始化原模型metadata，不做DDL。需要metadata同步时在这个显式配置设forceRefresh=true，完成一次后改回false；失败不将active metadata替换。ES/Qdrant启用时调用真实服务，错误明确失败，不能当作live验证。旧H2数据副本、timezone/特殊SQL与索引回滚计划见 [H2/SQLite证据](../docs/python-migration/h2-evidence.md)。

| 配置 | 作用 |
|---|---|
| REACTOR_DATA_CONFIG_FILE | db.type=sqlite/path/timeout秒，TABLE/SQL modelList；es/qdrant独立启用；不复用ledger/Tool SQLite |
| REACTOR_TOOL_SERVICE_TOKEN | backend和原Tool API/Sandbox一致的独立内部凭证，最少32字符；不传入执行子进程或浏览器 |
| REACTOR_TOOL_AUTH_REQUIRED=true | 在原Tool API/Sandbox启用；backend启动向原Tool核验实际开启，未开启拒绝启动 |
| FILE_SERVER_URL | 原Tool文件公开URL前缀指向backend或同源受保护代理 `/v1/file_tool`；保留原路径和ID |
| FILE_SERVER_INTERNAL_URL | 受保护Tool内部文件地址，凭证仅发到显式已配置host；不对任意外部URL发token |
| ANA_SCHEMA_URL / ANA_DATA_URL | 原Tool分析接口指向backend `/data/queryModelInfo`、`/data/apiChatQuery`，自动带服务认证和签名范围 |
| REACTOR_ANALYSIS_MODELS | 允许分析的原modelCode，逗号分隔 |
| REACTOR_WEB_SEARCH_CONFIG_FILE / REACTOR_DEEPSEARCH_ENGINES | 原五native搜索与Tool六引擎显式选择；缺key不模拟成功 |
| REACTOR_MRAG_KB_IDS | 主Agent明确配置当前访客有owner的KB；原MRAG页面使用其选中私有KB |
| REACTOR_RESEARCH_TIMEOUT | 默认600秒；普通Tool210秒，原timeout/error分开 |

Tool API/local Sandbox进程必须显式开启两次已批准的原守卫，不只配置backend：

```bash
export CODE_INTERPRETER_ENABLE_PRE_EXECUTION_VALIDATION=true
export CODE_INTERPRETER_ENABLE_PATH_SANDBOX=true
export CODE_INTERPRETER_ENABLE_RUNTIME_DOUBLE_CHECK=true
```

local/E2B真实实现保留；守卫不是OS/container隔离。Bash原exit_code/stdout/stderr/timed_out保持。私有S3公开链接尚无认证object gateway实证，protected Tool上传明确503，不静默降级本地；原S3 SDK保留在legacy对照，需单独授权验证私有网关后启用。

本轮不自动启动原server.py生产角色或加载其dotenv；它仍保留原环境加载与外部服务依赖。可复现隔离host通过原router执行真实Tool，只改变配置/模型上游，禁止.env读取；不等同完整OCR/vector/E2B部署实测。

两个终端复现原React：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p3 --business-db sqlite --serve
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /printed/fresh/reactor-p3-root
```

http://127.0.0.1:3000 命名→勾数据分析输入P3_DATA可见真实SQLite表格/图表；新ReAct会话不勾该项，输入“P3_DATA 通过数据分析工具查询分类销售额并交付完整来源报告”→原auto_analysis/get_data/NL2SQL→真实DataFrame→报告预览→刷新→近期会话→同文件预览。独立问数SSE原本不创建主Agent Run历史，不把它称为可恢复Agent。MRAG→知识源→创建“P3 SQLite 私有来源库”→证据→上传新隔离ui-source.txt，文件原URL可预览；缺embedding时显示失败/未完成切片，完整检索U。React只补现有fetch/SSE的credentials include，未换界面。

## 阶段与回滚

RunA WAITING_INPUT → durable decision → claim → RunB；重复请求不重复派发，准入拒绝释放 claim。stop/inject/follow/HITL/capabilities/task 归属与期限/终态 CAS 已按已确认 P0 修复；旧无 owner 会话拒绝访问，需在授权副本明确映射。管理员认证和 Tool 私有资源边界随 P3/P5 接入，不在 P2 声称完成。

当前P4代码与隔离验收已完成并停止；P3 ACL/H2与P4 Skill权限确认已执行，外部live仍U，不代表生产切换或全量迁移完成。下一入口为 plan.md 的 P5，须另行授权。原 Java 和默认入口保留，回滚为停止独立 Python owner 后使用原入口；不清库，不同时写同一个 session。完整实现位置、证据与限制见 [P4报告](../docs/python-migration/p4-report.md)，前轮见 [P3收尾报告](../docs/python-migration/p3-closure-report.md)。

## P4 配置、启动与验收

必需连接/身份配置仍见上文，全部只指向新环境或明确授权副本。新增配置不发现 `.env`；共享库不授予访客写权限。

| 配置 | 行为 |
|---|---|
| REACTOR_SKILL_ROOT | 显式绝对共享库路径；原 `runtime/skills` 31项兼容，手册按需读；管理员CLI维护 |
| REACTOR_SKILL_SCOPE_POLICY=session-copy | 默认；访客在 `.reactor/skill-library` 写/执行自己的副本，禁止symlink/跨会话 |
| REACTOR_MEMORY_CONFIG_FILE | 显式JSON，见 [examples-p4-memory.json](examples-p4-memory.json)；builtin、holographic、openviking可选，flush/review预算 |
| REACTOR_COMPACTION_CONFIG_FILE | 显式JSON，见 [examples-p4-compaction.json](examples-p4-compaction.json)；micro/session/真实模型摘要、预算/失败回退/审计 |
| BASH_SANDBOX_READ_ROOTS | Tool端可选JSON绝对路径数组，仅由operator配置必要运行时只读目录；不授予模型设置能力，不指定用户私有根 |

在已有明确授权测试连接配置下启动单worker（下面JSON路径指向仓库无凭证示例，也可复制到自己的新隔离目录调整）：

```bash
export REACTOR_SKILL_ROOT="$PWD/runtime/skills"
export REACTOR_SKILL_SCOPE_POLICY=session-copy
export REACTOR_MEMORY_CONFIG_FILE="$PWD/reactor-backend/examples-p4-memory.json"
export REACTOR_COMPACTION_CONFIG_FILE="$PWD/reactor-backend/examples-p4-compaction.json"
REACTOR_BACKEND_PORT=8101 reactor-backend/.venv/bin/python -m reactor_backend
```

macOS本地Bash用内核deny-default文件策略，仅会话写、明确运行时读，真实Python/YAML与原Skill Creator通过；非login shell，HOME/TMPDIR本会话，不继承服务token或模型key。Linux/Windows本地session-copy缺native边界明确失败要求原E2B，live未验证，不静默无隔离执行。原Java旧library路径保留对照/回滚行为。

完整回归命令（需允许本机loopback/MCP子进程；macOS外层工具沙箱不能嵌套加载sandbox-exec，应在有权限的本机测试终端执行）：

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests \
  --ignore=reactor-backend/tests/test_integration.py \
  --ignore=reactor-backend/tests/test_p2_integration.py \
  --ignore=reactor-backend/tests/test_p2_recovery.py \
  --ignore=reactor-backend/tests/test_p3_integration.py \
  --ignore=reactor-backend/tests/test_p3_closure_integration.py \
  --ignore=reactor-backend/tests/test_p4_integration.py \
  -q --junitxml=target/python-migration-p4-unit.xml
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p4 --business-db sqlite
reactor-backend/.venv/bin/python reactor-backend/tests/p4_skill_admin.py
```

最终141确定性通过/1环境门控skip/16warnings、50真实隔离集成、70原Java记忆测试、Java账本5+2+11帧通过。最后原子reload后10项Skill复验通过；31原Skill发现、package/import/reload/真实HTTP URL import、权限负例通过。最新root写入 `target/python-migration-p4/latest-integration.json`；harness每次新库/新目录，不接受生产连接。模型仅tests HTTP fixture，原Sandbox/脚本/三个MCP端点/数据库真实。原P3 Tool13项/UI2项基线失败未在本轮声称修复，未重跑全套原Tool/UI。

原React复现（两终端）：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p4 --business-db sqlite --serve
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /printed/fresh/reactor-p4-root
```

访问 `http://127.0.0.1:3000` 原命名页。`P4_MEMORY 用户需要跨轮记忆` → `P4_CONTINUE 续轮确认记忆` → 刷新/近期会话；新会话 `P4_MCP 三传输调用`；`P4_SKILL /absolute/project/reactor-backend/.venv/bin/python` 实际运行原 package 脚本产出213字节`.skill`。原UI未新增二进制`.skill`预览renderer，下载字节/CRC单独验证。详情/截图/模型fixture边界见[P4报告](../docs/python-migration/p4-report.md)。

共享Skill维护CLI只给OS operator，不作为Agent工具或未认证管理HTTP。如下命令仅使用明确授权的新库路径；不拿原共享库做测试：

```bash
reactor-backend/.venv/bin/python -m reactor_backend.skills.manage --root /absolute/new/authorized/skills --authorized-root import-package --file /absolute/test/package.skill
reactor-backend/.venv/bin/python -m reactor_backend.skills.manage --root /absolute/new/authorized/skills --authorized-root reload
reactor-backend/.venv/bin/python -m reactor_backend.skills.manage --root /absolute/new/authorized/skills --authorized-root preview --file /absolute/test/package.skill
```

还支持list/create/delete/import-url；冲突默认失败，仅operator显式`--replace`替换。包拒绝ZipSlip/重复条目/symlink和超限，reload原子更新registry；P5接原管理员认证HTTP。

原Java可选holographic/OpenViking当前实际为本地facts/buckets，Python保留实际行为、按可信owner隔离；配置endpoint不构成真实远端验证。真实语义provider/embedding/模型、远端MCP鉴权/E2B/其他平台、真实旧库与旧USER身份映射均单列U。完成P4后停止，下一入口P5；无push/PR/远端变更或生产切换。

## P5 启动、管理与图片配置

保留前述显式配置，且授权测试副本须先手动完成001/002/003加法表；无表时启动明确失败，不静默建表。当前shell已明确指定授权 `REACTOR_MYSQL_URL` 后：

```bash
reactor-backend/.venv/bin/python -m reactor_backend.maintenance admin-migrate --authorized-copy
reactor-backend/.venv/bin/python -m reactor_backend.maintenance featured-migrate --authorized-copy
# 仅第一次空 admin_user 表，可交互输入密码，不在命令行/文档放真实密码：
reactor-backend/.venv/bin/python -m reactor_backend.maintenance admin-init --authorized-copy --username YOUR_ADMIN --user-id YOUR_ADMIN_ID
```

已有原admin_user可直接登录；旧plaintext密码字段兼容。新opaque Cookie表只存digest，8h有效；禁用/过期/撤销即时失效。原配置页面在0003时显示登录弹窗；`validate-login`不签Cookie。原API64路由+精选5路由全部保留，生产默认Secure Cookie需HTTPS；本机隔离明确false。管理模型/API配置按下一次请求生效，Skill reload真实registry；单worker不变。

`REACTOR_IMAGE_CONFIG_FILE`为显式JSON文件，含 `base_url`、`api_key`，可选 `model`（默认gpt-image-2.5-flare）、`grok_model`、`grok_base_url`、`grok_api_key`。URL按Java为host基础地址，adapter拼接 `/v1/images/...`；原gateway在backend，不能以Tool服务替代。密钥由使用者显式注入文件，不提供假默认、不发现.env。真实供应商当前未验证。

原Tool须显式提供相同 `REACTOR_WORKSPACE_ROOT` 与内部认证配置；文件/文档按当前session及visitor配置隔离。访客自定义theme/template写自己的配置，共享配置只读；管理员Skill写共享库。GenUI及原docgen DOCX字体随OFL资源嵌入，文件约增加10MB；CPU/I/O渲染在工作线程，不需系统字体安装。

P5复验与页面预览：

```bash
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p5
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p5 --serve
# 使用上一命令打印的新隔离root：
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /absolute/new/reactor-p5-root
```

serve仅测试fixture上游，原Tool/数据库/文件实际运行；常规backend启动仍 `reactor-backend/.venv/bin/python -m reactor_backend`。详见[P5报告](../docs/python-migration/p5-report.md)。完成P5停止，不自动启动P6或切换默认部署。

PPTX复用原Office字体引用，需要阅读器可用CJK字体；本轮视觉QA只为LibreOffice子进程指定仓库font_assets目录。PDF/DOCX已内嵌字体，不应把PPTX阅读器缺字体静默宣称为全平台已验证。
