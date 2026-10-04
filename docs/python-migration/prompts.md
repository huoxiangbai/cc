# Reactor Python 迁移：开发顺序与分阶段提示词

本文件提供分阶段执行提示词；阶段实际状态以progress.md为准。当前审计和架构已确认，用户本轮恢复并仅执行准备/P0，已完成；P1未开始。发送某一阶段的执行提示词时，表示恢复并授权该阶段。GitHub已登录，但origin仍指向原作者OWWZO/ai-agent；本文件不授权push、PR、创建远端仓库或生产发布。

## 使用方式

按“准备 → P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7”顺序推进。每次发送下面的通用提示词和本阶段提示词；也可以让Codex读取本文件并执行指定阶段。阶段内自行拆分可运行里程碑，持续实现、验证和修复，完成本阶段后报告，不自动跨入下一阶段。

同一项目后续工作先读取progress.md并复用已完成实现、测试与决策。开始新聊天时仍指定项目根目录与阶段；不用重新复制最初的整份迁移需求。

如果前一阶段有外部集成未验证，后续不依赖它的实现仍可继续，但不得把前一阶段验收标成通过。前序确定性协议/状态测试的失败要先修复；最终正式切换前必须关闭所有范围内验收缺口。

## 通用提示词

```text
项目根目录：/Users/cuimingkai/Documents/claw-agent/ai-agent。
你负责按已确认方案迁移Reactor后端，请直接完成本轮指定阶段的实现、验证和文档更新。

先检查Git状态，读取根AGENTS.md和docs/python-migration中的progress.md、inventory.md、contracts.md、architecture.md、plan.md，以及本轮涉及的模块指南。审计已完成，按已有证据推进；发现遗漏时补充审计，不重新从零制定方案。以用户最新授权和progress中的记录为准，不因旧文档写“待确认”重复请求批准。

已确认边界：迁移当前代码实际实现的全部能力；不恢复已退役Workflow/定时任务；H2待核实，不能擅自删除实际依赖。保留原React工作台；新增独立Python backend，复用原Tool API和Sandbox，backend初期单worker；兼容原MySQL、SQLite、文件路径和ID关系；原Java保留用于对照与回滚。数据库更换不在本轮范围。

保护已有改动，特别是.github/workflows/ocr-review.yml。先在本地开发；当前origin是原作者仓库。不得自动push、创建PR、修改远端地址、创建云端仓库或操作生产数据；这些动作需另行授权。不要输出密钥、覆盖.env、清库或执行旧DROP脚本。

保持确定性HTTP/SSE/工具/GenUI/身份与持久化契约；模型自然语言无需逐字一致。权限和恢复缺口先按P0证据提出具体方案，涉及外部协议改变时确认；常规实现选择自行处理。不能用TODO、空实现、假结果或静默降级替代生产能力。

外部凭证不足时继续完成真实adapter及不依赖它的实现，隔离替身只用于测试，真实集成明确标“未验证”。所有命令只针对新建隔离环境或明确授权的测试副本，不能自动复用疑似生产连接。

每个里程碑更新覆盖表、测试命令/结果/限制和progress检查点。完成本轮阶段后报告：实现位置、可复现启动/测试命令、真实用户流程证据、未验证项和下一阶段入口。不要只输出建议或骨架，也不要未经要求开始下一阶段。
```

## 准备：本地分支与环境

```text
按照通用约束，只执行迁移准备，不实现Python业务。
1. 检查本地分支、工作区、暂存区和远端。复核已保存的本地快照，必要时创建增量快照。
2. 在保留全部已有改动的前提下创建或复用适合的本地迁移分支，避免重复创建。不要自动提交用户原有工作流改动。无需push或fork就可以本地开发。
3. 检查可用Python>=3.11、uv、Node/npm、JDK/Maven及缓存。默认python3为3.10不代表没有其他已安装Python；优先使用本机可用版本。
4. 明确依赖安装与临时文件目录、测试数据库与工具工作区。安装依赖只进入项目虚拟环境，不能改系统Python。
5. 将环境与分支信息记录到progress.md；报告可进入P0的条件和缺口，不启动业务或连接生产数据。
验收：已有文件未丢失；准备过程有本地恢复点；环境检查可复现；远端未变更。
```

## P0：行为基线、H2核实与测试资产

```text
恢复迁移，按照通用约束执行plan.md的P0，只完成基线与验证资产。
1. 将已审计的HTTP映射、请求响应、错误码、SSE载荷/事件顺序/结束、工具动态schema/返回格式、GenUI及文件访问整理为机器可执行fixture。明确源码推导、原Java实际捕获与未验证的区别。
2. 建立不依赖真实模型/生产数据库的Java基线runner和对照harness；隔离外部依赖但真实执行Controller、序列化、状态转换和投影。补齐原先被Surefire跳过的HITL恢复测试验证方式，不改业务行为让测试通过。
3. 核实H2从依赖/配置键/代码/测试到使用入口的路径；只记录配置键和是否启用，不输出真实值。区分已证实使用、代码支持和未知部署。未发现证据不能认定永远不用；有JVM依赖时提交具体兼容决策，不默认换SQLite。
4. 针对A2/A3给出具体身份/权限、孤儿Run/RESUMING、问题stop/expiry方案和负例验收。先记录当前Java实际行为及拟改变的请求/响应，协议改变取得确认后再实现；其他基线工作继续。
5. 在不连接生产的前提下提供MySQL/SQLite副本DDL比对、旧文件和旧历史验证命令；无副本时明确缺口。
验收：基线fixture可复现；核心确定性行为有原Java执行证据；H2结论有路径引用与证据等级；P1可使用这些资产比较。更新contracts、inventory、plan、progress，完成后停在P0边界。
```

## P1：完整纵向链路

```text
按照通用约束执行P1，先核对P0门槛并修复相关确定性失败，然后实现一条完整用户链路。
新增reactor-backend Python后端，落实已确认模块依赖方向与轻量锁定依赖；通过独立端口/启动配置验证，保留原默认Java入口。
实现原访客bootstrap/naming与会话归属、query请求规范化、真实模型adapter、ReAct工具调用循环、原reactor-tool至少一种真实工具调用、data-only SSE、MySQL Run/LLM/tool/artifact账本写入、跨轮上下文的必要读取，以及原历史列表/详情/replayFrames。
优先复用WebFetch或docread/dataprep等实际工具；完成工具错误/超时、结构化结果、产物注册与预览/下载关联。SSE断线不取消业务执行；原React仅作必要连接配置。
用P0固定模型响应测试多轮tool-call→observation→final及失败路径，再验证真实模型与真实工具；隔离MySQL中的新记录和旧Java历史回放保持兼容。无模型凭证/旧数据副本时生产adapter仍需完整，真实验收明确未验证，不改成demo模式。
验收：原工作台→Python Agent→真实工具→SSE→账本/产物→刷新历史能复现；隔离契约测试通过；给出启动和测试命令、数据关联证据与缺口。完成P1后停止，不宣称全部后端迁移完成。
```

## P2：编排、HITL、并发与运行控制

```text
按照通用约束执行P2，在P1实现上补齐Plan-Solve、模型目录/参数、重试/回退/空流补救、Todo、同步/后台子Agent、TaskOutput/TaskStop、mailbox、指导注入、上下文与工具隔离、会话能力开关。
实现计划审批/拒绝/编辑与用户提问/回答/取消/恢复；保留RunA WAITING_INPUT→CAS decision/claim→RunB关联，重复answer/decide/resume不重复派发，准入拒绝正确释放claim。落实已确认的P0权限/恢复修复。
实现stop-before-bind、同访客跨session单Run、不同访客并发、follow的128帧cursor/pending/idle、旧observer解绑竞争、根Agent返回后后台排空和stream_settle。
将该阶段拆成可运行里程碑并依次完成，不能把并发、子Agent和HITL留成占位实现。
验收：确定性并发与取消测试、隔离MySQL claim竞争测试、实际TCP断线重连与原UI刷新恢复；迟到完成不破坏已确认终态，浏览器断线不stop。后台重启不自动重放工具副作用；记录真实集成缺口。更新覆盖与进度，完成P2后停止。
```

## P3：研究、RAG、数据与代码执行

```text
按照通用约束执行P3，完整复用reactor-tool现有实现，迁移Java侧调用/处理/账本投影。
补齐DeepResearch、多渠道WebSearch/WebFetch与来源报告、现有三社媒只读工具、MRAG多模态检索/入库/知识库/历史、TableRAG与NL2SQL真实执行、数据处理、CodeAct与local/E2B沙箱、SOP及对应前端入口。
NL2SQL必须完成schema召回→生成→SQL解析/方言/业务DB执行→表格/图表和文件；不能只返回生成SQL。H2按P0核实及确认结果处理，不更换Reactor自身持久库。
保留Tool SSE与主Agent SSE的不同协议、DeepSearch阶段/章节进度、错误/超时、证据URL与完整文件。类存在、配置启用、渠道实测分别记录；不把Skill/MCP渠道说成全部原生内置。
验收：真实样本产物及来源可追溯；隔离接口/失败测试通过；各外部服务有单独验证状态。凭证缺失时继续其他能力，实现真实调用路径且标未验证。完成P3后停止。
```

## P4：记忆、压缩、Skill与MCP

```text
按照通用约束执行P4，迁移工作记忆读取/写入、跨轮重建与上下文预算压缩，保留tool-use/result配对、micro/session/模型压缩和失败回退。
实现curated长期记忆、原有可选语义provider、user/session/subagent scope、flush/review fork与session_search，不用普通消息表替代记忆系统。
迁移Skill发现、按需读取、物化/虚拟路径、真实脚本执行、package/import/reload与权限；原脚本和合法工作流保持可用。
实现MCP SSE/STDIO/streamable_http三传输、工具/资源发现、FQ名称与原wire名称映射、ToolSearch与延迟schema激活、session隔离和资源shutdown。
验收：旧工作记忆可续轮、压缩失败仍保留可用上下文、隔离负例通过；真实Skill脚本与三种MCP测试端点可运行；真实外部记忆provider未验证时单列。完成P4后停止。
```

## P5：GenUI、产物、图片与管理端

```text
按照通用约束执行P5，补齐原工作台和全部HTTP-only管理能力。
迁移GenUI tree/JSON Patch校验与历史合并、actions、HTML canvas、3D与iframe资源访问、独立GenUI PDF/DOCX导出；复用全部docgen/docread/dataprep、主题/模板和图表能力。
迁移Java当前图片供应商gateway，保留images/edits/mask、参数与默认模型、fallback、参考文件、request_source、批次历史与文件关联；不能假设现有Python服务已承担此链路。
完成上传/文件注册/预览/下载/工作区archive，保留旧URL、Unicode/嵌套路径/新旧MD5/MIME。
完成访客及已确认管理员认证方案、模型/API/MCP/Skill/SubAgent全部配置接口、热更新、精选会话公开/管理流程。按contracts全路由索引检查，不只实现UI目前调用的子集。
验收：原页面用户流程、真实导出内容与视觉、3D/GenUI交互、图片集成、管理配置生效和身份/path负例；未验证项逐项记录。完成P5后停止。
```

## P6：旧数据、全量行为与回滚验收

```text
按照通用约束执行P6，以inventory F01–F42和plan B01–B12逐项验收。
在明确授权的旧数据/文件副本上比较Java与Python的接口、SSE、状态、工具/产物关联、历史回放/续轮、记忆、GenUI、身份/路径和故障并发行为。读对照使用同一snapshot；写对照使用分开的副本，不能争写同session或重复外部副作用。
验证Python新写入可由旧Java读取/回放，并演练drain→切回Java→canary。必要DDL只用已确认的版本化加法迁移，检验备份恢复；不能清库重建。
执行原React实际用户流程与失败负例，关闭前期遗漏和已确认的权限/恢复问题。保留真实外部集成未验证项，不用隔离替身冒充真实验收。
验收：每项范围能力都有实现位置和证据；给出可复现报告与切换阻断项。存在真实验收缺口时继续无依赖工作，但不能宣称全量通过或授权生产切换。完成P6后停止。
```

## P7：无JVM启动、部署产物与切换准备

```text
按照通用约束执行P7，只完成本地/staging部署产物与验收，不发布生产。
落实Python正式启动/镜像/Compose配置，保留Tool API与Sandbox边界、代理路径、Cookie/CORS/SSE不缓冲/超时、配置兼容和共享文件挂载。正式运行路径不依赖Java、jar或Maven；保留原Java模块与可用回滚入口。
整理启动、依赖、配置键、外部服务、数据升级/备份、drain、canary、切换及回滚文档；不能输出真实配置值。
在隔离环境按完整部署命令运行原React用户流程，验证重连/HITL/文件访问和数据兼容，不只检查容器health。
验收：运行命令/镜像无JVM，范围内全部验收通过，旧数据与新写入回滚兼容，原Java仍保留。若P6仍有缺口，仅标“部署产物完成、正式验收待验证”；生产发布和Java清理需要另行明确授权。完成P7后停止。
```

## 中断后继续同一阶段

```text
恢复项目/Users/cuimingkai/Documents/claw-agent/ai-agent的Python迁移，继续当前已授权阶段。
先读取docs/python-migration/progress.md与最近测试/变更，保留工作区，复用已有实现；不要重新开始已完成审计或重写已验收模块。
从上个检查点未完成事项继续实现、运行必要验证、修复失败并更新覆盖/进度。真实集成缺凭证照实记录，不扩大阶段范围、不操作远端或生产数据。
```

## 每阶段的独立复核提示词

```text
复核刚完成阶段，不推进下一阶段。按contracts、inventory和plan的验收条件检查实际代码与测试证据。
重点找：未实现入口、空实现/假结果、成功路径以外的差异、SSE结束/断线/取消混淆、DB claim/ID关联、用户归属/path隔离、未验证真实集成却记为通过。
只读检查和运行隔离验证；报告有源码位置/复现条件的发现及严重程度，区分已复现和推断。没有证据的问题不要写成已验证缺陷。需要修复时另按原阶段范围推进，不自动切换部署或提交远端。
```

## 可选的个人GitHub仓库准备

本地开发不依赖这一步。需要远端备份时，单独明确自己的目标仓库名称、可见性和是否推送；选择fork或独立仓库后再执行，当前文档不替用户选择或创建。

示例请求：

```text
先检查huoxiangbai账号可用性与本地远端关系，为这个项目制定保存到我个人GitHub仓库的具体方案。
保留原作者仓库作为upstream参考，保护未提交改动。报告目标仓库、可见性、许可文件保留方式、拟推送分支和文件清单，检查.env/数据库/文件产物不入库。
在我确认这个具体目标前，不创建远端仓库、不改remote、不push。
```

提示词的里程碑、验收命令和持续进度记录写法参考[OpenAI Docs：Run long horizon tasks with Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)。阶段内容与迁移要求来自本仓库已保存的审计方案。
