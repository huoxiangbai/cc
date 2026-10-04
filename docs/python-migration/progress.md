# Python 迁移进度

## 当前检查点：P5 实现及隔离验收完成，停止（2026-10-04，Asia/Shanghai）

用户授权P5及已确认管理员认证；最新明确采用访客独立theme/template、共享只读。原Java/React/Tool/Sandbox/MySQL/SQLite/文件及默认部署保留。P6不启动。

- M1 GenUI/tree/patch/actions/canvas/3D/独立export、24原doc工具接线完成；实际SSE messageType与旧历史合并、真实导出内容和中文视觉通过。初次字体缺失已修复为OFL嵌入资源，原docgen DOCX主题alias保留。
- M2 原Java图片gateway、images/edits/mask/multiref/size/fallback/批次history/产物完成；workspace与主Agent两来源实际TCP/Tool文件/账本关联通过。新旧MD5/Unicode/nested/MIME/Range/HEAD/archive、替换symlink及外访客引用拒绝通过。
- M3 完整108原Java路由method/path索引通过；64原admin+5精选管理完整CRUD/query/model-test/SkillZIP及URL导入/reload、配置下一次真实调用生效。32字节opaque Cookie/8h/SHA-only/enabled/expiry/revoke/CSRF，公开精选精确输出allowlist与下线撤销通过；首管理员空表CLI成功/非空拒绝。必要原UI登录弹窗与鉴权拒绝CORS接线。
- M4 最终backend **159 passed /55 skipped/16 warnings**（未提供集成环境门控项另由harness验证）；全新隔离 **46 passed**；原Java实际账本 **5+2+11帧PASS**；UI **434 passed/2原基线failed**，production build通过。原页面命名/GenUI按钮与iframe交互/3D加载拖拽/刷新历史/生图历史/管理员模型创建+连接成功，截图归档。
- 最终integration root `reactor-p5-qq8pdiiy`；此前`kra38x10/tmtr7ew5/oz4t41m3`各46通过。新增Agent图片补验初次测试误用工具名/字段，`llijrr9s`45通过/1失败保留；改为真实image_generation_tool/tool_invocation_id后新root46通过。此前遗漏schema/依赖/测试参数与路径alias/Range等中间失败完整保留，不在旧root清库重试。
- U：真实Micu/Grok图片、真实LLM与远端语义provider/MCP/E2B、真实旧数据库/文件授权副本、HTTPS/Nginx/部分Office阅读器/远端图源模板，逐项见[P5报告](p5-report.md)。Grok分支代码保留，本轮Grok专用TCP实测亦U，不冒充全部迁移或生产验收。
- [机器证据](fixtures/p5-evidence.json)、[页面证据](fixtures/p5-browser-evidence.json)、[启动/测试](../../reactor-backend/README.md)、[覆盖表](inventory.md)。workflow SHA256仍`f1eca5939f829e26e6ea45c66a07c92d8bb9536d16a8fffb33b23bbbe667248e`，原改动保留；无push/PR/remotes/生产/.env/DROP。
- 终检：826本地链接、26归档SHA256、offline wheel/sdist及P5资源/字体/OFL包含、compileall/Git diff通过。PPTX两页（子进程显式CJK字体目录）、XLSX首表/图表视觉通过；PPTX仍需阅读器字体。已关闭本轮标签/reset视口、停止自己的预览/Tool/model/backend/隔离MySQL与Vite/helper，数据日志保留。
- 下一入口仅plan的P6，需另行授权；完成本轮停止。原隔离数据/日志保留，测试进程清理结果在下方终检记录。

## 前轮检查点：P4 实现及隔离验收完成，停止（2026-10-04，Asia/Shanghai）

用户明确授权 P4，并明确采用 P0 A2 Skill 方案：访客读共享、写/执行自己的会话副本，管理员维护共享库。覆盖旧“待确认”。P4 已完成；P5 管理 HTTP/完整 GenUI 等未开始，默认入口未切换。

- M1：`memory/working.py/service.py/providers.py`、`adapters/memory_store.py/mysql.py` 完成旧投影读写、reasoning/media、预算/micro/session/模型压缩与失败回退、curated/user profile、memory-only flush/review fork、FULLTEXT session_search。真实 Java 投影续轮通过；Java `sub:<id>` 和 P2 `subagent:<id>` 兼容读，新写 Java scope，主子和访客隔离通过。
- M2：`skills/registry.py/manage.py` 完成原 31 Skill 发现、手册按需读、物化/虚拟路径、真实原 package 脚本、package/import/URL/reload 与会话副本。operator CLI 真实验证；管理员 HTTP 按计划 P5。`mcp/runtime.py` 官方固定 SDK 三传输、FQ→wire、ToolSearch/延迟 schema、资源及 shutdown 真实本机端点通过。
- M3：最终 **141 passed / 1 skipped / 0 failed**（142 总数，16 warnings）、**50 passed / 0 skipped** 真实隔离 TCP/原 Tool/MySQL/SQLite/P1–P3 回归，**70 原 Java 记忆 JUnit**，Java 实际 Python 账本 **5+2+11 帧 PASS**。最后原子 reload 调整后 **10 Skill 测试通过**；CLI import/reload/preview/重复拒绝/真实 URL import 通过。结果与归档 SHA256 见 [机器清单](fixtures/p4-evidence.json)。
- M4：原 React 命名→长期记忆写入→同会话续轮→刷新/近期会话恢复，实际下一 HTTP 模型请求含 curated 偏好；MCP 三传输工具/资源及原 Skill Creator 产物 213 字节验证。浏览器模型为 tests HTTP fixture，工具/数据库真实。截图早于最终 Bash 收窄；最终真实脚本由新 HTTP 集成和原生权限负例复验，不宣称 `.skill` 二进制浏览器预览已支持。
- 已批准权限：macOS 原 Sandbox Bash 增加内核 deny-default 文件策略，仅会话可写、明确 runtime 可读，HOME/TMPDIR 在本会话且 O_NOFOLLOW。真实 Python/YAML 脚本成功；其他会话/共享库写/host passwd/symlink/凭证继承负例通过。其他平台本地 session-copy 明确要求 E2B。宽泛只读提案被自动审查拒绝、未执行；收窄 literal-directory 策略经独立负例证明后获准。外层沙箱复验不能加载 kernel profile，获准本机复验 10 项通过。
- U：真实模型/embedding/远端语义 provider、远端 MCP 鉴权/网络、E2B/其他平台执行环境、真实旧 MySQL/多模态副本、旧 USER owner 可信映射。Java 可选 holographic/OpenViking 实际为本地内存实现；endpoint 配置不等于远端集成。不得声称全部迁移或生产验收完成。
- 原 workflow SHA256 `f1eca5939f829e26e6ea45c66a07c92d8bb9536d16a8fffb33b23bbbe667248e` 保持；原改动保留，无 push/PR/remote、生产、.env 或 DROP 操作。P3 原 Tool/UI 基线失败未冒充本轮修复。
- 交付：[P4报告](p4-report.md)、[覆盖表](inventory.md)、[契约](contracts.md)、[启动/测试](../../reactor-backend/README.md)、[浏览器证据](fixtures/p4-browser-evidence.json)。最终集成 root `reactor-p4-8zj4rb66`，浏览器 root `reactor-p4-uh6h0rak`，隔离日志/数据库保留。下一入口为 plan 的 P5，需另行授权；完成本轮后停止。

终检：824 个本地文档链接和 6 个归档 SHA256 通过；offline wheel/sdist 构建及 P4模块/schema 打包通过，Git diff check 通过（原workflow CRLF提示保留）。

终检清理：本轮浏览器测试标签已关闭；serve harness、原Tool/模型fixture/新MySQL/backend及Vite/helper已停止，隔离数据/日志保留。SIGINT退出130为主动收尾；未停止其他服务。

## 前轮检查点：P3 实现与隔离验收完成，停止；下一入口 P4（2026-10-03，Asia/Shanghai）

用户最新授权的独立SQLite业务源、私有Tool ACL和内部认证已执行，覆盖历史待确认；Reactor MySQL账本、原Tool SQLite及Java/H2回滚保留。外部缺凭证服务逐项U，不代表生产切换；本轮不实施P4。

- M1：SQLite真实连接/发现/原元数据初始化同步、schema→原NL2SQL→AST/方言/实际执行→表格/图表/CSV/来源文件闭合；get_data实际返回DataFrame。JOIN/CTE/UNION/日期/NULL/Unicode/大小写/整数/金额兼容验证，不静默丢精度。
- M2：可信访客、持久owner、加法001和独立内部认证/签名回调接入原文件/KB/document/history/问数；同访客正常、B403、缺身份/伪owner/坏认证拒绝、旧无owner不认领、重启映射保留通过；两次批准Sandbox守卫回归通过。
- M3：118 backend测试通过；SQLite和保留业务MySQL各42项同套真实隔离集成通过；Java账本5+2+11帧/四组SQL DTO通过。原Tool127项114通过/13失败，HEAD原源码逐项同失败；原UI436项434通过/2同HEAD失败，构建通过。失败保留不删/跳/算通过。
- M4：原React问数表格/图表、主Agent自动分析→完整报告预览→刷新历史恢复实测；私有KB建库/上传/原文预览成功，缺embedding入库明确失败。模型仅HTTP fixture；原Tool/SQLite/DataFrame/文件真实。独立问数SSE原本不创建主Agent历史，不扩张恢复声明。
- 文档/证据：[P3收尾报告](p3-closure-report.md)、[机器清单](fixtures/p3-closure-evidence.json)、[完整产物](fixtures/p3-closure-artifacts)、[启动/测试](../../reactor-backend/README.md)。SQLite root reactor-p3-mpvo90vz；MySQL root reactor-p3-axv77fa5；浏览器root reactor-p3-6cwrb_px。此前中间失败/待确认记载为历史，以本检查点为准。
- 保护：workflow/.gitignore原改动保留，无远端/生产/.env/DROP操作。新隔离数据和日志保留，关闭本轮测试服务与标签。下一任务接续plan的P4，完整Skill/MCP/记忆与上下文；本轮停止。

终检：36份归档文件大小/SHA256、文档本地链接及Git diff检查通过；保护workflow哈希未变。已确认本轮backend/Tool/模型fixture/新MySQL/Vite/UI helper停止，浏览器测试标签已关闭，隔离日志/数据库保留；SIGINT退出130为主动清理。

## P3 前轮检查点（历史）：P3 本轮实现与隔离验证交付，停止阶段推进（2026-10-03，Asia/Shanghai）

用户本轮授权 P3；两次明确批准原 Sandbox 最小守卫修复已执行，不重复请求。M1工具/流/专用账本、M2问数和M3验证均已交付。**P3正式启用/全量验收仍未闭合**：私有Tool file/KB/data query ACL外部协议与H2可选JDBC方案待具体决定；各外部服务live状态逐项标U。保留原Java/default，不开始P4/P5。

- 实现：独立backend复用原DeepSearch、五原生WebSearch渠道、WebFetch、三社媒、MRAG、TableRAG/NL2SQL、auto_analysis、CodeAct/local/E2B和SOP入口；Java调用/处理/专用账本迁移到Python。Skill/MCP不冒充原生渠道，完整runtime留P4。
- 问数：schema召回→原NL2SQLAgent生成→SQL AST/业务方言→独立业务MySQL真实执行→原表格/图表DTO及CSV、完整来源文件。新库sales三行实际得到A=30、B=7.5；自动分析内层get_data实际经该链路得到DataFrame。
- 最终验证：**101 backend确定性测试通过、36真实TCP/MySQL/原Tool/SQLite集成通过、原Java账本5+2+11帧回放通过、3组Java SQL DTO对照通过**。原Tool选定127项114通过/13失败，平台假设及旧断言原因逐项保留，未全绿。
- 原React实际聊天→文件预览→刷新历史恢复；MRAG创建知识库实际写入SQLite；SOP缺Qdrant配置实际明确失败。原UI源码未改。公开Python教程WebFetch实际完整文件/来源/sha256留档。模型仅隔离HTTP fixture；供应商、五搜索/六DeepSearch引擎、三社媒、MRAG外部服务、ClickHouse/E2B/旧数据副本均按服务单列未验证。
- P0修复：仅原executor透传三个既有guard开关、runner执行前调用原静态校验、runtime guard接入builtins.open/io.open原路径校验。实际越界拒绝及正常CSV执行通过；不声称语言I/O守卫等同OS隔离。Tool进程必须显式全部开启。
- 最终集成root reactor-p3-5bcl0tfu；原Tool测试root reactor-p3-tool-tests-yzgfw6ub。日志/JUnit/新datadir保留，样本文件复制进[机器清单](fixtures/p3-evidence.json)与[产物目录](fixtures/p3-artifacts)。完整实现/失败记录/渠道表见[P3报告](p3-report.md)，复现启动/测试见[backend README](../../reactor-backend/README.md)。
- 收尾：uv离线锁校验、Git diff检查、文档本地链接与11个样本sha256通过。已停止本轮创建的backend/原Tool/模型fixture/新MySQL/Vite与浏览器测试标签；日志、datadir与文件保留，未停止其他服务。
- 不读取或覆盖.env、不执行旧DROP、不操作生产数据，无push/PR/远端更改；原workflow/.gitignore改动保留。ACL/H2具体方案见[p3-pending-decisions.md](p3-pending-decisions.md)。下一入口先关闭P3确认门与所需外部验收；P4需另行授权。

## P2 完成并停止（历史检查点，2026-10-03，Asia/Shanghai）

用户本轮明确授权 P2 与已确认 P0 owner/恢复修复；历史“待确认/未开始”不再覆盖本轮已实现的修复。范围止于 P2，未进入 P3–P7，未切换默认部署。

- M1：模型目录、采样参数/JSON显式配置、planner模型/400步参数、重试/备用/struct_parse/一次空流补救；首批 35 通过。
- M2/M3：PlanSolve、审批批准/拒绝/编辑、提问/回答/取消/恢复、Todo、同步/后台子 Agent、TaskOutput/Stop、mailbox/指导、上下文/工具隔离、能力差集；中间 53 确定性 / 20 集成通过。
- M4 最终：**59 确定性测试、25 真实 TCP/MySQL/原 Tool/SQLite 集成、原 Java 5+2+11 帧回放、原 UI 六文件 26 项通过**。24 路 decide/claim、12 路 TCP resume、stop-before-bind/取消/晚完成、同访客单 Run与异访客并发、128cursor/observer竞争、follow park/pending/idle、根返回后台排空/stream_settle、两次 SIGKILL重启无副作用重放已验收。
- 原 UI实际流程：提问暂停→刷新恢复→回答/文件；PlanExecute→刷新→拒绝修订→编辑批准/实际报告；后台 root 返回→刷新历史→原子 Agent面板 Completed/产物。浏览器 BG 流程恢复已完成后台历史；活跃期间断线/cursor续流由 TCP验证。原 UI源码未改。
- P0 修复：P2资源 owner/非空身份、旧无owner拒绝首次认领、expiry、terminal CAS、claim释放/锁读、运行恢复收口落实。管理员认证与Tool私有资源/Skill import随P3/P5接入；不把整个 A2写成完成。Java/H2保留。
- 失败记录：新增 TCP resume竞争首次24通过/1失败，发现MySQL RR旧snapshot误报状态，claim后SELECT FOR UPDATE修复，最终25通过；原日志保留。真实供应商/旧数据副本、外部服务、Nginx/HTTPS仍 U。
- 最终集成 root `reactor-p1-8dwz_4qh`，浏览器 root `reactor-p1-5tzg79ec`；机器证据 [fixtures/p2-evidence.json](fixtures/p2-evidence.json)，报告 [p2-report.md](p2-report.md)，启动/隔离命令 [backend README](../../reactor-backend/README.md)。打包/文档终检和测试服务清理见最终收尾记录。
- 原工作流/.gitignore和P1资产保留；无push/PR/远端更改，无.env加载覆盖、旧DROP或生产数据操作。**P2已完成，当前停止；下一入口为plan的P3，只在新授权后继续。**

## P1 检查点（历史记录，2026-10-03）

用户本轮授权 P1 实现、验证和文档更新；完成 P1 后停止，不自动进入 P2。下面 P0 的“未开始/等待授权”已被本轮授权替代。

- 门槛里程碑：原 P0 golden 对照、102 Java JUnit（0 失败）、9 harness 通过；没有需修复的 P0 确定性失败。A2/A3 的具体权限/恢复协议方案仍只保留证据；本轮没有改变旧 stop/answer/expiry 协议，未启用这些 Python 入口。
- 实现里程碑：新增 `reactor-backend/`，独立端口、锁定依赖、真实 HTTP 模型 adapter、ReAct、原 Tool API、MySQL 账本/必要 working memory、data-only SSE、断线 follow、访客归属和历史回放；生产代码不含固定模型或 demo 分支。
- 第一批验证（保留里程碑）：`reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py -q` 22 通过；真实 TCP + 新 MySQL datadir + 原 Tool/SQLite 文件路由集成 7 通过。原 Java projector 对实际 Python 写入账本回放 5 帧逐字段一致（仅 taskId 动态归一）。
- 原 React 浏览器：独立临时 root `reactor-p1-gcon5v70`，访客命名→text_processor 写入/读取→SSE→文件预览；刷新后从近期会话恢复、文件栏再预览成功。模型上游是隔离固定响应 HTTP fixture，不是供应商实测。下载字节由 TCP 集成验证；浏览器下载事件捕获超时，不能记为浏览器下载已验收。
- 本轮真实模型凭证及真实旧数据副本未提供，均 U；只使用新建隔离 MySQL、SQLite 和文件目录。Java/default 部署、原 H2、用户工作流/.gitignore 改动保持；未 push/PR/远端修改、未加载或覆盖 .env、未操作生产数据。
- 最终验证：Python契约 **28通过**，独立TCP/MySQL/原Tool/SQLite集成 **10通过**；原Java回放对照 **5+2+11帧通过**（通用/GenUI/rich含产物，taskId归一）。UI选定5文件 **14通过**；不是全套UI/全部后端测试结果。额外补齐专用rich与GenUI旧表读侧、原模型DB绑定/窗口；未启用对应生成/管理/HITL执行。
- 打包/边界检查：sdist与wheel构建成功，prompt/schema/GenUI资源包含；文档本地链接与Git diff检查通过。已停止本轮创建的预览/Tool/模型fixture/隔离MySQL进程，日志与数据保留。原Tool测试宿主禁用dotenv自动发现且审计阻止.env读取；生产Tool源码不变。
- 最终隔离root：`/var/folders/15/rh2lsj816qn5q7p7djht06bc0000gn/T/reactor-p1-mwpe__4r`，原始JUnit/日志/导出SQL事实保留；[P1证据索引](fixtures/p1-evidence.json)记录Run/LLM/tool/artifact关联和真实/fixture边界。初次环境与测试种子/捕获器失败保留于报告，修复后复跑通过。
- 实现/启动/测试/限制见 [p1-report.md](p1-report.md) 和 [backend README](../../reactor-backend/README.md)。**P1实现与隔离验收完成；真实供应商/旧副本U，不切正式入口。已停止阶段推进，P2未开始。** 下一阶段入口为plan的P2，仅收到新授权后实施。

P0 历史日期：2026-10-02（Asia/Shanghai）。用户当轮已恢复迁移，当轮只授权“准备”和P0；P0基线与验证资产完成，停在P0边界，P1未开始。

## P0 检查点（历史记录）

- 本地分支 `migration/python-p0`，HEAD仍`cb6e389a`，无commit/push/PR/remote变更，暂存区为空。原工作流与.gitignore改动保留，未改Java业务、原部署、DB初始化或生产数据。
- 原七份文件快照哈希已复核；新增八份文件恢复点`../local-snapshots/ai-agent-p0-prep-20261002-225540.zip`，SHA-256 `46a713cecb0c1466ec89027cb3682595b990631c9e5610f4a40f96e3d09fdd72`。恢复前先比较，不覆盖后续工作。
- 选择本机Python3.12.13建立项目`.venv`；Python3.11.12、uv0.11.32、Node22.23.1/npm10.9.8、JDK21.0.12/Maven3.9.11可用。P0Python仅stdlib，未安装依赖或改系统Python。后续backend依赖进入项目虚拟环境，临时/副本/日志只放ignored target或独立临时root。
- 已交付`tests/python_migration/`离线Java runner、对照器、source索引生成器、测试副本只读校验器，以及`docs/python-migration/fixtures/`原Java/rawHTTP/SSE/DTO/工具/GenUI/历史/CAS fixture。108路由源码与Spring反射集合一致，67命名工具schema、63个显式全工具ReAct池、61字段类、33MySQL表/30mapper、Python路由/SQLite模型均登记；证据类别分别标注，未冒充全端点/外部服务实测。
- 最新选定Java JUnit **102通过，0失败**，含原case审批恢复1及子Agent配置1（直接JUnitCore绕开父Surefire skip）、真实工具observation/产物绑定8；另有Java capture断言。Python harness **9通过**。首次95中1个部署profile测试因application-dev.yml未打包失败，原日志/结果保留；该1个用例明确排除为部署U，其余11个工厂测试执行。最终默认重新捕获与golden对照通过，源码fixture漂移检查通过。不是全套测试结果。
- H2已核实runtime依赖、业务query/metadata配置和DataAgentInitRunner启动入口；新建内存库实际执行原SPI/连接池/catalog/DataQueryExecutionAdapter及user_question SQL。工厂支持mem，不支持file/tcp，与注释不同。prod的type/url占位符未解析，dev/test本地文件不存在；实际部署H2是否启用仍U。保留原H2，不换SQLite；P7无JVM决策缺口单列。
- A2/A3具体方案与拟改变响应、状态/CAS和负例验收已保存[p0-decisions.md](p0-decisions.md)，用户确认前不实现协议变更。已执行复现其他访客stop、缺身份answer、过期answer接受、markFailed覆盖ANSWERED；原Java行为保留。
- 真实MySQL/SQLite旧数据副本、旧文件、Cookie/Nginx/TCP/原UI流程、全部远程工具/模型仍U。[copy-validation.md](copy-validation.md)提供副本DDL/文件/历史命令，校验器只跑合成测试副本；无生产连接、无外部账号动作。
- 完整成果/测试命令/限制见[p0-report.md](p0-report.md)，H2路径见[h2-evidence.md](h2-evidence.md)。下一步仅在新一轮明确授权P1后开始真实纵向链路；复用P0fixture，不重审计，不重复确认已批准架构。A2/A3及H2范围/数据源行为需要具体决策，其他无依赖工作可继续。

复现：

```bash
.venv/bin/python tests/python_migration/run_baseline.py
.venv/bin/python tests/python_migration/export_source_contracts.py
.venv/bin/python -m unittest discover -s tests/python_migration -p test_harness.py -v
```

最终P0恢复包：`../local-snapshots/ai-agent-p0-complete-20261002-232910.zip`，包含本轮文档/fixture/测试源码及原有工作流/.gitignore；包内manifest记录各文件SHA-256。未包含.env、数据库、target日志或凭证。

## 历史记录（以下暂停和环境描述已被当前检查点替代）


日期：2026-10-02（Asia/Shanghai）。阶段一文档完成；用户已批准P0/P1，目前按用户要求暂停实施并处理本地保存/GitHub登录。

- 基线：`master`，`cb6e389a`。开始时仅 `.github/workflows/ocr-review.yml` 有用户改动，保留不动。
- 已检查根 `AGENTS.md`、模块说明、README、全部 Java Controller 映射、Python 路由装配、前端服务与流消费、MySQL schema/mapper、SQLite 模型、Docker/Nginx、关键运行控制和测试。
- 已核实：ReAct/Plan-Solve 两种策略；访客单 Run 并发；断线解绑与显式停止分离；128 帧进程内续流缓冲；审批/提问 DB continuation；后台任务重启孤儿标记失败；mailbox 为进程内队列。
- 原 Java 选定的16个测试类共80个隔离测试通过：初次24、domain追加21、app流测试17、身份/历史/归属复跑18。后18个首次受Mockito self-attach限制报错，命令行预载已缓存agent后通过；保留初次失败记录。case模块审批恢复测试被父Surefire配置跳过，尚未验证。
- 原 Python 的 `test_sandbox_backend_config.py` 4 个测试通过（仅 E2B 代理配置）。默认 Python 3.10，不满足项目 >=3.11；无项目虚拟环境、FastAPI/SQLAlchemy/httpx；UI 无 node_modules。
- 四份文档已完成：[功能清单](inventory.md)、[兼容契约](contracts.md)、[目标架构](architecture.md)、[阶段计划](plan.md)。范围42项能力；契约含108个Java方法映射、当前Python路由、DTO字段、68个工具名称定义、33张MySQL表和30个SQL mapper索引。工具类索引不等于默认模型可见工具数。
- 656个文档/源码链接检查通过，均有实际文件，源码行号有效；Git差异检查通过。原docs目录整体被忽略，.gitignore只为本迁移文档子目录增加例外。原工作流用户改动未动；没有修改业务代码、DB脚本或默认部署。
- 未连接 MySQL、SQLite 实际数据文件、外部模型、搜索、向量库或 E2B；没有操作生产数据。真实旧数据兼容、UI流程、外部集成均为未验证；动态工具schema和原始HTTP序列化快照留P0。
- 已确认：采用上述架构与处理方向，开始P0/P1；旧Workflow/定时任务无需恢复；H2使用情况待核实。用户随后要求先暂停迁移、检查GitHub登录并本地保存，未新增Python业务代码。权限/恢复的具体协议方案仍按P0取证推进。
- 本地保存/GitHub：2026-10-02已保存7个改动文件到claw-agent/local-snapshots/ai-agent-20261002-223215.zip并校验SHA-256；GitHub官方设备授权登录huoxiangbai成功，通过正常系统钥匙串环境复查凭证有效（沙箱内auth status会误报）。未push、未创建PR、未改远端地址。
- 下一步：迁移保持暂停，等待用户恢复。恢复后继续已授权P0/P1，不重复请求范围/架构确认；不替换原默认启动路径。
- 开发提示词已保存到[prompts.md](prompts.md)，包含准备/P0–P7、通用约束、阶段复核与中断恢复。仅整理说明，未执行阶段任务；原origin仍指向OWWZO/ai-agent。plan中的旧授权描述已更新，后续按最新记录判断。

可复用命令和完整验收门槛最终记录于 `plan.md`。本文件是执行检查点，不代表任何 Python 后端能力已经迁移。

### P2 M2/M3 检查点（历史里程碑，已由上方最终检查点替代）

- 原表 `user_question/plan_approval` 两步决定→claim→RunB 已接线，审批 reject 修订、edit 后真实 Tool 写报告；源 RunA 保留 WAITING_INPUT。双身份负例、24 路 decide/24 路 claim、拒绝准入释放 claim、迟到终态 CAS、expiry/pending cancellation 均隔离 MySQL V。
- Todo、同步/后台 Agent、TaskOutput/TaskStop、mailbox FIFO、指导注入、工具/上下文隔离、PlanSolve planner 参数/工具门禁、capability owner/difference sets 已实现；子工具父调用与 memory_scope 持久化。
- `reactor-backend/.venv/bin/python -m pytest reactor-backend/tests/test_contracts.py reactor-backend/tests/test_p2_models.py reactor-backend/tests/test_p2_runtime.py -q`：**53 passed**。
- `reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p2`：**20 passed**（P1 10 + P2 10）；root `/var/folders/15/rh2lsj816qn5q7p7djht06bc0000gn/T/reactor-p1-s9n2e03f`。新建 MySQL datadir/33 CREATE，原 Tool/SQLite 文件写入是真实执行；上游模型是独立 HTTP fixture，供应商 U。Java P1 对照仍进行输出检查。
- 初次沙箱内 mysqld initialize SIGSEGV（与 P1 环境问题一致）；新隔离环境经本机执行权限运行通过，保留失败日志。没有复用旧/生产连接。
- M4 尚需进程 kill/restart 不重放、follow park/pending/idle、更多取消/快完成/子代理续跑竞争、原 React HITL 刷新/继续/后台 follow 证据及文档终检。未进入 P3。


### P2 最终收尾

- 2026-10-03：最终新 root `reactor-p1-8dwz_4qh`，25集成/59确定性，原Java5+2+11帧与UI26项通过。重启覆盖根已SUCCESS后台未完场景，receipt/子调用失败收口，根终态不改，无工具重放。
- ui_copy.py 在新 root `reactor-p1-92wpj3c3` 实测启动原命名页、依赖字体HTTP200；不复制dotenv，Vite cache落隔离root。最终wheel/sdist包含planner/system prompt和schema；738本地文档链接、Git diff和新源码/文档空白检查通过。
- 已关闭本轮浏览器页和UI/helper/harness创建的模型、Tool、backend、MySQL进程；数据/日志保留。工作流SHA-256仍为`f1eca5939f829e26e6ea45c66a07c92d8bb9536d16a8fffb33b23bbbe667248e`；Git仍仅初始两项tracked改动及迁移未提交资产。无commit/push/PR/生产操作。**P2完成后停止；P3未开始。**
