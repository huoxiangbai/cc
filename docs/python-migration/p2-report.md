# P2 实现与验收报告

2026-10-03，Asia/Shanghai。用户本轮明确授权 P2 及已确认 P0 owner/恢复修复。P2 实现与隔离验收完成；**停在 P2，没有实施 P3 或切换部署**。外部真实集成 U，不能据此声称全部 Reactor 后端迁移完成。

## 可运行里程碑与覆盖

| 里程碑 / 原能力 | 实现位置 | 验收事实 |
|---|---|---|
| M1，F04/05 模型目录/参数/重试 | [model.py](../../reactor-backend/reactor_backend/adapters/model.py)、[config.py](../../reactor-backend/reactor_backend/bootstrap/config.py)、MySQL enabled_model_metadata / 原 UI query-enabled | 首批 P1+模型 35 通过；最终参数、备用分类、重试耗尽、thinking、struct_parse、一次空流补救通过。真实供应商 U |
| M2，F02/20/21/22 PlanSolve/HITL | [react.py](../../reactor-backend/reactor_backend/runtime/react.py)、[local_tools.py](../../reactor-backend/reactor_backend/runtime/local_tools.py)、[interactions.py](../../reactor-backend/reactor_backend/adapters/interactions.py)、[control.py](../../reactor-backend/reactor_backend/transport/control.py) | PlanSolve 主工具白名单、首轮/强制计划、planner model/400步默认；批准/拒绝/编辑/提问/回答/取消/恢复，RunA/B 原 ID 关系；24 路 decide/claim、12 路真实 HTTP resume 无重复工具副作用 |
| M3，F15–19 Todo/子 Agent | [subagents.py](../../reactor-backend/reactor_backend/runtime/subagents.py)、[tasks.py](../../reactor-backend/reactor_backend/adapters/tasks.py)、[workspace.py](../../reactor-backend/reactor_backend/runtime/workspace.py) | 同步/后台真实模型+Tool；共享持久 Todo/依赖/owner，独立上下文、memory_scope、父工具 ID；TaskOutput 超时不 cancel，TaskStop、mailbox FIFO、指导下一步生效、resume_agent_id、全局许可、快完成与入协程前取消收口 |
| M4，F23/24 控制与流 | [runs.py](../../reactor-backend/reactor_backend/application/runs.py)、[control.py](../../reactor-backend/reactor_backend/runtime/control.py) | stop-before-bind / claim→admission gap；同访客跨 session 单 Run、异访客并发；128 帧 cursor、替换 observer/旧解绑竞争、实际 TCP 断线重连、park/pending/idle；根返回后后台排空和 stream_settle |
| M4，F31 会话能力 | 原 session_capability 差集表、owner、运行快照；ToolScope kind/refId 与子 Agent 继承 | MySQL 开关和双访客拒绝；Skill 明确目录清单、启用 MCP 配置元数据。完整 Skill/MCP 执行与动态发现归 P4，没有伪造运行能力 |
| 已确认 P0 修复 | [recovery.py](../../reactor-backend/reactor_backend/adapters/recovery.py)、MySQL 条件 finish / DB owner lock、所有 P2 控制/HITL边界 | 缺/错身份拒绝、期限检查、终态 CAS、claim 准入拒绝释放；旧无 owner 会话禁止首次认领；两次实际 SIGKILL/重启不重放工具，成功前后 claim reconciliation |

M2/M3 中间检查点为 53 确定性测试、20 TCP/MySQL 集成。M4 最终为 **59 确定性测试、25 集成测试**；集成含 P1 回归 10、P2 14、强杀重启 1。每批均有可运行入口，子 Agent/HITL/并发没有占位返回。

## 确定性与持久化契约

- 继续使用原 33 张表、MySQL 和原 SQLite/文件；无生产 DDL、无 schema 切换、无清库。status 数值与原字符串、llm_oberserve 拼写保持。`parent_tool_call_id/sub_agent_id` 和原 working-memory scope 实际写库。
- RunA 以 WAITING_INPUT=5 落库后发布卡片。answer/decide 原子 `PENDING→RESUME_PENDING` 并存唯一 resume ID；resume 原子 claim `RESUME_PENDING→RESUMING`，只胜者准入 RunB。重复请求观察该 RunB/终态。拒绝准入且无 RunB 才能释放 claim；未知 dispatch 不回收后重派。
- claim 后采用 locking read；MySQL REPEATABLE READ 下不能复用第一次 SELECT 的旧 status。ANSWERED/FAILED、Run SUCCESS/STOPPED、background terminal 和调用账本只允许从预期运行态收口，迟到回复不覆盖既有终态。
- 同批含 AskUserQuestion/ExitPlanMode 和其他工具时，全批给出失败 observation，不执行混杂副作用。批准时使用编辑后的计划；拒绝时仍留 plan mode 并带反馈。路径使用 anchored dirfd/O_NOFOLLOW，拒绝跨 session/绝对路径/.. /symlink/共享 Skill 写，独立读取状态校验编辑。
- Run token 在准入就存在；HTTP observer 不持有执行所有权。替换 observer 后旧流 finally 只能解绑自己的 queue。心跳不占 128 帧。follow 无活跃 registry 但持久 RUNNING 时 park 50×200ms，未绑定发送 follow_pending/retryMs=800；不存在/终态 follow_idle。均沿用 data-only 帧及 EOF。
- root SUCCESS 不表示后台已排空；先发 finished=false 的根结果，最后 stream_settle/finished=true。访客准入令牌直到全部后台收口才释放；取消子 Agent 不篡改已成功 root。取消发生在 child coroutine 第一条指令前，也会收口背景记录与原 Agent tool receipt。
- 一次空流 rescue 按每模型绑定计数。模型尝试的失败/成功账本与备用事件在 ContextVar scope 中记录，保留子 Agent 标签。生产 HTTP adapter 不使用固定结果。

## 可复现命令与结果

项目根目录执行；环境始终新建。启动与完整显式参数见 [backend README](../../reactor-backend/README.md)。

```bash
UV_CACHE_DIR=target/uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py reactor-backend/tests/test_p2_models.py reactor-backend/tests/test_p2_runtime.py -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p2
UV_CACHE_DIR=target/uv-cache uv build --project reactor-backend --out-dir target/python-migration-p2/dist --offline
```

结果：59 passed；25 passed；原 Java 对实际 Python 写入账本通用 5 帧、GenUI 2 帧、rich/产物 11 帧对照通过（仅归一动态 taskId）；wheel/sdist 构建通过，包含 prompt/schema。没有把原工具全部服务或供应商模型写成实测通过。

最终集成 root：`/var/folders/15/rh2lsj816qn5q7p7djht06bc0000gn/T/reactor-p1-8dwz_4qh`。`integration.xml`、SQL事实、实际模型/Tool/后端日志、restart/evidence.json 保留；机器摘要见 [p2-evidence.json](fixtures/p2-evidence.json)。

原 UI 六个文件的 26 项测试，在新建 UI 副本执行：

```bash
npm test -- src/utils/planApprovalRestore.test.ts src/utils/askUserRestore.test.ts src/components/ChatView/useConversationStream.test.ts src/utils/querySSE.test.ts src/utils/chat/agentRuntimeProjector.test.ts src/components/Dialogue/tools/askUserToolParse.test.ts
```

不是全 UI 测试结果。首批命令中两个路径未匹配，实际只执行 4 文件/18 项；随后用真实路径补齐 6 文件/26 项，记录在此。

## 原工作台真实用户流程

UI 源码无改动。复制到隔离 root，排除所有 `.env*`，原 Tool 文件/SQLite 真执行；模型上游为独立固定 HTTP fixture。浏览器通过实际界面操作，并从隔离 MySQL 核实 Run、决策、后台与文件 SHA-256。[UI事实](fixtures/p2-ui/evidence.json)。

1. `session-1791012905281-2527`：ReAct 提问暂停→刷新→近期会话恢复待答卡→选择“分析”→提交→原 Tool 生成回答报告并预览。Run ID 6=WAITING_INPUT、7=SUCCESS；源/恢复 request 保留，question=ANSWERED。[恢复截图](fixtures/p2-ui/question-restored.jpg)、[交付截图](fixtures/p2-ui/question-result.jpg)。
2. `session-1791013006740-1858`：PlanExecute→刷新恢复计划→拒绝并反馈“加入来源核实与用户确认”→修订计划→编辑正文→执行。Run 8/9=WAITING_INPUT、10=SUCCESS，两次审批均 ANSWERED；`.reactor/plan.md` 和 `计划报告.md` SHA-256 相同，实际产物是用户编辑内容。[恢复](fixtures/p2-ui/plan-restored.jpg)、[修订](fixtures/p2-ui/plan-revised.jpg)、[编辑交付](fixtures/p2-ui/plan-edited-result.jpg)。
3. `session-1791013349877-5728`：后台 Agent→根返回→刷新→近期恢复→原子 Agent 面板显示 Completed、general-purpose、1 tools、background；真实 worker-browserbackground.md 32 bytes。实际 TCP 集成另验证后台仍活跃时断线/cursor 重连与 stream_settle；浏览器本例恢复的是后台完成历史，不虚称刷新时仍在运行。[后台面板](fixtures/p2-ui/background-detail.jpg)。

浏览器环境 root `reactor-p1-5tzg79ec` 的模型目录请求在补接口前返回 404；后续新增原 query-enabled DTO 读接口并用真实 MySQL 集成验收。精选/管理 CRUD 等 P5 入口 404 仍是明确范围缺口，没伪造成功。页面原有嵌套 button 警告保留，无 UI 行为改写。初始副本的依赖字体曾被 Vite fs allowlist 拒绝；新 ui_copy.py 仅向隔离开发服务开放依赖目录，最后新 root reactor-p1-92wpj3c3 实测启动命名页和字体 HTTP200。未改原 UI 源码。

## 恢复、失败记录与限制

恢复必须显式 `REACTOR_RECOVER_EXCLUSIVE=true`，确认旧 Java/Python owner 已退出；Python 同 DB GET_LOCK 和 workspace 锁在 sweep 前取得。两次真正 kill/restart 使用第二个全新测试 DB，已提交 Todo 副作用保持 1 次、重启新增模型请求 0；孤儿 run FAILED/PROCESS_RESTART、运行中 LLM/tool failed、background failed，无 RunB claim FAILED，已完成 RunB claim ANSWERED。不会自动重放工具副作用。另在确定性模型阻塞点实际杀掉“根已返回、后台仍运行”的进程：根Run保持SUCCESS，child调用和Agent receipt收口failed，未生成后台工具文件；会话失败计数与账本一致。GET_LOCK 不替代跨主机 lease/fencing，也不能证明旧 Java 已退出。

保留的失败：初次沙箱内 mysqld initialize SIGSEGV（新本机隔离执行通过）；曾有执行权限复核因工具额度暂时不可用，用户“继续”后恢复。最后新增 12 路 TCP resume 首次为 24 通过/1 失败（root reactor-p1-prvaqk48）：DB 只派发一 RunB，但失败 claim 用旧 snapshot 误报已结束；修复后最终 25 通过。原日志没有删除。

未验证：真实模型供应商/跨供应商网关与备用、真实旧 MySQL/SQLite/文件副本、Nginx/HTTPS/Cookie生产配置、跨主机 fencing、原 Java 活跃部署恢复、外部搜索/向量/RAG/E2B/Sandbox、完整 MCP 三传输与 Skill 脚本。旧数据 owner/ID 映射须用授权副本验证，不能凭合成新库声称完成。

已确认 P0 修复在 **P2 已接入接口** 落实。管理员统一认证/新会话表、Tool 私有 file/KB/image ACL/服务token、共享 Skill import 权限随 P3/P5 接口迁移落实；对应路由本阶段没接入，不宣称整个 A2 完成。H2 依赖和原 Java 保留，部署使用仍 U；不擅自删除。

无 push/PR/remote 更改，无 `.env` 覆盖、生产连接或 DROP；保护原工作流 SHA-256 见证据索引。回滚为停止独立 Python backend 后使用原 Java 入口，不清数据，不同时让两者写同 session。下一入口仅 [plan.md](plan.md) 的 P3，需新阶段授权；本轮到此停止。
