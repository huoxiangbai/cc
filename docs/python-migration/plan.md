# 分阶段迁移计划与验收

> 2026-10-04 P5 当前检查点：交付/图片/全部管理接口已实现，159 确定性通过、46 真实隔离集成与 Java 5+2+11 帧回放通过；管理员登录、原工作台交互和中文导出视觉通过，P5完成后停止。原 UI 434 通过/2 个已知基线失败保留。真实图片/模型供应商与真实旧数据仍 U。已批准访客 theme/template 独立配置、共享只读；见 [P5报告](p5-report.md)。完成 P5 后停止，不启动 P6。


> 2026-10-04 当前检查点：P4 实现及隔离验收完成，停止。用户已批准访客 Skill 会话副本/管理员共享库方案；141 确定性测试通过（1 环境门控 skip）、50 真实隔离集成、70 原 Java 记忆测试通过。macOS 原生文件边界已验证，外部记忆 provider/MCP/E2B 与真实旧数据仍 U；管理 HTTP 留 P5。见 [P4报告](p4-report.md) 和 [progress.md](progress.md)。下文历史“未启动/待确认”以本条为准。

> 2026-10-03 P3收尾更新：用户已授权独立SQLite替代H2业务源及可信身份/持久owner/内部认证方案。下文原审计的待确认记录为历史；最新实现、验收与边界见 [P3收尾报告](p3-closure-report.md)。Reactor MySQL账本及Tool SQLite保持，Java/H2保留回滚；P4未启动。

日期：2026-10-03（Asia/Shanghai）；架构已确认，本轮P1实现与隔离验收完成，真实供应商/旧数据副本U；完成P1后停止。各阶段以“能完成真实用户流程”的成果交付，未通过门槛不得切换默认生产入口。覆盖表对应 [inventory.md](inventory.md) F01–F42，契约见 [contracts.md](contracts.md)。

## 1. 授权与工作区

初始 `git status --short`：仅 ` M .github/workflows/ocr-review.yml`，分支 master，commit cb6e389a。本次保留该文件及业务代码；新增 docs/python-migration 下文档。仓库原先忽略整个docs目录，因此只增加该子目录的Git忽略例外，其他docs继续忽略。测试只在本地生成 ignored target 报告和 /private/tmp 日志，不执行外部服务或真实数据库初始化。未创建 commit/PR，也未修改默认 Docker/启动路径。

审计时用户要求“输出方案后等待我确认迁移范围和架构，再开始实施”。之后已明确接受架构和处理方向、授权开始P0/P1，确认旧Workflow/定时任务无需恢复，H2待核实。用户随后暂停实施，要求本地保存和GitHub登录；这两项已完成。用户前轮恢复并完成准备/P0；前轮完成P1；本轮明确授权P2与已确认P0修复，成果与缺口见[p2-report.md](p2-report.md)。P2完成后停止，未进入P3；最新状态见progress.md。

## 2. 阶段顺序、可运行成果与门槛

| 阶段 | 工作与覆盖 | 可运行成果 | 必须通过的验收 | 风险与回滚 |
| --- | --- | --- | --- | --- |
| P0 基线冻结/验证资产 | 对全部路由/DTO、SSE/raw JSON、工具动态 schema、SQL repository、文件 ID 建立 fixture；审查 A1–A3；保留原 UI 测试 | 隔离旧 Java baseline runner + 行为对照 harness、空凭证也可运行确定性测试 | 所有当前 Java HTTP 路由登记；全部工厂可暴露工具 schema/返回样本；null/default/error/time/json/ID 确认；live DDL 仅授权副本比对 | 原测试配置会跳过、Mockito agent 限制、live schema lag；不改原业务以让 baseline 通过；fixture 不含密钥/用户数据 |
| P1 真实纵向链路 | F01/03/23/25/26/36/38 的最小完整路径；真实模型+WebFetch 或现有无凭证 docread/dataprep 工具 | Python backend 独立端口/配置；原 React 请求→Agent工具循环→SSE→MySQL账本/文件→刷新历史 | B01/B02/B07/B09/B11 基础用例；同一次真实运行可查 LLM/tool/artifact；旧会话可读；原 UI 不重做 | 一个成功聊天不算迁移完成；外部模型无凭证时实现真实 adapter+隔离测试，标 U，本轮停止；下一阶段需新授权；停 Python 恢复原 Java 路由即可 |
| P2 完整编排与运行控制 | F02/04/05/15–24/31：PlanSolve、模型回退、任务/Todo/mailbox、子 Agent、HITL/claim/stop/follow、并发 | 原 React 的计划审批/提问→continuation、后台子 Agent、断线 follow、多访客 | B02–B06/B11；并发提交 claim 只派发一次；同访客单 Run；父子终态/后台排空；取消与迟到回写竞争 | 不让断线触发 task cancel，不开多 worker；DB CAS 不能以 Lock 替代；回滚前 drain/resume records 兼容旧 Java |
| P3 研究/RAG/数据/代码能力 | F06–14/41、数据源方言、搜索与RAG全部复用桥接；三社媒和 Skill/MCP 渠道集成 | 前端研究来源、知识库管理/问答、NL2SQL取数、真实 CodeAct+沙箱+报告 | B02/B07/B09/B12；每渠道记录 credentials/fixtures/live；SQL执行与图表一致；权限/沙箱错误不返回假成功 | DDG限流/平台凭证、ES/Qdrant/embedding/OCR、E2B；保持原 tool 服务和 storage 不变，按 adapter 切回 Java |
| P4 记忆/上下文/Skill/MCP | F18/27–30：跨 turn working memory、compaction、curated/语义 provider、flush/review、Skill package、三 MCP 传输 | 重启后旧上下文读取；memory/session_search；实际 Skill脚本和MCP远端工具 | B07/B08/B11/B12；tool pair 不断裂；provider scope 隔离、压缩失败回退；延迟 schema 激活与 FQ wire 对照 | 实现/本机隔离验收与外部 live 分列；真实 provider/MCP 缺凭证标 U，不能宣称生产全量验收；A2会话副本已批准，rollback原表/目录 |
| P5 交付/工作台/管理全覆盖 | F32–40：GenUI/tree/patch/canvas/3D/export、全部doc工具、图片编辑fallback/历史、模型/API/MCP/SubAgent/Skill/admin/featured | 原全部 workspace 页面、HTTP-only管理API、GenUI可交互/可导出、旧文件可用 | B01/B09/B10/B11；所有管理route覆盖；PDF/DOCX/PPTX/XLSX真实内容与视觉检查；mask/image真实integration | 不把Java图片gateway或GenUI exporter漏掉；协议/鉴权改变需决策；保持文件旧路径和元数据格式 |
| P6 数据兼容与全行为对照 | 全F01–F42；真实匿名化旧数据副本、历史回放/续轮；失败/崩溃/负例/并发矩阵 | Python staging 一套完全运行、全部用户流程回归报告与覆盖表证据 | B01–B12 全覆盖，无空实现/假结果；旧DB/文件验证与回滚演练；待决A1–A3关闭 | 无双写争用，不在生产自动回放副作用；坏数据/缺服务要分类，不能静默跳过 |
| P7 正式无 JVM 启动/部署与切换准备 | F42；Python镜像/启动/config/docs、Compose backend替换、代理路径保持、env兼容、回滚 | 新正式入口不含 java/jar/Maven；旧Java镜像/模块仍可选用于回滚 | 原React接Python完成全部流程；所有runtime任务drain；fresh隔离库与升级副本都通过；JVM-free镜像/命令检查 | 生产切换另需明确环境授权；清理Java模块只在验收后另定计划；不能提前删除证明“迁移完成” |

P1 为第一条真实纵向链路，不承诺“外部没有凭证即可真实模型验证”；缺凭证只限制集成证据，不能限制生产 adapter 的实现。P3/P4 的依赖集成可以在已有接口边界内逐项推进，但未满足前序 Run/HITL 安全门槛不得启用正式路径。

## 3. 行为验收矩阵

| 编号 | 用例与比较对象 | 源码测试/取证依据 | 隔离验证与真实集成 |
| --- | --- | --- | --- |
| B01 HTTP/DTO/errors | 全方法/path/query/body/form/default/null/pagination/binary；旧错误码、400/500、unknown route | Controllers/VO/API DTO；[DataAgentController.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L39)、[AgentGenUiExportController.java:27](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentGenUiExportController.java#L27)；现UI services | 本地旧/新同输入比较，动态ID/时间归一；隔离真实HTTP；不得直接用FastAPI默认422代替Java |
| B02 工具/模型循环 | 多轮工具、parallel dispatch_index、structuredOutput/observation、bad JSON、tool timeout、retry/fallback、首chunk/空流/取消 | [LlmRequestRetryTest.java:15](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/LlmRequestRetryTest.java#L15)、[LlmModelFallbackTest.java:12](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/LlmModelFallbackTest.java#L12)、ToolLlmObservationRuntimeTest、ExecutionLedgerBoundaryTest、LLM 代码 | 固定模型/工具替身只用于确定性；真实provider+至少一个真实工具链路另验，不用硬编码生产结果 |
| B03 HITL/幂等 | RunA WAITING_INPUT、tool yield sole、approve/reject/edit/answer/cancel、RunB关联；并发重复decision/resume | [PlanModeToolsTest.java:16](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/planmode/PlanModeToolsTest.java#L16)、[PlanApprovalResumeApplicationServiceTest.java:13](../../Reactor-agent-case/src/test/java/org/wwz/ai/test/application/agent/planmode/PlanApprovalResumeApplicationServiceTest.java#L13)、UserQuestionYield/Resume、两个mapper CAS | MySQL隔离库并发CAS+拒绝准入返还claim；模拟断线前后、claim后crash；实际UI刷新与继续 |
| B04 reconnect/follow | POST不重发、disconnect不stop、128帧cursor、旧abort race、pending park/idle、root result与EOF | [ActiveAgentRunRegistryTest.java:13](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/ActiveAgentRunRegistryTest.java#L13)、[BackgroundStreamSettleTest.java:26](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/stream/BackgroundStreamSettleTest.java#L26)、ui querySSE/useConversationStream tests | 实际TCP中断/代理EOF/慢读；Java-Python只比较必要事件顺序，不强制并行工具全序一致 |
| B05 stop/background | stop-before-bind、root返回而child running、单task stop、全run stop、终态后迟到成功 | [BackgroundStreamSettleTest.java:26](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/stream/BackgroundStreamSettleTest.java#L26)、[BackgroundAgentTaskTest.java:18](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/subagent/BackgroundAgentTaskTest.java#L18)、TaskOutput/Stop、RuntimeBackgroundTaskRegistry | 后台任务真实等待/查/取消，process restart后孤儿failed；不宣称重启自动续执行 |
| B06 concurrency/isolation | 同visitor多session拒绝、不同visitor可并发；subagent semaphore/嵌套、mailbox、child tools/memory | [SubAgentConcurrencyHardeningTest.java:19](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/subagent/SubAgentConcurrencyHardeningTest.java#L19)、[SubAgentResumeHardeningTest.java:17](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/subagent/SubAgentResumeHardeningTest.java#L17)、[SendMessageMailboxTest.java:15](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/tasklist/SendMessageMailboxTest.java#L15)、SubAgentLtmIsolationTest | 重复create/resume/stop竞争，toolSource/event projector不串；多worker启动配置拒绝或禁用 |
| B07 DB历史/产物 | 原session/run/tool/LLM/artifact数据→同replay语义/模式/缺失文件reason；新写旧Java也可读 | [ConversationHistoryControllerTest.java:34](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/ConversationHistoryControllerTest.java#L34)、ReplayProjectorTest、ToolArtifactBindingRuntimeTest、mapper/schema | 真实授权副本比较行数/PK/FK语义/unique/NULL/JSON/时间/decimal；不拿空库通过当旧库兼容 |
| B08 记忆/压缩 | 跨turn hydrate、user/session/subagent scope、micro/session/LLM/drop、失败保留、flush/review与语义provider | WorkingMemoryCompactorTest、MemoryContextFenceTest、LtmForkParityTest、SessionContextCompactionOutcomeTest | 配对tool-use/result与上下文窗口固定fixture；真实模型summary/外部memory单列V/U |
| B09 GenUI/files/artifacts | UI tree/patch + 原树历史；canvas相对资源/3D；multipart/preview/download/archive；真实多格式/图片 | [GenUiSchemaTest.java:10](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/canvas/GenUiSchemaTest.java#L10)、[GenUiExportServiceTest.java:11](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/canvas/GenUiExportServiceTest.java#L11)、CanvasPublishToolTest、Python file tests、UI genui/file tests | HTTP头与字节内容、历史URL、unicode路径、MIME、PDF/DOCX/PPTX/XLSX内容/视觉；浏览器3D和交互 |
| B10 管理/config | 全CRUD/query/test/reload/启禁用、重复modelId、API/MCP/Skill/SubAgent、featured列表详情公开读取 | SubAgentDefinitionAdminApplicationServiceTest、FeaturedConversation*Test、LlmModelCatalogDuplicateIdTest、UI model/admin tests | 不遗漏UI未引用API；catalog invalidate后下一轮生效，feature online/offline复现 |
| B11 identity/path/security | 旧Cookie摘要、命名、归属、CORS/contextpath、访客/管理员拒绝、路径穿越/绝对路径/symlink/共享Skill | [VisitorIdentityFilterTest.java:21](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/VisitorIdentityFilterTest.java#L21)、[ConversationSessionOwnershipApplicationServiceTest.java:15](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/ConversationSessionOwnershipApplicationServiceTest.java#L15)、Workspace*Test、Python sandbox permissions tests | A2范围决策先关闭；双访客读/停/指导他人Run、下载/KB、管理员未认证负例；sandbox逃逸实测 |
| B12 实际外部集成 | 搜索渠道、MRAG/OCR/vector、业务SQL、CodeAct/E2B、MCP三传输、外部记忆、图片供应商 | reactor-tool tests、cloud vector/MCP/DeepSearch/Social/Image tests | 仅记脱敏环境与配置键、版本、样本输出和失败；每能力保留U直至该真实链路证据存在 |

不比较模型自然语言逐字一致；比较工具名称/参数/schema、必需事件偏序、状态/claim/取消、账本/产物关联、权限与真实交付质量。冻结模型 fixture 的工具循环可逐字段对照；动态UUID/时间应保持引用关系后归一化，不能删除ID字段遮住关联错误。

## 4. 数据验证、迁移和回滚操作方案

本次不执行以下操作；实施只在明确授权的测试数据副本上开始：

1. 只读取副本 DDL、schema版本、索引、collation、时区、存储路径清单，不将内容/密钥写测试日志；对比 [schema.sql:1](../../Reactor-agent-app/src/main/resources/db/schema.sql#L1) 与 mapper。旧 `DROP TABLE` 脚本不作为 Python 迁移步骤。
2. 备份 MySQL、两个SQLite与文件volume，保持同一静止窗口/一致性点；SQLite 用backup机制，不能活跃写入时只copy主文件忽略WAL。记录备份版本/校验和，检验恢复。
3. staging完整复制旧schema、数据、文件权限和root mount；工具 SQLite和vector collection保持原实现管理。文件绝对路径如果因挂载必须变化，使用明确root mapping，留旧地址；测试新旧MD5相对路径算法。
4. 初期零DDL迁移，只新Python repository mappings。必要加列/索引需versioned SQL、dry-run、backfill/checkpoint/row验证，检查旧Java读取新写入字段。无用户确认不得运行不可逆变更。
5. 用旧Java/newPython分别只读同一snapshot回放；写入/模型工具比较使用分开的两个副本，**不能**让两者争写同session或重放同真实外部副作用。验证生成的新行也可由旧Java回放/续轮。
6. 切换时先停止新run准入，drain主/后台/flush，核对开放审批与问题。不得在ActiveRun或RESUMING期间直接路由到另一个进程，进程内状态无法跨语言移交。保留RESUME_PENDING可由兼容claim消费。
7. 切换代理/backend镜像与配置，保留Tool/Sandbox/DB/volume地址；按B01/B04/B07/B09/B11运行canary。生产发布须用户另行明确环境授权。
8. 回滚：停止Python准入并drain→记录未完run/claim→切回原Java镜像/代理/配置→核对新行可读→相同canary。默认零DDL时无需清库或数据还原；有加法DDL通常保留。如果新写入语义旧Java不兼容，必须先解决兼容再切换，不能仅恢复旧snapshot而丢用户新数据。

## 5. 外部验证缺口与完成门槛

当前 U：所有实际模型、搜索与社媒/渠道凭证、E2B、Qdrant/ES/embedding/VLM/MinerU/OCR、OSS、MCP三传输、OpenViking/holographic、图片生成供应商、业务数据源、真实MySQL/SQLite旧历史/文件、原React浏览器流程。缺哪些配置键从 `.env_template`/配置定义提取，永不输出真实值；有配置不等于可用或已验证。

正式完成要求：F01–F42每行存在目标实现位置+Bxx证据；所有范围接口/工具/SSE/持久化等价；原工作台用户流程通过；历史与文件升级/回滚证据齐全；无JVM正式入口；配置/部署/启动/回滚说明更新；无TODO、空实现、假结果或未声明降级。任何范围内真实集成仍U时不能宣称全部迁移完成，可以报告“实现完成、该集成验收待验证”。

## 本次审计执行记录

环境：JDK21.0.12、Maven3.9.11可用，使用 `-o` 离线本地缓存；默认python3=3.10，无reactor-tool/.venv、FastAPI/SQLAlchemy/httpx、pytest；ui/node_modules不存在，因此未安装重型依赖或执行UI测试。Python4个配置测试只需stdlib，可运行，但不证明>=3.11生产环境合格。

E1：`mvn -o -pl Reactor-agent-domain -am test -DskipTests=false -Dtest=ActiveAgentRunRegistryTest,LlmRequestRetryTest,LlmModelFallbackTest,SendMessageMailboxTest -Dsurefire.failIfNoSpecifiedTests=false`，24测试，0失败/0错误。

E2：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_sandbox_backend_config.py -v`（cwd reactor-tool），4测试通过；仅E2B proxy优先级/显式off/空值/fallback，不代表E2B执行。

E3：离线app reactor联合选择 `BackgroundStreamSettleTest,AgentResponseHandlerReplayContractTest,SseEmitterAgentSessionStreamTest,ConversationHistoryControllerTest,VisitorIdentityFilterTest,ConversationSessionOwnershipApplicationServiceTest,PlanApprovalResumeApplicationServiceTest,PlanModeToolsTest,GenUiSchemaTest,GenUiExportServiceTest,DeferredMcpCatalogTest,SubAgentConcurrencyHardeningTest,SubAgentResumeHardeningTest`。domain额外21通过；app 35测试中17通过、18错误；错误均为Mockito/ByteBuddy无法self-attach，并非断言失败；case tests被父Surefire固定skipTests跳过（即使传命令属性）。不改pom绕过此问题。

E4：针对18个Mockito环境错误，尝试通过命令行 `-DargLine=-javaagent:<本机已缓存mockito-core.jar>` 预载agent重跑；复跑18测试全部通过（0失败/0错误，BUILD SUCCESS）。本次总计80个不同Java隔离测试通过（E1 24 + E3 domain21 + E3 app17 + E4 18），另有4个Python配置测试通过。最终报告保留E3初次失败记录，不抹掉环境缺口。case的独立恢复测试仍未验证。

报告位置：各Maven模块 ignored `target/surefire-reports/TEST-*.xml`；临时日志 `/private/tmp/reactor-python-migration-baseline.log`、`/private/tmp/reactor-python-migration-identity.log`，不提交日志。测试均为选定的隔离单测，没有启动Spring完整应用、调用外部模型或访问生产DB。静态Controller/工具/schema索引以及文档引用检查另记progress。

### 最终选定 Java 测试报告汇总

仅下列16个测试类，最新对应Surefire XML复核共80测试通过；不是全套测试结果。E3环境错误已在E4复跑通过，case模块的审批resume测试仍被跳过。

| 测试类 | tests | failures / errors / skipped |
| --- | --- | --- |
| [ActiveAgentRunRegistryTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/ActiveAgentRunRegistryTest.java#L1) | 6 | 0 / 0 / 0 |
| [LlmRequestRetryTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/LlmRequestRetryTest.java#L1) | 12 | 0 / 0 / 0 |
| [LlmModelFallbackTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/LlmModelFallbackTest.java#L1) | 3 | 0 / 0 / 0 |
| [SendMessageMailboxTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/tasklist/SendMessageMailboxTest.java#L1) | 3 | 0 / 0 / 0 |
| [DeferredMcpCatalogTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/DeferredMcpCatalogTest.java#L1) | 2 | 0 / 0 / 0 |
| [GenUiExportServiceTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/canvas/GenUiExportServiceTest.java#L1) | 2 | 0 / 0 / 0 |
| [GenUiSchemaTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/canvas/GenUiSchemaTest.java#L1) | 3 | 0 / 0 / 0 |
| [PlanModeToolsTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/planmode/PlanModeToolsTest.java#L1) | 10 | 0 / 0 / 0 |
| [SubAgentConcurrencyHardeningTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/subagent/SubAgentConcurrencyHardeningTest.java#L1) | 2 | 0 / 0 / 0 |
| [SubAgentResumeHardeningTest.java:1](../../Reactor-agent-domain/src/test/java/org/wwz/ai/test/domain/subagent/SubAgentResumeHardeningTest.java#L1) | 2 | 0 / 0 / 0 |
| [VisitorIdentityFilterTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/VisitorIdentityFilterTest.java#L1) | 7 | 0 / 0 / 0 |
| [ConversationHistoryControllerTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/ConversationHistoryControllerTest.java#L1) | 7 | 0 / 0 / 0 |
| [ConversationSessionOwnershipApplicationServiceTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/ConversationSessionOwnershipApplicationServiceTest.java#L1) | 4 | 0 / 0 / 0 |
| [SseEmitterAgentSessionStreamTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/SseEmitterAgentSessionStreamTest.java#L1) | 2 | 0 / 0 / 0 |
| [BackgroundStreamSettleTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/stream/BackgroundStreamSettleTest.java#L1) | 9 | 0 / 0 / 0 |
| [AgentResponseHandlerReplayContractTest.java:1](../../Reactor-agent-app/src/test/java/org/wwz/ai/test/domain/AgentResponseHandlerReplayContractTest.java#L1) | 6 | 0 / 0 / 0 |

## P0实施验收（2026-10-02）

已完成本地迁移分支/快照/环境、离线Java行为runner、可重复fixture捕获与差异对照。102个隔离JUnit及9个Python harness测试通过；原审批resume测试直接JUnitCore执行，不再因Surefire跳过。108路由、工具schema、HTTP/SSE、历史/GenUI/HITL与原SQL取证见[p0-report.md](p0-report.md)。初次失败与排除的部署profile测试仍记录为U。

H2实际支持/使用入口已查清，但外部部署是否启用及P7无JVM兼容仍待决，见[h2-evidence.md](h2-evidence.md)。A2/A3给出明确协议/状态修复方案和负例，见[p0-decisions.md](p0-decisions.md)，未实施协议改变。旧MySQL/SQLite/files/history与实际UI/代理/外部集成缺口保留，副本命令见[copy-validation.md](copy-validation.md)。

P0基线资产门槛通过；全部真实集成门槛未通过，不能据此正式切换。后续P1使用独立Python入口、同形capture比较；不得自动跨阶段或改原默认入口。

## P1 检查点

2026-10-03：P0门槛复核通过，新增独立reactor-backend；固定模型多轮/失败路径、原Tool真实文件处理、MySQL账本与跨轮必要上下文、data-only SSE/断线follow、原React刷新历史通过。历史通用、GenUI及专用rich读侧与原Java对照，生成/完整控制未进入P2/P5。启动、命令、逐项覆盖、未验证项见[p1-report.md](p1-report.md)。真实供应商和真实旧数据副本缺失不转demo，也不授权自动跨阶段。下一入口仍为上表P2，A2/A3外部协议按既有具体方案处理。


## P2 检查点（2026-10-03，完成后停止）

用户本轮已授权P2及已确认P0权限/恢复修复，替代历史待决文字在P2范围的约束。M1模型adapter→M2持久HITL/PlanSolve→M3Todo/真实子Agent/隔离→M4并发/TCP/重启/原React恢复依次交付，结果和限制详见[P2报告](p2-report.md)。59确定性、25集成（P1回归10+P2 14+重启1）、原Java5+2+11帧和UI6文件26项通过。

P2入口：`reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p2` 自动新建测试环境；浏览器`--phase p2 --serve`配合`tests/ui_copy.py`排除dotenv的原工作台副本。真实供应商/旧数据副本U、HTTPS/外部服务U，不等于正式切换门槛通过。既有workflow修改和Java回滚入口保留，无远端或生产操作。

P2当前完成并停止；下一授权入口仅上表P3（原工具、研究/数据/Sandbox及相关安全边界）。管理员统一认证和Tool私有资源ACL按接口接入阶段P3/P5推进，完整Skill/MCP/上下文压缩P4，H2部署/P7无JVM决策继续保留；没有借本轮跨阶段实现这些模块。

## P3 本轮检查点（2026-10-03）

本轮已获P3授权，增量成果见[p3-report.md](p3-report.md)，上文P2“未进入P3”为历史状态。101 backend、36新库TCP集成、Java5+2+11帧及3 SQL DTO对照通过；实际CodeAct、NL2SQL执行、auto_analysis/get_data、MRAG建库/历史与原前端入口落地。原Tool选定127测试中114通过/13失败，不把平台/旧断言等失败删掉。

已批准并实现沙箱三开关透传、既有静态校验和runtime open/io.open接线。Tool私有file/KB ACL外部拒绝/网关与H2过渡具体确认未收到；正式启用门不标完成，H2原Java保留。外部凭证/service矩阵逐项U；完整Skill/MCP渠道依赖P4，不称全部原生内置。本轮不启动P4/P5。完成当前P3确认门及外部验收后，下一阶段入口仍为P4，需另行授权。


## 最新阶段入口（P3收尾授权）

P3新增限定范围：独立SQLite替代H2业务源、私有Tool网关/持久owner/服务认证及隔离加法迁移。以收尾报告当前检查点为准，前文ACL/H2待确认已被本次批准覆盖。P3代码与隔离验收可闭合；逐服务外部U转为正式切换前独立验收项，不阻止本轮代码收尾。

下一阶段仅为原P4：完整Skill Runtime、MCP SSE/STDIO/Streamable HTTP、ToolSearch/延迟加载及其原入口、权限/恢复契约。复用P0索引和P1–P3证据，不重新从零审计；新P0协议缺口按证据给具体方案。必须收到新P4授权后开始，本轮停止，不实施P4或P5管理端。

## P4 完成检查点与下一入口（2026-10-04）

P4 用户授权及 A2 会话副本批准已执行。M1 记忆/预算/压缩/检索，M2 Skill/MCP/权限，M3 141确定性+50真实隔离+70Java对照，M4 原React跨轮/刷新、MCP及脚本产物闭合。当前完成含真实adapter及本机测试端点，不等于缺凭证的生产服务已验收；远端provider/MCP/E2B/真实旧数据按用户通用约束单列U，不因缺凭证留下空实现。详见 [P4报告](p4-report.md)。

下一入口为本表 P5：复用已实现记忆/Skill/MCP服务，接原管理员认证和配置/管理HTTP、工作台及完整GenUI。P4 Skill维护当前为OS权限保护operator CLI，不作为未认证HTTP暴露。旧Workflow/定时任务不恢复，原Java/H2继续保留。不开始P5，不自动push/PR/部署；待新授权后接续。

## P5 收口与下一阶段入口

本轮仅P5。按M1 GenUI/真实文档、M2图片/文件、M3全管理/身份/精选、M4原页面/视觉/回归验收收口，证据见[P5报告](p5-report.md)。真实外部供应商、旧生产副本、HTTPS反代逐项U；不因此以替身替代生产adapter。下一入口为上表P6，只在收到新授权后推进；不修改默认部署或开始生产切换。
