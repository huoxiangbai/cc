# P4 记忆、Skill 与 MCP 交付记录

日期：2026-10-04，Asia/Shanghai。用户授权的 P4 实现及隔离验收完成，停止阶段推进。用户明确采用 P0 A2：访客读共享 Skill，写/执行自己的会话副本；管理员维护共享库。该授权覆盖旧文档“待确认”。P5 管理 HTTP、完整 GenUI 等未实施，默认部署未切换。

## 实现与覆盖

路径均相对项目根。原 Java、React 工作台、33 张 MySQL 原表、Tool SQLite、文件 ID/关联保留。

| 能力 | 实现位置 | 本轮证据与边界 |
|---|---|---|
| F18/F27 工作记忆读写/重建 | `reactor-backend/reactor_backend/adapters/mysql.py`、`adapters/memory_store.py` | 原 READY 投影、reasoning/media/origin_key、跨轮顺序、主/子 scope；实际 Java 生成的旧投影导入新隔离 MySQL 后续轮；同时兼容 Java `sub:<id>` 和 P2 `subagent:<id>`，新写前者 |
| F27 上下文预算/压缩 | `memory/working.py`、`runtime/react.py` | system/schema 纳入估算；tool-use/result 原子分组；micro、session notes、真实模型摘要、drop fallback、审计和持久替换 |
| F28 curated/可选记忆 | `memory/service.py`、`memory/providers.py`、`adapters/memory_store.py` | 专用 `ai_agent_ltm_curated_entry`/`ai_agent_ltm_fork_execution`，user profile/curated；原可选 holographic/OpenViking 本地行为、显式 owner 隔离；未用普通聊天表替代长期记忆 |
| F28 flush/review/session_search | 同上 | 精确父 prompt/tools/history 快照，memory-only fork；实际 FULLTEXT 搜索、read/scroll、消息 ID/窗口、投影去重、访客/子 Agent 负例 |
| F29 Skill runtime/管理 | `skills/registry.py`、`skills/manage.py`、`runtime/local_tools.py` | 原 31 个 Skill 全发现；手册按需读取、Unicode/物理目录/虚拟名映射、占位符物化、真实原脚本、ZIP package/import/URL/reload；operator CLI 真实执行，管理 HTTP 留 P5 |
| F29 权限与执行 | `reactor-tool/reactor_tool/tool/bash_sandbox.py`、`bash_scope_guard.py` | 会话副本、dirfd/O_NOFOLLOW、ZipSlip/symlink/跨会话拒绝；macOS 内核限制真实通过，脚本产物真实产生；其他平台本地执行明确要求原 E2B |
| F30 MCP | `mcp/runtime.py`、`runtime/local_tools.py` | 官方 SDK SSE/STDIO/streamable_http，工具/资源分页发现、FQ→原 wire、ToolSearch/延迟 schema 激活、scope 连接 actor、超时/错误/shutdown；三种本机真实端点通过，外部服务 U |

## 兼容与失败行为

- 原 working-memory 消息/turn/compaction 表保留；事务保存原 turn、替换投影和压缩审计。原投影被标 INVALID 后仍可历史检索，origin 去重避免重复；不改原 Run/Task/Artifact ID 或 SSE 帧。
- 以原 Java 100k→75k、4k→3400 预算行为为基线。默认 micro 保留最近 5 条工具结果、更旧结果清理、保留结果上限 8k 字符；首 3/尾 8 条消息下限按完整组保护、尾部 token 范围受配置控制。孤立或重复工具结果明确拒绝。旧图片在模型边界转成多模态输入，reasoning 保留，审计图片省略。
- 摘要瞬态错误、空输出、超时采用本地证据摘要，再按完整组裁剪；context-too-long 最多 3 次缩小输入重试。认证/额度永久失败 `abort-unchanged`，恢复压缩前上下文并记录失败；取消传播。原 `[CONTEXT COMPACTION — REFERENCE ONLY]` 标记保留；不把失败当成功。
- curated 使用 Java UTF-16 字符预算：user 1375、curated 2200，包含条目分隔符。add/重复/replace/remove/歧义/批处理及 result 结构保持；锁访客行避免跨会话并发超额。身份来自可信 visitor，模型 `user` 参数不获得身份权限。
- provider 状态按 owner 显式分区；子 Agent 禁止父级长期记忆/历史检索/相关别名。flush 默认开启、至少 6 turn、去重；review 默认关闭、间隔 10 turn。fork 分别 5/6 步、45/90 秒，只允许记忆写入；禁止 Bash 等调用返回原失败 observation，shutdown 排空自己的任务。
- `session_search` 优先原 MySQL FULLTEXT；SQL 索引不可用时显式 `search_backend=scan`，不是伪检索。main scope 的 READY/INVALID 历史，跨访客拒绝，user 搜索排除当前会话，read 首 20/尾 10（超过 30 时）、scroll 最大 20、保留匹配消息 ID/原参数和 280 字符片段。
- MCP descriptor 支持原嵌套 stdio/baseUri/sseEndpoint/endpoint/headers；STDIO timeout 为秒、HTTP 为分钟。FQ 规范化/64 长度与原名映射、alwaysLoad/searchHint、ToolSearch select/关键词/最多 50 条保持。资源与 wire observation 保持，连接不跨 session/run/child 串用，关闭由创建连接的同一 actor 执行。

## 已批准的 Skill 权限落地

共享库不作为访客可写 cwd。每 session 在 `.reactor/skill-library` 保留副本与用户修改，禁用配置覆盖所有合法别名；模型不能注入内部 `_skill_library`。即使没有配置共享库，Python session-copy Bash 仍受限。原脚本不修改，原合法 package 工作流通过。

本机 macOS 使用原 Sandbox 的真实 Bash 路径并增加 `sandbox-exec` deny-default 文件策略：只允许当前会话写，系统/Python 等明确运行时路径只读；HOME/TMPDIR 均在本会话且逐层 O_NOFOLLOW 创建。使用非 login shell，不执行宿主初始化脚本；不继承模型 key/服务 token。`/etc/passwd`、其他 session 文件、共享 Skill 写入和 scratch symlink 负例真实拒绝。Linux/Windows 的 session-copy 本地模式缺相应原生边界时明确失败并要求原 E2B；没有静默无隔离执行。

管理员共享库维护由操作系统用户权限保护的本地 operator CLI 完成，必须指定绝对 root 和 `--authorized-root`，不对访客/Agent 开放。P5 才接管理员认证 HTTP。原 Java 使用的其他 library 路径保持原回滚行为，不能把它声称为本轮隔离边界。

调试中宽泛只读策略被自动批准审查拒绝，未执行。随后用新临时目录证明 literal-directory 权限不开放子文件，采用明确运行时目录和 literal 父目录的收窄策略，获准并验证通过。外层工具沙箱不能嵌套加载 macOS 内核策略；对应测试在获准的本机执行环境运行，不以跳过代替。

## 验收结果与可复现命令

命令从项目根执行。Python 3.11–3.13（本轮 3.12.13），锁定 `mcp==1.30.0`、PyYAML；依赖进入独立 `.venv`。集成需本机 mysqld 和 P0 已准备的 JDK/Maven 缓存。harness 每次新建临时 MySQL datadir/Unix socket、SQLite、文件目录；仅提取 CREATE，不读取 `.env` 或接受生产连接。完整启动必需配置见 [backend README](../../reactor-backend/README.md)。

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

| 验证 | 最终结果 | 证据 |
|---|---|---|
| Python 确定性/原真实 MCP 本机端点/原生 Bash | **141 passed / 1 skipped / 0 failed**，142 总数，16 warnings | [unit.xml](fixtures/p4-artifacts/unit.xml)；skip 是原环境门控重启用例，harness 覆盖恢复；requests 依赖版本等 warning 保留 |
| 真实隔离 HTTP/SSE、原 Tool、MySQL/SQLite、P1–P3 回归及 P4 | **50 passed / 0 skipped / 0 errors**，59.576 秒 | [integration.xml](fixtures/p4-artifacts/integration.xml)，root `reactor-p4-8zj4rb66` |
| 原 Java 记忆行为 | **70 JUnit passed**；Java 实际旧投影续轮通过 | [java-memory-tests.log](fixtures/p4-artifacts/java-memory-tests.log)、[java-memory.json](fixtures/p4-artifacts/java-memory.json) |
| 原 Java replay 实际 Python ledger | **5 + 2 + 11 帧 PASS** | 最新隔离 root 中 replay 日志，机器索引记录 |
| 最后原子 reload 改动后复验 | **10 Skill tests passed** | `pytest reactor-backend/tests/test_p4_skills.py -q`，含真实原生 Bash 正/负例 |
| CLI package/preview/reload/重复拒绝/真实 HTTP URL import | **PASS**，仅新 library root | [skill-admin.json](fixtures/p4-artifacts/skill-admin.json) |
| 原 Skill Creator package | 原 `package_skill.py` 实际产出 **213 字节**，ZIP CRC 正常、共享脚本未变 | [p4-created.skill](fixtures/p4-artifacts/p4-created.skill) |

首次外层沙箱复验出现 `sandbox_apply: Operation not permitted`，获批本机复验 10 项通过；不归为生产实现错误。旧 P3 原 Tool 13 个、原 UI 2 个基线失败没有在 P4 冒充修复或重新全测。完整机器清单与 SHA256 见 [p4-evidence.json](fixtures/p4-evidence.json)。

## 原工作台用户流程

两个终端，第二条使用第一条打印的新 isolation_root：

```bash
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p4 --business-db sqlite --serve
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /printed/fresh/reactor-p4-root
```

访问 `http://127.0.0.1:3000`，原 UI 命名 → 输入 `P4_MEMORY 用户需要跨轮记忆` → `P4_CONTINUE 续轮确认记忆` → 刷新 → 近期会话恢复。实际 curated 条目落专用 MySQL 表，后续 HTTP 模型请求含用户偏好，异访客不含该偏好。新会话 `P4_MCP 三传输调用` 经 ToolSearch 激活三个真实本机 MCP 工具，原 wire `original.echo!` 与资源内容进入工具账本。`P4_SKILL /absolute/project/reactor-backend/.venv/bin/python` 经原脚本打包并显示产物。

浏览器截图/步骤：[记忆](fixtures/p4-memory-ui.jpg)、[MCP](fixtures/p4-mcp-ui.jpg)、[Skill](fixtures/p4-skill-ui.jpg)、[机器步骤](fixtures/p4-browser-evidence.json)。模型上游为 tests 中的固定 HTTP fixture，记忆持久化、工具/脚本/端点/文件真实。截图早于最终 Bash 收窄，最终真实脚本再经 50 项 HTTP 集成和原生负例验收；`.skill` 二进制原 UI 暂无预览 renderer，字节/ZIP 校验独立验证，不宣称浏览器预览成功。

## 未验证与下一入口

1. 真实模型供应商/embedding、远端语义记忆 provider 单列 **U**。补审计确认原 Java holographic/OpenViking 当前是内存 facts/buckets，配置 endpoint 不等于已经调用远程服务；本轮迁移其真实本地行为，没有虚构远端成功。
2. 远端 MCP 认证/服务/代理网络、E2B live、Linux/Windows 执行环境 **U**。本机三种协议是真实测试端点，不是生产远端验收。
3. 真实旧 MySQL/多模态文件历史副本、旧 `USER` owner 到可信 visitor 的授权映射 **U**。本轮旧投影来自实际 Java 序列化并只导入新隔离库，不借模型 user 参数认领旧身份。
4. 管理员 HTTP/工作台管理全覆盖、完整 GenUI 新生成按原计划 **P5**；本轮仅交付 P4 operator Skill 管理，不开放未认证管理路由。

下一阶段入口是 [plan.md](plan.md) 的 P5，复用本轮记忆/MCP/Skill 服务并接管理员认证与原管理协议；须另行授权，本轮停止。回滚：停止 Python owner 后回原 Java 入口，保留原表/目录/默认部署，不清库、不同时对同 session 写入。没有 push、PR、远端修改、生产或 `.env` 操作；保护 workflow SHA256 未变。仅停止本轮测试进程，保留隔离日志/数据及证据。
