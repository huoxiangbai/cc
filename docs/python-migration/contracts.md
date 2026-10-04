# HTTP、SSE、工具、身份与存储兼容契约

> 2026-10-04 P5 当前检查点：交付/图片/全部管理接口已实现，159 确定性通过、46 真实隔离集成与 Java 5+2+11 帧回放通过；管理员登录、原工作台交互和中文导出视觉通过，P5完成后停止。原 UI 434 通过/2 个已知基线失败保留。真实图片/模型供应商与真实旧数据仍 U。已批准访客 theme/template 独立配置、共享只读；见 [P5报告](p5-report.md)。完成 P5 后停止，不启动 P6。


> 2026-10-04 当前检查点：P4 实现及隔离验收完成，停止。用户已批准访客 Skill 会话副本/管理员共享库方案；141 确定性测试通过（1 环境门控 skip）、50 真实隔离集成、70 原 Java 记忆测试通过。macOS 原生文件边界已验证，外部记忆 provider/MCP/E2B 与真实旧数据仍 U；管理 HTTP 留 P5。见 [P4报告](p4-report.md) 和 [progress.md](progress.md)。下文历史“未启动/待确认”以本条为准。

> 2026-10-03 P3收尾更新：用户已授权独立SQLite替代H2业务源及可信身份/持久owner/内部认证方案。下文原审计的待确认记录为历史；最新实现、验收与边界见 [P3收尾报告](p3-closure-report.md)。Reactor MySQL账本及Tool SQLite保持，Java/H2保留回滚；P4未启动。

基线：2026-10-02，master cb6e389a。本文以源码绑定/前端消费者/mapper为规范，静态索引不是运行时OpenAPI或网络抓包。运行结果见 [plan.md](plan.md)，能力差异见 [inventory.md](inventory.md)。默认保持现有外部行为；发现缺陷不能静默改成“更合理”的协议。

## 1. HTTP 总体约定

后端部署端口8100，原 `/web/`、`/api/`、`/data/` 前缀保持；Tool API1601，经Nginx `/tool/` 去前缀到 `/v1/...`；Sandbox1602内网角色。依据 [nginx.conf:1](../../docker/nginx.conf#L1)、[docker-compose.yml:1](../../docker-compose.yml#L1)、[origin.ts:4](../../ui/src/utils/origin.ts#L4)、[vite.config.ts:7](../../ui/vite.config.ts#L7)。SSE代理要保持不缓存、长timeout；当前 `/api/` Nginx location 未显式关闭buffering，而follow/HITL使用它，需P0验证网络行为，不能只测直连。

Java普通Response为 `{code:string,info:string,data:T}`，[ResponseCode.java:15](../../Reactor-agent-types/src/main/java/org/wwz/ai/types/enums/ResponseCode.java#L15)：`0000`成功、`0001`未知失败、`0002`非法参数、`0003`登录失败。业务拒绝大量仍HTTP200并携带code；不能统一换HTTP4xx。Data `/allModels`、`/previewData` 使用 `{code:200,data:...}`；其他数据问数接口直接返回业务对象/列表，没有统一Response（[DataAgentController.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L39)）。Tool服务多为裸JSON/流，UnknownException返回500纯文本，FastAPI请求校验仍有自己的422（[middleware_util.py:29](../../reactor-tool/reactor_tool/util/middleware_util.py#L29)）。GenUI导出是成功二进制/400 `{code:"400",info}`/500 `{code:"500",info}`（[AgentGenUiExportController.java:27](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentGenUiExportController.java#L27)）。

UI axios解包上述两种成功包，普通请求超时10s、multipart至少60s、withCredentials和X-Device-Id（[request.ts:119](../../ui/src/utils/request.ts#L119)）。SSE是独立POST fetch adapter，credentials include，X-Device-Id=轻量固定device-default，不是身份凭证；不要凭这个header划分会话owner（[querySSE.ts:47](../../ui/src/utils/querySSE.ts#L47)、[agentConversation.ts:11](../../ui/src/services/agentConversation.ts#L11)）。

`@RequestMapping` 未指定method表示源码未限定HTTP方法；主入口的UI实际用POST。Python不能未经确认只实现POST并声称所有方法契约不变。Java binding缺字段/类型异常、null是否序列化、日期格式需P0用隔离HTTP捕获；Pydantic coercion、extra ignore、默认422不能直接当Java基线。

### 1.1 核心请求和返回

| 路径/方法 | 输入与默认 | 结果/错误/关联 |
| --- | --- | --- |
| 任意method `/web/health`（常用GET） | 无body | 200 `ok`；源码声明text/event-stream但不是业务流 |
| 任意method `/web/api/v1/gpt/queryAgentStreamIncr`（UI POST） | [GptQueryReq.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/req/GptQueryReq.java#L18)：query/sessionId/requestId/deepThink/outputStyle/traceId/user/model/thinking/thinkingEffort/sessionFiles/forcePlanMode | user缺省reactor，deepThink缺省0，非0→PlanSolve(3)，否则React(5)；requestId原样trim作为run身份，traceId只追踪；query入口存在open HITL时拒绝；错误有completeWithError，不全是JSON错误帧 |
| POST `/api/agent/run/stop` | `{requestId,sessionId?}` | Response data `{requestId,sessionId,stopped,message,firstCancel?}`；requestId空0002；未找到是0000包+stopped=false；首次/再次停止firstCancel区分 |
| POST `/api/agent/run/inject` | `{requestId,sessionId?,text}` | accepted/queued/message；trim、最多8000字符；不begin新run，下一step消费；缺字段0002，未接受0001 |
| POST `/api/agent/run/follow` | `{requestId,sessionId?,lastEventSeq}` long缺省0 | 重绑观察，不dispatch；无ID/已终态/拒绝→follow_idle；registry缺而ledger RUNNING→park后pending；不把pending当finished |
| GET `/api/agent/conversation/sessions` | limit缺省20，后续范围normalize由query service决定 | 访客recent列表；不含完整summary；日期/统计/status保持 |
| GET `/api/agent/conversation/sessions/{sessionId}` | existing owner校验；不新建空会话 | `{sessionId,title,status,deepThink,runCount,finishedRunCount,failedRunCount,startedAt,lastActiveAt,runs:[{requestId,status,queryText,finalSummaryText,startedAt,finishedAt,contextUsage,replayFrames}]}`；拒绝0001 |
| GET/POST `/api/agent/visitor/bootstrap` / `/naming` | GET bootstrap、POST `{username}` | visitorId/username/named；new/invalid token换cookie；命名门槛不能跳过 |
| POST `/api/agent/file/upload` | multipart sessionId+file；非空；真实文件流 | AgentFileUploadRespVO：含预览/下载/size/mime/name等（见DTO索引），owner从server context取得 |
| GET `/api/agent/workspace/{sessionId}/archive` | existing owner、合法session root | ZIP二进制，文件名/错误码和archive过滤保持；不是新的云存储实现 |
| GET/PUT `/api/agent/session/{sessionId}/capabilities` | PUT `{kind,refId,enabled}` | kind skill/mcp、配置差集语义；原scope权限缺口单列，不假设已保护 |
| POST `/api/agent/genui/export/pdf`、`/docx` | `{tree,mode?}`，mode缺省document | 二进制+Content-Disposition `genui-yyyyMMdd-HHmmss.ext`，对应MIME；非法tree400，服务异常500 |
| POST `/api/agent/image-generation/generate`、GET `/history` | [AgentImageGenerationController.java:34](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentImageGenerationController.java#L34)和VO索引；history pageNo缺省1、pageSize缺省10（当前不按sessionId过滤） | workspace生成与会话tool同gateway，使用request_source区分，不伪造Agent run；供应商默认model由server决定 |
| GET `/api/agent/featured-conversations/home`、base、`/{featuredId}` | home limit=6；base pageNo=1/pageSize=20 | 公开精选卡/分页详情，非一般会话绕过owner接口；online/offline语义保持 |

### 1.2 HITL 接口

`/api/agent/ask-user`：POST `/answer` `{questionId,answers:Record<string,string>}`；GET `/pending?sessionId=...`；POST `/cancel` `{questionId}`（服务端reason固定user_cancelled）；POST SSE `/resume` `{resumeRequestId}`。

`/api/agent/plan-approval`：POST `/approve` `{approvalId,editedPlanContent?,feedback?}`；POST `/reject` `{approvalId,feedback?}`；GET `/pending?sessionId=...`；POST `/cancel` `{approvalId}`（服务端reason固定user_cancelled）；POST SSE `/resume` `{resumeRequestId}`。取消复用answer/approval VO，但Controller不读取客户端reason；完整字段以下文为准。

answer/decide只持久化，返回 `accepted,idempotent,resumeRequestId,sessionId,status,message` 等，不启动续跑；UI随后单独连接resume。重复已决返回同resumeRequestId，不能重新分配。resume校验visitor/session→DB CAS claim→空query continuation恢复memory/tool observation→dispatch，审批拒绝让Agent修订；取消不等于拒绝。pending列表SQL包含ANSWERED，前端用于恢复已结束卡片；hasOpen gate不算ANSWERED。依据 [AskUserQuestionApplicationService.java:23](../../Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/askuser/AskUserQuestionApplicationService.java#L23)、[PlanApprovalApplicationService.java:24](../../Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/planmode/PlanApprovalApplicationService.java#L24)、两个resume service和mapper。

## 2. SSE 线格式与业务事件

### 2.1 Java主Agent/HITL/follow

[SseEmitterAgentSessionStream.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/reactor/support/SseEmitterAgentSessionStream.java#L39) 直接发默认 SSE message 的JSON `data:`，**没有明确设置命名event、SSE id或[DONE]**。事件名称主要位于JSON `packageType`、`resultMap.eventData.messageType` 与嵌套 `resultMap.messageType`；不能误迁为必须监听 `event:tool_call`。

[GptProcessResult.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/response/GptProcessResult.java#L18) 字段：status、response/responseAll（默认空串）、finished(boolean)、useTimes/useTokens(long)、resultMap、responseType（对象缺省markdown，handler常置text）、traceId、reqId、encrypted、query、messages、packageType（缺省result）、errorMsg、eventSeq(long缺省0)、retryMs(nullable)。P0 rawHTTP已确认缺省Jackson输出null，见[fixture](fixtures/java-behavior.json) serialization/http；Java Builder与字段初值不总一致，已见编译警告，不能用dataclass默认值猜测所有包。

resultMap常含 `agentType,multiAgent,eventData`；eventData是canonical projector产物，含taskId/taskOrder/messageId/messageType/messageOrder/resultMap，嵌套payload的messageType才是具体tool/research/GenUI类型。plan_thought/初次plan有顶层类型，很多工具与后续plan被包装为task。[BaseAgentResponseHandler.java:29](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/handler/BaseAgentResponseHandler.java#L29) 共享 [ReplayProjector.java:28](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/ledger/replay/ReplayProjector.java#L28) 的eventData，但**实时agentType不被history marker覆盖**。

| 业务类型/控制包 | 内容与顺序/结束约束 |
| --- | --- |
| packageType heartbeat | finished=false、status=success、空response/responseAll、0times/tokens、reqId、encrypted=false；默认10s；不进128帧缓冲，不递增业务eventSeq |
| packageType follow_idle | finished=true、status=success、空文本；发送后EOF，不表示再执行一次 |
| packageType follow_pending | finished=false、retryMs常800；registry仍缺且ledger RUNNING，park每200ms最多50ticks后提示并EOF；客户端退避follow |
| plan_thought / plan / task / tool_thought / llm_reasoning | task/order/plannerRoundId、增量isFinal；具体层级保持 |
| tool_call_delta / tool_call / tool_result | 调用ID/name/params/status/dispatchIndex和结果字段、父子来源；先登记和running，再最终输出；无要求并行工具按启动顺序完成 |
| ask_user_question / plan_approval / plan_mode_entered | 对应questionId/approvalId、原toolCallId、questions/plan/status、RunA让步；sole-tool约束；进入等待不是网络故障 |
| subagent_progress / agent_stream / session_tasks / user_inject / llm_retry | 子身份/父工具关系、任务快照、指导/重试提示；不混成最终回答 |
| browser / code / html / markdown / ppt / file / knowledge / deep_search / data_analysis | 旧payload/source/file协议；deep_search内层extend/search/report |
| ui_tree / ui_patch | tree envelope或patches、canvas_id/seq、toolCallId/toolName/isFinal；rich output事实保存后可历史重建 |
| result / task_summary / stream_settle | 根result业务结论，不必马上EOF；有后台任务要延迟finished/关流；子result不能结束根；stream_settle在父turn已closed且后台idle时收口 |

所有AgentResponse投影在一个串行锁内产生单调eventSeq，rebind补发seq大于cursor的最近128非heartbeat帧。浏览器get event.id钩子存在，但实际主流没有SSE id，UI也保存payload eventSeq。不能要求客户端只用Last-Event-ID header续流。

[querySSE.ts:47](../../ui/src/utils/querySSE.ts#L47) 默认retryOnError=false，隐藏tab仍保持连接，abort不报错误。[useConversationStream.ts:227](../../ui/src/components/ChatView/useConversationStream.ts#L227) 在EOF/error、history/activeRun/pending恢复后用follow续绑，不能重发初始query；等待输入流正常EOF不发follow。完整运行关闭由应用完成/后台settle负责，ledger/HITL终态在EOF前落库。

### 2.2 Tool SSE 不与主Agent统一

[tool.py:67](../../reactor-tool/reactor_tool/api/tool.py#L67) 的deepsearch/code_interpreter/mragQuery等使用sse-starlette，常以data `[DONE]` 结束；有自己的JSON stage帧，mrag stage/最终答案/history写入与异常帧独立。DeepSearch至少extend/search/report，实际还包括章节中间事件，不删未知字段。主Agent的remote stream adapter读取这些帧再投影成旧Agent协议，**不将Tool [DONE]原样作为主Agent结束**。`/data/chatQuery`保持原数据query流结构，通过 [DataAgentQueryServiceImpl.java:52](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/rag/DataAgentQueryServiceImpl.java#L52) 对照，不硬套主Agent三段事件。

## 3. 状态、并发、ID与幂等

[ExecutionLedgerConstants.java:8](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/ledger/model/ExecutionLedgerConstants.java#L8)：RUNNING=0、SUCCESS=1、FAILED=2、TIMEOUT=3、STOPPED=4、WAITING_INPUT=5。history外层大写标签；SSE status多用小写running/success/failed；不能统一大小写或枚举数值。

HITL：`PENDING → RESUME_PENDING → RESUMING → ANSWERED`，另有FAILED、TIMEOUT、CANCELLED。decide/answer CAS要求PENDING，claim只允许RESUME_PENDING，markAnswered只更新RESUMING；cancelable仅PENDING/RESUME_PENDING。expires_at存在但CAS没有过期条件，不承诺后台expiry sweep（差异D12）。dispatch executor拒绝退回RESUME_PENDING；执行出错标FAILED；同visitor原single-run guard错误需要结构化terminal frame，不能把并发拒绝当上游瞬态重试。

同访客进程内single-run，不同visitor并发。浏览器断开只detach，不cancel。显式stop取消pending/后台、写STOPPED，底层HTTP/工具及时中断能力按原适配实现；后台任务持久化+进程内Future跨turn共享，首次hydrate的running孤儿转failed，原因 `interrupted by process restart`。mailbox仅session+agent进程内FIFO。详情与边界见architecture。

ID：sessionId由前端请求/旧数据保留；requestId是真实Run控制键，traceId不替换；数据库run_id是数值PK，run_uid另唯一；LLM invocation_seq、tool_call_id、dispatch_index与父tool_call/subAgentId关联；HITL保存source_run_id/source_request_id/tool_invocation_id/tool_call_id/resume_request_id，RunB为新requestId（resume_...）。TaskCreate的Todo taskId、后台task_id、child agentId、UI task/message/plannerRoundId各有职责，不能统一UUID取代原ID关系。

unique约束见存储索引。普通query重复requestId没有完整exactly-once保证：registry begin会覆盖，DB request_id唯一，前端禁止自动重POST。应冻结原重复query结果并记录缺口，**不得因HITL CAS成功而宣称所有接口都幂等**。

### 模型失败策略（确定性契约）

默认最多额外重试5次（总6次），退避起点500ms、上限4000ms；同步/聚合调用加抖动，流式调用使用Reactor backoff。HTTP瞬态集合为408/409/425/429/500/502/503/504/520/521/522/523/524/525/527；网络中断、超时、空body/截断JSON等按异常链分类；证书验证/hostname/协议配置错误优先排除。已发出首chunk的可见流禁止透明重开；内部聚合流失败可丢弃部分结果后重试。备用模型链保留调用位置与账本，允许瞬态、空响应及认证/证书失败进入备用链，上下文过长和用户取消不进入。空streaming askTool另有一次非流式补救；不得叠加SDK默认重试改变次数。权威实现：[LlmRequestRetry.java:33](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/llm/LlmRequestRetry.java#L33)、[LlmModelFallback.java:21](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/llm/LlmModelFallback.java#L21)、[LLM.java:1](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/llm/LLM.java#L1)。

## 4. 工具和MCP契约

模型可见工具名大小写完全保持：`Agent`、`AskUserQuestion`、`ToolSearch`、`WebSearch`、`WebFetch`、`TaskCreate`等不可全部转snake_case；普通config的search/web_search/image_generation等选择器也不等于wire工具名。工厂有能力组和条件挂载，类存在不证明默认已暴露，尤其旧 `mcp_tool` wrapper与CodeInterpreterTool需按实际工厂分支核实（[AgentToolCollectionFactory.java:105](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/factory/AgentToolCollectionFactory.java#L105)）。完整源码名称/参数索引在附录。

参数schema以各 `toParams()`/文本JSON常量为基线，required、items、enum、aliases、缺省与运行实际验证分别记录：AskUserQuestion schema声明1–4问题，每题question/header/options，2–4label/description、multiSelect；实现normalize只截问题数且不是完整schema验证。`ExitPlanMode` plan/planFilePath、`Agent` description/prompt/subagent_type/resume_agent_id/run_in_background、`SendMessage` to/message/summary、`code_execution` source/inputs/files/fileNames/timeoutSeconds/memoryBytes/importTier/resetWorkspace/workspaceFile 等保留。完整嵌套与description不从静态字段摘要臆造；P0导出真实目录快照用于逐项JSON比较。

[ToolResultPayload.java:20](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/ToolResultPayload.java#L20) 区分toolResult原文、llmObservation、llmData、structuredOutput、base64Image/imageMimeType、failed/errorMsg；成功 `{tool,ok:true,...}`；softFailData可ok=false且failed=false，failureFrom保留error/detail；不能把所有返回值string化或将业务否决改异常。[ToolObservationSerializer.java:19](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/ToolObservationSerializer.java#L19) 生成模型observation，structured output驱动专用表/history；文件/tool artifact source必须保留。

MCP：SSE、STDIO、streamable_http（三种实际常量；schema旧注释仅sse/stdio已过时）。[McpServerDescriptor.java:22](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/mcp/runtime/McpServerDescriptor.java#L22) / [McpRegistry.java:38](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/mcp/runtime/McpRegistry.java#L38) 保存command/args/env、URL/endpoint/headers、request timeout与resource/tool发现；stdio串行锁不能遗漏，连接/子进程shutdown要对等。模型工具名 `mcp__{normalizedServer}__{normalizedTool}`，段非ASCII字母数字_-变_并截64，wire `tools/call`仍原始名字（[McpToolNamePolicy.java:9](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/mcp/runtime/McpToolNamePolicy.java#L9)）。ToolSearch keyword或select:name激活schema，alwaysLoad例外，session/task scoped catalog不能串会话；ListMcpResources/ReadMcpResource也保留。

## 5. GenUI、文件与产物

GenUI：tree可object或JSON string，envelope/root/nested tree/bare node均规范化为 `{schemaVersion:"1",root:{kind,nodeId?,props,children?}}`；kind/type alias与props提升规则保持，组件catalog/白名单由Java+UI共同定义。默认深度24、节点200。patch array非空、最多200，只add/replace/remove，path须以/起始RFC6901指针，add/replace必须value、remove不保留value；可选canvas_id与非负整数seq的真实schema/校验分别对照。[GenUiSchema.java:19](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/GenUiSchema.java#L19) / [EmitUiPatchTool.java:25](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/EmitUiPatchTool.java#L25)。

原UI [genuiState.ts:35](../../ui/src/utils/chat/genuiState.ts#L35) 当前从同task组最新ui_tree合并patch，保留originalTree/appliedPatches；不能假设canvas_id是全局唯一树仓库，更不能用服务端新增树状态替代历史tool事实。action send_message/open_url/submit_form/patch_ui 与legacy actionId走 [genUiActionBus.ts:9](../../ui/src/components/genui/genUiActionBus.ts#L9)；ThreeJsFrame脚本/Model3D加载与iframe规则保持。

文件：MySQL artifact只记录身份/关联/metadata，Python SQLite `fileinfo`索引磁盘文件。`/preview/{file_id}/{file_name:path}`、`/download/...` 的路径file_id实际request_id/经常sessionId，不能改成SQL数值PK。[protocal.py:97](../../reactor-tool/reactor_tool/model/protocal.py#L97) 是MD5(request_id+normalize后的相对路径/文件名)，兼容legacy MD5原名；先relative再basename再legacy lookup。Unicode、斜杠、嵌套资源/下载URL保留。

响应metadata含fileName/name、requestId、ossUrl/domainUrl/downloadUrl/previewUrl/url、size/mimeType等，接口不同不做统一改名。预览md text/markdown、glb model/gltf-binary、gltf model/gltf+json；未知attachment、404纯 `File not found`；HTML preview按需注入Three runtime，但download原文件不变（[file_manage.py:50](../../reactor-tool/reactor_tool/api/file_manage.py#L50)）。文件URL分public/internal，不能把本地路径当domainUrl。

Canvas发布真实workspace html_path并注册artifact，路径净化/资源访问保留；GenUI显式导出PDF/DOCX与Agent文档生成是不同入口；图片主链路server model、images/edits/mask/n/size、fallback、参考附件解析、workspace/agent request_source及上传产物关联全保留。

## 6. 身份和权限契约及缺口

访客cookie缺省 `ai_agent_visitor_token`，HttpOnly/secure=true、SameSite=Lax、path=/、365days（运行profile可能覆盖），raw token服务器仅持digest。token算法、既有visitor_id及session owner不变；不接受客户端user/X-Device-Id替代owner。Session首次访问绑定，既有空owner的历史可首次绑定，其他visitor拒绝；existing detail不创建缺失session。CORS允许credentials、允许来源列表与context-path处理见 [BaseFilterConfig.java:26](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/config/BaseFilterConfig.java#L26) / [VisitorIdentityFilter.java:23](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/visitor/VisitorIdentityFilter.java#L23) / [AnonymousVisitorApplicationService.java:19](../../Reactor-agent-case/src/main/java/org/wwz/ai/application/agent/visitor/AnonymousVisitorApplicationService.java#L19)。

当前保护并不完整：follow做ownership；stop/inject只比可选sessionId；capabilities/生图/genui不在filter路径清单；tool文件/MRAG未见owner校验。admin login/validate-login不建立auth session，源码未找到全管理端统一鉴权，UI request也无admin credential注入。workspace路径normalize+startsWith不防symlink；虚拟skills写可访问全局库。用户要求权限隔离优先，**这些是迁移决策/验收缺口，不是已满足的兼容保证**；补拒绝行为/身份协议之前需确认具体方案，仓库外网关权限仍需证据。

## 7. 持久化契约

MySQL表/列/默认/索引以 [schema.sql:1](../../Reactor-agent-app/src/main/resources/db/schema.sql#L1) 与MyBatis mapper为参考，live DDL实际版本需授权副本确认。使用全部当前config/admin/visitor/session/run/LLM/tool/HITL/artifact/working_memory/ltm/todo/background/featured/专用tool_output表；不能只保留聊天messages。retired planning/script/report/file输出表和agent flow/schedule已在旧DROP脚本退役，不再新建。

执行账本是用户可见历史事实源，working memory是下一轮prompt投影；MRAG历史SQLite是独立工作区问答；session Todo/background是任务面，不改装成LLM事实。保留unique/upsert/soft-deleted、事务条件/affected rows、visit ownership与new-run统计。record run/LLM/tool start与finish的具体SQL边界参考repository和mapper，不在DB事务中跨await整个模型调用。

字符编码utf8mb4（表collation不完全相同）、本地DATETIME/时区、BIGINT/Decimal、JSON空值/嵌套、长度限制和serializer差异必须对照验证。文件本身、SQLite、MySQL artifact不是同一事务；旧文件绝对路径与public URL配置必须继续可解析。任何需要DDL/路径调整的操作采用plan中的备份、加法迁移、验证、回滚，不清库。

## 8. 静态索引的使用限制

以下附录由当前源码提取：所有Java HTTP映射与参数/返回类型、Python已挂载路由、核心DTO字段、工具名称/schema位置与字段摘要、MySQL表字段/unique键。它们提供**可复核源码位置**，不是“所有响应已抓包”“全部schema已执行”或“所有数据库已验证”。P0须将动态工厂schema、rawHTTP错误/空值、真实副本DDL补成机器可执行fixture。

## 附录 A：Java HTTP 全映射

共108个方法映射；不包含自动OPTIONS和Spring框架error端点。参数列保留源码annotation/default及DTO类型，DTO字段见附录C。

| 方法/完整路径 | 绑定参数 | 返回类型 | 实现位置 |
| --- | --- | --- | --- |
| 任意（未限定） `/web/health` | `—` | `ResponseEntity&lt;String&gt;` | [AiAgentController.java:48](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/AiAgentController.java#L48) |
| 任意（未限定） `/web/api/v1/gpt/queryAgentStreamIncr` | `@RequestBody GptQueryReq params` | `SseEmitter` | [AiAgentController.java:61](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/AiAgentController.java#L61) |
| POST `/api/v1/admin/admin-user/create` | `@RequestBody AdminUserRequestDTO request` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:43](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L43) |
| PUT `/api/v1/admin/admin-user/update-by-id` | `@RequestBody AdminUserRequestDTO request` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:72](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L72) |
| PUT `/api/v1/admin/admin-user/update-by-user-id` | `@RequestBody AdminUserRequestDTO request` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:107](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L107) |
| DELETE `/api/v1/admin/admin-user/delete-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:142](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L142) |
| DELETE `/api/v1/admin/admin-user/delete-by-user-id/{userId}` | `@PathVariable("userId") String userId` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:165](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L165) |
| GET `/api/v1/admin/admin-user/query-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;AdminUserResponseDTO&gt;` | [AdminUserAdminController.java:188](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L188) |
| GET `/api/v1/admin/admin-user/query-by-user-id/{userId}` | `@PathVariable("userId") String userId` | `Response&lt;AdminUserResponseDTO&gt;` | [AdminUserAdminController.java:220](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L220) |
| GET `/api/v1/admin/admin-user/query-by-username/{username}` | `@PathVariable("username") String username` | `Response&lt;AdminUserResponseDTO&gt;` | [AdminUserAdminController.java:252](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L252) |
| GET `/api/v1/admin/admin-user/query-enabled` | `—` | `Response&lt;List&lt;AdminUserResponseDTO&gt;&gt;` | [AdminUserAdminController.java:284](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L284) |
| GET `/api/v1/admin/admin-user/query-by-status/{status}` | `@PathVariable("status") Integer status` | `Response&lt;List&lt;AdminUserResponseDTO&gt;&gt;` | [AdminUserAdminController.java:310](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L310) |
| POST `/api/v1/admin/admin-user/query-list` | `@RequestBody AdminUserQueryRequestDTO request` | `Response&lt;List&lt;AdminUserResponseDTO&gt;&gt;` | [AdminUserAdminController.java:336](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L336) |
| GET `/api/v1/admin/admin-user/query-all` | `—` | `Response&lt;List&lt;AdminUserResponseDTO&gt;&gt;` | [AdminUserAdminController.java:390](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L390) |
| POST `/api/v1/admin/admin-user/login` | `@RequestBody AdminUserLoginRequestDTO request` | `Response&lt;AdminUserResponseDTO&gt;` | [AdminUserAdminController.java:416](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L416) |
| POST `/api/v1/admin/admin-user/validate-login` | `@RequestBody AdminUserLoginRequestDTO request` | `Response&lt;Boolean&gt;` | [AdminUserAdminController.java:466](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AdminUserAdminController.java#L466) |
| POST `/api/v1/admin/ai-client-api/create` | `@RequestBody AiClientApiRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientApiAdminController.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L39) |
| PUT `/api/v1/admin/ai-client-api/update-by-id` | `@RequestBody AiClientApiRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientApiAdminController.java:70](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L70) |
| PUT `/api/v1/admin/ai-client-api/update-by-api-id` | `@RequestBody AiClientApiRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientApiAdminController.java:108](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L108) |
| DELETE `/api/v1/admin/ai-client-api/delete-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;Boolean&gt;` | [AiClientApiAdminController.java:146](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L146) |
| DELETE `/api/v1/admin/ai-client-api/delete-by-api-id/{apiId}` | `@PathVariable("apiId") String apiId` | `Response&lt;Boolean&gt;` | [AiClientApiAdminController.java:172](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L172) |
| GET `/api/v1/admin/ai-client-api/query-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;AiClientApiResponseDTO&gt;` | [AiClientApiAdminController.java:205](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L205) |
| GET `/api/v1/admin/ai-client-api/query-by-api-id/{apiId}` | `@PathVariable("apiId") String apiId` | `Response&lt;AiClientApiResponseDTO&gt;` | [AiClientApiAdminController.java:239](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L239) |
| GET `/api/v1/admin/ai-client-api/query-enabled` | `—` | `Response&lt;List&lt;AiClientApiResponseDTO&gt;&gt;` | [AiClientApiAdminController.java:273](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L273) |
| POST `/api/v1/admin/ai-client-api/query-list` | `@RequestBody AiClientApiQueryRequestDTO request` | `Response&lt;List&lt;AiClientApiResponseDTO&gt;&gt;` | [AiClientApiAdminController.java:301](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L301) |
| GET `/api/v1/admin/ai-client-api/query-all` | `—` | `Response&lt;List&lt;AiClientApiResponseDTO&gt;&gt;` | [AiClientApiAdminController.java:357](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientApiAdminController.java#L357) |
| POST `/api/v1/admin/ai-client-model/test/{modelId}` | `@PathVariable("modelId") String modelId` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AiClientModelAdminController.java:53](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L53) |
| POST `/api/v1/admin/ai-client-model/test-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AiClientModelAdminController.java:58](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L58) |
| POST `/api/v1/admin/ai-client-model/create` | `@RequestBody AiClientModelRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientModelAdminController.java:101](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L101) |
| PUT `/api/v1/admin/ai-client-model/update-by-id` | `@RequestBody AiClientModelRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientModelAdminController.java:132](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L132) |
| PUT `/api/v1/admin/ai-client-model/update-by-model-id` | `@RequestBody AiClientModelRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientModelAdminController.java:170](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L170) |
| DELETE `/api/v1/admin/ai-client-model/delete-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;Boolean&gt;` | [AiClientModelAdminController.java:220](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L220) |
| DELETE `/api/v1/admin/ai-client-model/delete-by-model-id/{modelId}` | `@PathVariable("modelId") String modelId` | `Response&lt;Boolean&gt;` | [AiClientModelAdminController.java:246](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L246) |
| GET `/api/v1/admin/ai-client-model/query-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;AiClientModelResponseDTO&gt;` | [AiClientModelAdminController.java:287](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L287) |
| GET `/api/v1/admin/ai-client-model/query-by-model-id/{modelId}` | `@PathVariable("modelId") String modelId` | `Response&lt;AiClientModelResponseDTO&gt;` | [AiClientModelAdminController.java:321](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L321) |
| GET `/api/v1/admin/ai-client-model/query-by-api-id/{apiId}` | `@PathVariable("apiId") String apiId` | `Response&lt;List&lt;AiClientModelResponseDTO&gt;&gt;` | [AiClientModelAdminController.java:355](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L355) |
| GET `/api/v1/admin/ai-client-model/query-by-model-type/{modelType}` | `@PathVariable("modelType") String modelType` | `Response&lt;List&lt;AiClientModelResponseDTO&gt;&gt;` | [AiClientModelAdminController.java:383](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L383) |
| GET `/api/v1/admin/ai-client-model/query-enabled` | `—` | `Response&lt;List&lt;AiClientModelResponseDTO&gt;&gt;` | [AiClientModelAdminController.java:411](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L411) |
| POST `/api/v1/admin/ai-client-model/query-list` | `@RequestBody AiClientModelQueryRequestDTO request` | `Response&lt;List&lt;AiClientModelResponseDTO&gt;&gt;` | [AiClientModelAdminController.java:439](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L439) |
| GET `/api/v1/admin/ai-client-model/query-all` | `—` | `Response&lt;List&lt;AiClientModelResponseDTO&gt;&gt;` | [AiClientModelAdminController.java:484](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientModelAdminController.java#L484) |
| POST `/api/v1/admin/ai-client-tool-mcp/create` | `@RequestBody AiClientToolMcpRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientToolMcpAdminController.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L39) |
| PUT `/api/v1/admin/ai-client-tool-mcp/update-by-id` | `@RequestBody AiClientToolMcpRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientToolMcpAdminController.java:70](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L70) |
| PUT `/api/v1/admin/ai-client-tool-mcp/update-by-mcp-id` | `@RequestBody AiClientToolMcpRequestDTO request` | `Response&lt;Boolean&gt;` | [AiClientToolMcpAdminController.java:108](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L108) |
| DELETE `/api/v1/admin/ai-client-tool-mcp/delete-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;Boolean&gt;` | [AiClientToolMcpAdminController.java:146](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L146) |
| DELETE `/api/v1/admin/ai-client-tool-mcp/delete-by-mcp-id/{mcpId}` | `@PathVariable("mcpId") String mcpId` | `Response&lt;Boolean&gt;` | [AiClientToolMcpAdminController.java:172](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L172) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-by-id/{id}` | `@PathVariable("id") Long id` | `Response&lt;AiClientToolMcpResponseDTO&gt;` | [AiClientToolMcpAdminController.java:198](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L198) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-by-mcp-id/{mcpId}` | `@PathVariable("mcpId") String mcpId` | `Response&lt;AiClientToolMcpResponseDTO&gt;` | [AiClientToolMcpAdminController.java:231](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L231) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-all` | `—` | `Response&lt;List&lt;AiClientToolMcpResponseDTO&gt;&gt;` | [AiClientToolMcpAdminController.java:264](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L264) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-by-status/{status}` | `@PathVariable("status") Integer status` | `Response&lt;List&lt;AiClientToolMcpResponseDTO&gt;&gt;` | [AiClientToolMcpAdminController.java:291](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L291) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-by-transport-type/{transportType}` | `@PathVariable("transportType") String transportType` | `Response&lt;List&lt;AiClientToolMcpResponseDTO&gt;&gt;` | [AiClientToolMcpAdminController.java:318](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L318) |
| GET `/api/v1/admin/ai-client-tool-mcp/query-enabled` | `—` | `Response&lt;List&lt;AiClientToolMcpResponseDTO&gt;&gt;` | [AiClientToolMcpAdminController.java:345](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L345) |
| POST `/api/v1/admin/ai-client-tool-mcp/query-list` | `@RequestBody AiClientToolMcpQueryRequestDTO request` | `Response&lt;List&lt;AiClientToolMcpResponseDTO&gt;&gt;` | [AiClientToolMcpAdminController.java:372](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/AiClientToolMcpAdminController.java#L372) |
| POST `/api/v1/admin/featured-conversations/create` | `@RequestBody FeaturedConversationAdminUpsertReqVO request` | `Response&lt;Boolean&gt;` | [FeaturedConversationAdminController.java:41](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java#L41) |
| PUT `/api/v1/admin/featured-conversations/update` | `@RequestBody FeaturedConversationAdminUpsertReqVO request` | `Response&lt;Boolean&gt;` | [FeaturedConversationAdminController.java:47](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java#L47) |
| POST `/api/v1/admin/featured-conversations/online/{featuredId}` | `@PathVariable("featuredId") String featuredId, @RequestParam("operator") String operator` | `Response&lt;Boolean&gt;` | [FeaturedConversationAdminController.java:52](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java#L52) |
| POST `/api/v1/admin/featured-conversations/offline/{featuredId}` | `@PathVariable("featuredId") String featuredId, @RequestParam("operator") String operator` | `Response&lt;Boolean&gt;` | [FeaturedConversationAdminController.java:61](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java#L61) |
| POST `/api/v1/admin/featured-conversations/query-list` | `@RequestBody FeaturedConversationAdminQueryReqVO request` | `Response&lt;PageRespVO&lt;FeaturedConversationAdminRespVO&gt;&gt;` | [FeaturedConversationAdminController.java:69](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/FeaturedConversationAdminController.java#L69) |
| GET `/api/v1/admin/skills/list` | `—` | `Response&lt;List&lt;Map&lt;String, Object&gt;&gt;&gt;` | [SkillAdminController.java:41](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L41) |
| POST `/api/v1/admin/skills/parse-package` | `@RequestPart("file") MultipartFile file` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [SkillAdminController.java:46](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L46) |
| POST `/api/v1/admin/skills/upload` | `@RequestPart("file") MultipartFile file, @RequestParam(value = "replace", defaultValue = "false") boolean replace` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [SkillAdminController.java:55](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L55) |
| POST `/api/v1/admin/skills/create` | `@RequestBody CreateSkillBody body` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [SkillAdminController.java:70](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L70) |
| POST `/api/v1/admin/skills/import-url` | `@RequestBody ImportUrlBody body` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [SkillAdminController.java:83](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L83) |
| DELETE `/api/v1/admin/skills/{name}` | `@PathVariable("name") String name` | `Response&lt;Boolean&gt;` | [SkillAdminController.java:94](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L94) |
| POST `/api/v1/admin/skills/reload` | `—` | `Response&lt;Boolean&gt;` | [SkillAdminController.java:103](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SkillAdminController.java#L103) |
| GET `/api/v1/admin/sub-agent-definitions/query-list` | `—` | `Response&lt;List&lt;SubAgentDefinitionRespVO&gt;&gt;` | [SubAgentDefinitionAdminController.java:45](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L45) |
| GET `/api/v1/admin/sub-agent-definitions/tool-catalog` | `—` | `Response&lt;List&lt;String&gt;&gt;` | [SubAgentDefinitionAdminController.java:55](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L55) |
| GET `/api/v1/admin/sub-agent-definitions/{agentKey}` | `@PathVariable("agentKey") String agentKey` | `Response&lt;SubAgentDefinitionRespVO&gt;` | [SubAgentDefinitionAdminController.java:128](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L128) |
| POST `/api/v1/admin/sub-agent-definitions/create` | `@RequestBody SubAgentDefinitionUpsertReqVO request` | `Response&lt;Boolean&gt;` | [SubAgentDefinitionAdminController.java:139](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L139) |
| PUT `/api/v1/admin/sub-agent-definitions/update` | `@RequestBody SubAgentDefinitionUpsertReqVO request` | `Response&lt;Boolean&gt;` | [SubAgentDefinitionAdminController.java:149](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L149) |
| DELETE `/api/v1/admin/sub-agent-definitions/{agentKey}` | `@PathVariable("agentKey") String agentKey` | `Response&lt;Boolean&gt;` | [SubAgentDefinitionAdminController.java:158](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L158) |
| DELETE `/api/v1/admin/sub-agent-definitions/delete` | `@RequestParam("agentKey") String agentKey` | `Response&lt;Boolean&gt;` | [SubAgentDefinitionAdminController.java:163](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L163) |
| POST `/api/v1/admin/sub-agent-definitions/reload` | `—` | `Response&lt;Integer&gt;` | [SubAgentDefinitionAdminController.java:176](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/admin/SubAgentDefinitionAdminController.java#L176) |
| POST `/api/agent/ask-user/answer` | `@RequestBody AskUserAnswerReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentAskUserController.java:50](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentAskUserController.java#L50) |
| POST `/api/agent/ask-user/resume` | `@RequestBody AskUserResumeReqVO req` | `SseEmitter` | [AgentAskUserController.java:77](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentAskUserController.java#L77) |
| GET `/api/agent/ask-user/pending` | `@RequestParam("sessionId") String sessionId` | `Response&lt;List&lt;Map&lt;String, Object&gt;&gt;&gt;` | [AgentAskUserController.java:107](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentAskUserController.java#L107) |
| POST `/api/agent/ask-user/cancel` | `@RequestBody AskUserAnswerReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentAskUserController.java:124](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentAskUserController.java#L124) |
| GET `/api/agent/conversation/sessions` | `@RequestParam(name = "limit", defaultValue = "20") Integer limit` | `Response&lt;List&lt;ConversationSessionRespVO&gt;&gt;` | [AgentConversationHistoryController.java:41](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentConversationHistoryController.java#L41) |
| GET `/api/agent/conversation/sessions/{sessionId}` | `@PathVariable("sessionId") String sessionId` | `Response&lt;ConversationHistoryDetailRespVO&gt;` | [AgentConversationHistoryController.java:57](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentConversationHistoryController.java#L57) |
| GET `/api/agent/featured-conversations/home` | `@RequestParam(name = "limit", defaultValue = "6") Integer limit` | `Response&lt;List&lt;FeaturedConversationCardRespVO&gt;&gt;` | [AgentFeaturedConversationController.java:36](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFeaturedConversationController.java#L36) |
| GET `/api/agent/featured-conversations` | `@RequestParam(name = "pageNo", defaultValue = "1") Integer pageNo, @RequestParam(name = "pageSize", defaultValue = "20") Integer pageSize` | `Response&lt;PageRespVO&lt;FeaturedConversationCardRespVO&gt;&gt;` | [AgentFeaturedConversationController.java:52](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFeaturedConversationController.java#L52) |
| GET `/api/agent/featured-conversations/{featuredId}` | `@PathVariable("featuredId") String featuredId` | `Response&lt;FeaturedConversationDetailRespVO&gt;` | [AgentFeaturedConversationController.java:78](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFeaturedConversationController.java#L78) |
| POST `/api/agent/file/upload` | `@RequestParam("sessionId") String sessionId, @RequestParam("file") MultipartFile file` | `Response&lt;AgentFileUploadRespVO&gt;` | [AgentFileController.java:30](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentFileController.java#L30) |
| POST `/api/agent/genui/export/pdf` | `@RequestBody Map&lt;String, Object&gt; body` | `ResponseEntity&lt;?&gt;` | [AgentGenUiExportController.java:29](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentGenUiExportController.java#L29) |
| POST `/api/agent/genui/export/docx` | `@RequestBody Map&lt;String, Object&gt; body` | `ResponseEntity&lt;?&gt;` | [AgentGenUiExportController.java:50](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentGenUiExportController.java#L50) |
| POST `/api/agent/image-generation/generate` | `@RequestBody WorkspaceImageGenerationReqVO reqVO` | `Response&lt;WorkspaceImageGenerationRespVO&gt;` | [AgentImageGenerationController.java:39](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentImageGenerationController.java#L39) |
| GET `/api/agent/image-generation/history` | `@RequestParam(name = "pageNo", defaultValue = "1") int pageNo, @RequestParam(name = "pageSize", defaultValue = "10") int pageSize` | `Response&lt;PageRespVO&lt;WorkspaceImageHistoryBatchRespVO&gt;&gt;` | [AgentImageGenerationController.java:88](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentImageGenerationController.java#L88) |
| POST `/api/agent/plan-approval/approve` | `@RequestBody PlanApprovalReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentPlanApprovalController.java:50](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentPlanApprovalController.java#L50) |
| POST `/api/agent/plan-approval/reject` | `@RequestBody PlanApprovalReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentPlanApprovalController.java:74](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentPlanApprovalController.java#L74) |
| POST `/api/agent/plan-approval/resume` | `@RequestBody PlanApprovalResumeReqVO req` | `SseEmitter` | [AgentPlanApprovalController.java:98](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentPlanApprovalController.java#L98) |
| GET `/api/agent/plan-approval/pending` | `@RequestParam("sessionId") String sessionId` | `Response&lt;List&lt;Map&lt;String, Object&gt;&gt;&gt;` | [AgentPlanApprovalController.java:128](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentPlanApprovalController.java#L128) |
| POST `/api/agent/plan-approval/cancel` | `@RequestBody PlanApprovalReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentPlanApprovalController.java:145](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentPlanApprovalController.java#L145) |
| POST `/api/agent/run/stop` | `@RequestBody AgentRunStopReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentRunController.java:67](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentRunController.java#L67) |
| POST `/api/agent/run/inject` | `@RequestBody AgentRunInjectReqVO req` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentRunController.java:97](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentRunController.java#L97) |
| POST `/api/agent/run/follow` | `@RequestBody AgentRunFollowReqVO req` | `SseEmitter` | [AgentRunController.java:134](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentRunController.java#L134) |
| GET `/api/agent/session/{sessionId}/capabilities` | `@PathVariable("sessionId") String sessionId` | `Response&lt;Map&lt;String, Object&gt;&gt;` | [AgentSessionCapabilityController.java:34](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentSessionCapabilityController.java#L34) |
| PUT `/api/agent/session/{sessionId}/capabilities` | `@PathVariable("sessionId") String sessionId, @RequestBody CapabilityToggleBody body` | `Response&lt;Boolean&gt;` | [AgentSessionCapabilityController.java:53](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentSessionCapabilityController.java#L53) |
| GET `/api/agent/visitor/bootstrap` | `—` | `Response&lt;VisitorBootstrapRespVO&gt;` | [AgentVisitorController.java:32](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentVisitorController.java#L32) |
| POST `/api/agent/visitor/naming` | `@RequestBody VisitorNamingReqVO request` | `Response&lt;VisitorBootstrapRespVO&gt;` | [AgentVisitorController.java:45](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentVisitorController.java#L45) |
| GET `/api/agent/workspace/{sessionId}/archive` | `@PathVariable("sessionId") String sessionId, HttpServletResponse response` | `void` | [AgentWorkspaceController.java:31](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/AgentWorkspaceController.java#L31) |
| POST `/data/queryModelInfo` | `@RequestBody JSONObject req` | `NL2SQLReq` | [DataAgentController.java:44](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L44) |
| POST `/data/vectorRecall` | `@RequestBody ColumnVectorRecallReq req` | `List&lt;Map&lt;String, Object&gt;&gt;` | [DataAgentController.java:50](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L50) |
| POST `/data/esRecall` | `@RequestBody ColumnEsRecallReq req` | `List&lt;Map&lt;String, Object&gt;&gt;` | [DataAgentController.java:56](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L56) |
| POST `/data/chatQuery` | `@RequestBody DataAgentChatReq req` | `SseEmitter` | [DataAgentController.java:62](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L62) |
| POST `/data/apiChatQuery` | `@RequestBody DataAgentChatReq req` | `List&lt;ChatQueryData&gt;` | [DataAgentController.java:75](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L75) |
| POST `/data/testQuery` | `@RequestBody DataAgentChatReq req` | `Object` | [DataAgentController.java:82](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L82) |
| POST `/data/getNl2SqlReq` | `@RequestBody DataAgentChatReq req` | `NL2SQLReq` | [DataAgentController.java:88](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L88) |
| GET `/data/allModels` | `—` | `Map&lt;String, Object&gt;` | [DataAgentController.java:93](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L93) |
| GET `/data/previewData` | `@RequestParam("modelCode") String modelCode` | `Map&lt;String, Object&gt;` | [DataAgentController.java:102](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/dataagent/DataAgentController.java#L102) |

## 附录 B：现有 Tool Runtime 已挂载路由

公网按部署前缀加`/tool`，内部路径如下。sandbox role仅bash/code_execution；api role两者为proxy，其余本地；all role全部本地。OSS utils中storage router未在当前build_api_router显式挂载，不能仅凭decorator认定公开可调用。

| 方法/内部路径 | handler / Python输入类型与默认 | 实现 |
| --- | --- | --- |
| POST `/v1/tool/code_interpreter` | `post_code_interpreter(body: CIRequest)` | [tool.py:91](../../reactor-tool/reactor_tool/api/tool.py#L91) |
| POST `/v1/tool/deepsearch` | `post_deepsearch(body: DeepSearchRequest)` | [tool.py:293](../../reactor-tool/reactor_tool/api/tool.py#L293) |
| POST `/v1/tool/web_fetch` | `post_web_fetch(body: WebFetchRequest)` | [tool.py:320](../../reactor-tool/reactor_tool/api/tool.py#L320) |
| POST `/v1/tool/embedding/text` | `post_text_embedding(body: EmbeddingProxyRequest)` | [tool.py:361](../../reactor-tool/reactor_tool/api/tool.py#L361) |
| POST `/v1/tool/table_rag` | `post_table_rag(body: TableRAGRequest)` | [tool.py:385](../../reactor-tool/reactor_tool/api/tool.py#L385) |
| POST `/v1/tool/cal_engine` | `cal_engine(body: CalEngineRequest)` | [tool.py:421](../../reactor-tool/reactor_tool/api/tool.py#L421) |
| POST `/v1/tool/auto_analysis` | `auto_analysis(body: AutoAnalysisRequest)` | [tool.py:445](../../reactor-tool/reactor_tool/api/tool.py#L445) |
| POST `/v1/tool/nl2sql` | `post_nl2sql(body: NL2SQLRequest)` | [tool.py:496](../../reactor-tool/reactor_tool/api/tool.py#L496) |
| POST `/v1/tool/sopRecall` | `post_sop_recall(body: SopChooseRequest)` | [tool.py:546](../../reactor-tool/reactor_tool/api/tool.py#L546) |
| POST `/v1/tool/script_runner` | `post_script_runner(body: ScriptRunnerRequest)` | [tool.py:566](../../reactor-tool/reactor_tool/api/tool.py#L566) |
| POST `/v1/tool/mragQuery` | `post_mrag_query(body: MultimodalRAGRequest)` | [tool.py:695](../../reactor-tool/reactor_tool/api/tool.py#L695) |
| POST `/v1/tool/document_generate` | `post_document_generate(body: DocgenRequest)` | [tool.py:868](../../reactor-tool/reactor_tool/api/tool.py#L868) |
| POST `/v1/tool/slides_generate` | `post_slides_generate(body: DocgenRequest)` | [tool.py:884](../../reactor-tool/reactor_tool/api/tool.py#L884) |
| POST `/v1/tool/excel_generator` | `post_excel_generator(body: DocgenRequest)` | [tool.py:900](../../reactor-tool/reactor_tool/api/tool.py#L900) |
| POST `/v1/tool/checklist_generate` | `post_checklist_generate(body: DocgenRequest)` | [tool.py:916](../../reactor-tool/reactor_tool/api/tool.py#L916) |
| POST `/v1/tool/template_filler` | `post_template_filler(body: DocgenRequest)` | [tool.py:932](../../reactor-tool/reactor_tool/api/tool.py#L932) |
| POST `/v1/tool/document_template` | `post_document_template(body: DocgenRequest)` | [tool.py:987](../../reactor-tool/reactor_tool/api/tool.py#L987) |
| POST `/v1/tool/theme_designer` | `post_theme_designer(body: DocgenRequest)` | [tool.py:1002](../../reactor-tool/reactor_tool/api/tool.py#L1002) |
| POST `/v1/tool/chart_generator` | `post_chart_generator(body: DocgenRequest)` | [tool.py:1017](../../reactor-tool/reactor_tool/api/tool.py#L1017) |
| POST `/v1/tool/csv_processor` | `post_csv_processor(body: DocgenRequest)` | [tool.py:1088](../../reactor-tool/reactor_tool/api/tool.py#L1088) |
| POST `/v1/tool/excel_reader` | `post_excel_reader(body: DocgenRequest)` | [tool.py:1093](../../reactor-tool/reactor_tool/api/tool.py#L1093) |
| POST `/v1/tool/html_processor` | `post_html_processor(body: DocgenRequest)` | [tool.py:1098](../../reactor-tool/reactor_tool/api/tool.py#L1098) |
| POST `/v1/tool/markdown_processor` | `post_markdown_processor(body: DocgenRequest)` | [tool.py:1103](../../reactor-tool/reactor_tool/api/tool.py#L1103) |
| POST `/v1/tool/text_processor` | `post_text_processor(body: DocgenRequest)` | [tool.py:1108](../../reactor-tool/reactor_tool/api/tool.py#L1108) |
| POST `/v1/tool/word_reader` | `post_word_reader(body: DocgenRequest)` | [tool.py:1113](../../reactor-tool/reactor_tool/api/tool.py#L1113) |
| POST `/v1/tool/pdf_reader` | `post_pdf_reader(body: DocgenRequest)` | [tool.py:1118](../../reactor-tool/reactor_tool/api/tool.py#L1118) |
| POST `/v1/tool/pdf_structure` | `post_pdf_structure(body: DocgenRequest)` | [tool.py:1123](../../reactor-tool/reactor_tool/api/tool.py#L1123) |
| POST `/v1/tool/citation_extractor` | `post_citation_extractor(body: DocgenRequest)` | [tool.py:1128](../../reactor-tool/reactor_tool/api/tool.py#L1128) |
| POST `/v1/tool/image_ocr` | `post_image_ocr(body: DocgenRequest)` | [tool.py:1133](../../reactor-tool/reactor_tool/api/tool.py#L1133) |
| POST `/v1/tool/data_aggregate` | `post_data_aggregate(body: DocgenRequest)` | [tool.py:1192](../../reactor-tool/reactor_tool/api/tool.py#L1192) |
| POST `/v1/tool/data_clean` | `post_data_clean(body: DocgenRequest)` | [tool.py:1197](../../reactor-tool/reactor_tool/api/tool.py#L1197) |
| POST `/v1/tool/data_merge` | `post_data_merge(body: DocgenRequest)` | [tool.py:1202](../../reactor-tool/reactor_tool/api/tool.py#L1202) |
| POST `/v1/tool/data_transform` | `post_data_transform(body: DocgenRequest)` | [tool.py:1207](../../reactor-tool/reactor_tool/api/tool.py#L1207) |
| POST `/v1/tool/data_validate` | `post_data_validate(body: DocgenRequest)` | [tool.py:1212](../../reactor-tool/reactor_tool/api/tool.py#L1212) |
| POST `/v1/tool/sql_query` | `post_sql_query(body: DocgenRequest)` | [tool.py:1217](../../reactor-tool/reactor_tool/api/tool.py#L1217) |
| POST `/v1/tool/twitter` | `post_twitter(body: SocialToolRequest)` | [social.py:57](../../reactor-tool/reactor_tool/api/social.py#L57) |
| POST `/v1/tool/reddit` | `post_reddit(body: SocialToolRequest)` | [social.py:63](../../reactor-tool/reactor_tool/api/social.py#L63) |
| POST `/v1/tool/xueqiu` | `post_xueqiu(body: SocialToolRequest)` | [social.py:69](../../reactor-tool/reactor_tool/api/social.py#L69) |
| POST `/v1/file_tool/get_file` | `get_file(body: FileRequest)` | [file_manage.py:103](../../reactor-tool/reactor_tool/api/file_manage.py#L103) |
| POST `/v1/file_tool/upload_file` | `upload_file(body: FileUploadRequest)` | [file_manage.py:128](../../reactor-tool/reactor_tool/api/file_manage.py#L128) |
| POST `/v1/file_tool/upload_file_data` | `upload_file_data(file: UploadFile=File(...), request_id: str=Form(alias='requestId'))` | [file_manage.py:157](../../reactor-tool/reactor_tool/api/file_manage.py#L157) |
| POST `/v1/file_tool/register_file` | `register_file(body: FileRegisterRequest)` | [file_manage.py:184](../../reactor-tool/reactor_tool/api/file_manage.py#L184) |
| POST `/v1/file_tool/get_file_list` | `get_file_list(body: FileListRequest)` | [file_manage.py:215](../../reactor-tool/reactor_tool/api/file_manage.py#L215) |
| GET `/v1/file_tool/download/{file_id}/{file_name:path}` | `download_file(file_id: str, file_name: str)` | [file_manage.py:248](../../reactor-tool/reactor_tool/api/file_manage.py#L248) |
| GET `/v1/file_tool/preview/{file_id}/{file_name:path}` | `preview_file(file_id: str, file_name: str)` | [file_manage.py:258](../../reactor-tool/reactor_tool/api/file_manage.py#L258) |
| POST `/v1/sop/list` | `list_sops(body: SopListRequest)` | [sop.py:80](../../reactor-tool/reactor_tool/api/sop.py#L80) |
| POST `/v1/sop/get` | `get_sop(body: SopGetRequest)` | [sop.py:93](../../reactor-tool/reactor_tool/api/sop.py#L93) |
| POST `/v1/sop/upsert` | `upsert_sop(body: SopUpsertRequest)` | [sop.py:106](../../reactor-tool/reactor_tool/api/sop.py#L106) |
| POST `/v1/sop/delete` | `delete_sop(body: SopDeleteRequest)` | [sop.py:124](../../reactor-tool/reactor_tool/api/sop.py#L124) |
| POST `/v1/sop/status` | `set_sop_status(body: SopStatusRequest)` | [sop.py:135](../../reactor-tool/reactor_tool/api/sop.py#L135) |
| POST `/v1/sop/recall_test` | `recall_test(body: SopRecallTestRequest)` | [sop.py:146](../../reactor-tool/reactor_tool/api/sop.py#L146) |
| POST `/v1/tool/code_execution` | `post_code_execution(body: CodeExecutionRequest)` | [sandbox_routes.py:19](../../reactor-tool/reactor_tool/api/sandbox_routes.py#L19) |
| POST `/v1/tool/bash` | `post_bash(body: BashSandboxRequest)` | [sandbox_routes.py:27](../../reactor-tool/reactor_tool/api/sandbox_routes.py#L27) |
| POST `/v1/tool/bash` | `proxy_sandbox_tool(request: Request)` | [sandbox_proxy.py:20](../../reactor-tool/reactor_tool/api/sandbox_proxy.py#L20) |
| POST `/v1/tool/code_execution` | `proxy_sandbox_tool(request: Request)` | [sandbox_proxy.py:21](../../reactor-tool/reactor_tool/api/sandbox_proxy.py#L21) |
| POST `/v1/documents/upload` | `upload_document(file: UploadFile=File(...))` | [document.py:235](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L235) |
| POST `/v1/documents/create_knowledge_base` | `create_knowledge_base(request: CreateKnowledgeBaseRequest)` | [document.py:391](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L391) |
| POST `/v1/documents/delete_knowledge_base` | `delete_knowledge_base(request: DeleteKnowledgeBaseRequest)` | [document.py:418](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L418) |
| POST `/v1/documents/list_knowledge_base` | `list_knowledge_base(request: ListKnowledgeBaseRequest)` | [document.py:451](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L451) |
| POST `/v1/documents/add_files` | `add_files(request: AddFilesRequest, background_tasks: BackgroundTasks)` | [document.py:536](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L536) |
| POST `/v1/documents/add_web_url` | `async_add_web_url(request: AddWebUrlRequest, background_tasks: BackgroundTasks)` | [document.py:627](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L627) |
| POST `/v1/documents/delete_files` | `delete_files(request: DeleteFileRequest)` | [document.py:652](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L652) |
| POST `/v1/documents/list_kb_files` | `list_kb_files(request: ListKBFilesRequest)` | [document.py:675](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L675) |
| POST `/v1/documents/get_file_full_content` | `get_file_full_content(request: GetFileFullContentRequest)` | [document.py:703](../../reactor-tool/reactor_tool/tool/mrag/api/routes/document.py#L703) |
| POST `/v1/mrag/sessions/create` | `create_session(request: CreateSessionRequest)` | [history.py:76](../../reactor-tool/reactor_tool/tool/mrag/api/routes/history.py#L76) |
| POST `/v1/mrag/sessions/list` | `list_sessions(request: ListSessionRequest)` | [history.py:95](../../reactor-tool/reactor_tool/tool/mrag/api/routes/history.py#L95) |
| POST `/v1/mrag/sessions/detail` | `session_detail(request: SessionDetailRequest)` | [history.py:107](../../reactor-tool/reactor_tool/tool/mrag/api/routes/history.py#L107) |
| POST `/v1/mrag/sessions/delete` | `delete_session(request: DeleteSessionRequest)` | [history.py:124](../../reactor-tool/reactor_tool/tool/mrag/api/routes/history.py#L124) |

## 附录 C：核心 Java HTTP DTO/VO 字段索引

类型/原始默认值来自字段声明。注解、getter、自定义convert/map、验证/例外逻辑仍按对应controller。管理配置的真实值不会写入此文档。

| 对象 | 字段（Java类型/默认） | 定义 |
| --- | --- | --- |
| `AdminUserLoginRequestDTO` | username: String; password: String | [AdminUserLoginRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AdminUserLoginRequestDTO.java#L19) |
| `AdminUserQueryRequestDTO` | userId: String; username: String; status: Integer; pageNum: Integer; pageSize: Integer | [AdminUserQueryRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AdminUserQueryRequestDTO.java#L19) |
| `AdminUserRequestDTO` | id: Long; userId: String; username: String; password: String; status: Integer | [AdminUserRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AdminUserRequestDTO.java#L19) |
| `AdminUserResponseDTO` | id: Long; userId: String; username: String; status: Integer; createTime: LocalDateTime; updateTime: LocalDateTime | [AdminUserResponseDTO.java:20](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AdminUserResponseDTO.java#L20) |
| `AiClientApiQueryRequestDTO` | apiId: String; baseUrl: String; status: Integer; pageNum: Integer; pageSize: Integer | [AiClientApiQueryRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientApiQueryRequestDTO.java#L19) |
| `AiClientApiRequestDTO` | id: Long; apiId: String; baseUrl: String; apiKey: String; completionsPath: String; embeddingsPath: String; status: Integer | [AiClientApiRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientApiRequestDTO.java#L19) |
| `AiClientApiResponseDTO` | id: Long; apiId: String; baseUrl: String; apiKey: String; completionsPath: String; embeddingsPath: String; status: Integer; createTime: LocalDateTime; updateTime: LocalDateTime | [AiClientApiResponseDTO.java:20](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientApiResponseDTO.java#L20) |
| `AiClientModelQueryRequestDTO` | modelId: String; apiId: String; modelType: String; status: Integer | [AiClientModelQueryRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientModelQueryRequestDTO.java#L19) |
| `AiClientModelRequestDTO` | id: Long; modelId: String; apiId: String; modelName: String; modelType: String; modelUsage: String; supportsThinking: Integer; contextWindow: Integer; status: Integer | [AiClientModelRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientModelRequestDTO.java#L19) |
| `AiClientModelResponseDTO` | id: Long; modelId: String; apiId: String; modelName: String; modelType: String; modelUsage: String; supportsThinking: Integer; contextWindow: Integer; status: Integer; createTime: LocalDateTime; updateTime: LocalDateTime | [AiClientModelResponseDTO.java:20](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientModelResponseDTO.java#L20) |
| `AiClientToolMcpQueryRequestDTO` | mcpId: String; mcpName: String; transportType: String; status: Integer; pageNum: Integer; pageSize: Integer | [AiClientToolMcpQueryRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientToolMcpQueryRequestDTO.java#L19) |
| `AiClientToolMcpRequestDTO` | id: Long; mcpId: String; mcpName: String; transportType: String; transportConfig: String; requestTimeout: Integer; status: Integer | [AiClientToolMcpRequestDTO.java:19](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientToolMcpRequestDTO.java#L19) |
| `AiClientToolMcpResponseDTO` | id: Long; mcpId: String; mcpName: String; transportType: String; transportConfig: String; requestTimeout: Integer; status: Integer; createTime: LocalDateTime; updateTime: LocalDateTime | [AiClientToolMcpResponseDTO.java:21](../../Reactor-agent-api/src/main/java/org/wwz/ai/api/dto/AiClientToolMcpResponseDTO.java#L21) |
| `FileInformation` | fileName: String; fileDesc: String; ossUrl: String; domainUrl: String; fileSize: Integer; fileType: String; resourceKey: String; mimeType: String; originFileName: String; originFileUrl: String; originOssUrl: String; originDomainUrl: String | [FileInformation.java:12](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/dto/FileInformation.java#L12) |
| `ImageGenerationGatewayRequest` | requestId: String; prompt: String; mode: String; fileNames: List&lt;String&gt;; maskFileNames: List&lt;String&gt;; fileName: String; fileDescription: String; model: String; size: String; n: Integer; timeoutSeconds: Integer; stream: Boolean | [ImageGenerationGatewayRequest.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/imagegeneration/ImageGenerationGatewayRequest.java#L17) |
| `DataAgentChatReq` | content: String; traceId: String | [DataAgentChatReq.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/req/DataAgentChatReq.java#L15) |
| `GptQueryReq` | query: String; sessionId: String; requestId: String; deepThink: Integer; outputStyle: String; traceId: String; user: String; model: String; thinking: Boolean; thinkingEffort: String; sessionFiles: List&lt;FileInformation&gt;; forcePlanMode: Boolean | [GptQueryReq.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/reactor/model/req/GptQueryReq.java#L18) |
| `AgentFileUploadRespVO` | name: String; url: String; type: String; size: Long; downloadUrl: String; previewUrl: String; resourceKey: String; mimeType: String; originFileName: String | [AgentFileUploadRespVO.java:12](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AgentFileUploadRespVO.java#L12) |
| `AgentRunFollowReqVO` | sessionId: String; requestId: String; lastEventSeq: long | [AgentRunFollowReqVO.java:9](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AgentRunFollowReqVO.java#L9) |
| `AgentRunInjectReqVO` | sessionId: String; requestId: String; text: String | [AgentRunInjectReqVO.java:9](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AgentRunInjectReqVO.java#L9) |
| `AgentRunStopReqVO` | sessionId: String; requestId: String | [AgentRunStopReqVO.java:9](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AgentRunStopReqVO.java#L9) |
| `ArtifactReferenceRespVO` | artifactType: String; displayName: String; relativePath: String; resourceKey: String; downloadUrl: String; previewUrl: String; fileSize: Long; mimeType: String; missing: Boolean; missingReason: String | [ArtifactReferenceRespVO.java:8](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/ArtifactReferenceRespVO.java#L8) |
| `AskUserAnswerReqVO` | questionId: String; answers: Map&lt;String, String&gt; | [AskUserAnswerReqVO.java:11](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AskUserAnswerReqVO.java#L11) |
| `AskUserResumeReqVO` | resumeRequestId: String | [AskUserResumeReqVO.java:9](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/AskUserResumeReqVO.java#L9) |
| `ConversationHistoryDetailRespVO` | sessionId: String; title: String; status: String; deepThink: Boolean; runCount: Integer; finishedRunCount: Integer; failedRunCount: Integer; startedAt: LocalDateTime; lastActiveAt: LocalDateTime; runs: List&lt;RunDetailRespVO&gt; = new ArrayList&lt;&gt;(); requestId: String; status: String; queryText: String; finalSummaryText: String; startedAt: LocalDateTime; finishedAt: LocalDateTime; contextUsage: ContextUsagePayload; replayFrames: List&lt;GptProcessResult&gt; = new ArrayList&lt;&gt;() | [ConversationHistoryDetailRespVO.java:21](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/ConversationHistoryDetailRespVO.java#L21) |
| `ConversationSessionRespVO` | sessionId: String; title: String; status: String; latestQueryText: String; runCount: Integer; finishedRunCount: Integer; failedRunCount: Integer; startedAt: LocalDateTime; lastActiveAt: LocalDateTime | [ConversationSessionRespVO.java:17](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/ConversationSessionRespVO.java#L17) |
| `FeaturedConversationCardRespVO` | featuredId: String; sessionId: String; title: String; summary: String; coverUrl: String; tags: List&lt;String&gt;; publishedAt: LocalDateTime; contentLastActiveAt: LocalDateTime | [FeaturedConversationCardRespVO.java:18](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/FeaturedConversationCardRespVO.java#L18) |
| `FeaturedConversationDetailRespVO` | featuredId: String; sessionId: String; title: String; summary: String; coverUrl: String; tags: List&lt;String&gt;; status: String; publishedAt: LocalDateTime; contentLastActiveAt: LocalDateTime; contentAvailable: Boolean; contentUnavailableReason: String; historyDetail: ConversationHistoryDetailRespVO | [FeaturedConversationDetailRespVO.java:18](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/FeaturedConversationDetailRespVO.java#L18) |
| `PageRespVO` | total: int; list: List&lt;T&gt; | [PageRespVO.java:10](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/PageRespVO.java#L10) |
| `PlanApprovalReqVO` | approvalId: String; editedPlanContent: String; feedback: String | [PlanApprovalReqVO.java:9](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/PlanApprovalReqVO.java#L9) |
| `PlanApprovalResumeReqVO` | resumeRequestId: String | [PlanApprovalResumeReqVO.java:6](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/PlanApprovalResumeReqVO.java#L6) |
| `VisitorBootstrapRespVO` | visitorId: String; username: String; named: boolean | [VisitorBootstrapRespVO.java:15](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/VisitorBootstrapRespVO.java#L15) |
| `VisitorNamingReqVO` | username: String | [VisitorNamingReqVO.java:15](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/VisitorNamingReqVO.java#L15) |
| `WorkspaceImageFileRespVO` | fileName: String; ossUrl: String; domainUrl: String; downloadUrl: String; previewUrl: String; fileSize: Long; mimeType: String | [WorkspaceImageFileRespVO.java:11](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/WorkspaceImageFileRespVO.java#L11) |
| `WorkspaceImageGenerationReqVO` | requestId: String; prompt: String; mode: String; fileNames: List&lt;String&gt;; maskFileNames: List&lt;String&gt;; fileName: String; fileDescription: String; model: String; size: String; n: Integer | [WorkspaceImageGenerationReqVO.java:11](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/WorkspaceImageGenerationReqVO.java#L11) |
| `WorkspaceImageGenerationRespVO` | data: String; fileInfo: List&lt;WorkspaceImageFileRespVO&gt;; requestId: String; mode: String; usedFallback: Boolean; rawResponse: Object | [WorkspaceImageGenerationRespVO.java:13](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/WorkspaceImageGenerationRespVO.java#L13) |
| `WorkspaceImageHistoryBatchRespVO` | requestId: String; prompt: String; mode: String; size: String; batchCount: Integer; sourceImageCount: Integer; maskImageCount: Integer; usedFallback: Boolean; createdAt: LocalDateTime; images: List&lt;WorkspaceImageFileRespVO&gt; | [WorkspaceImageHistoryBatchRespVO.java:14](../../Reactor-agent-trigger/src/main/java/org/wwz/ai/trigger/http/agent/vo/WorkspaceImageHistoryBatchRespVO.java#L14) |

## 附录 D：Java 工具源码与schema索引

范围：有`getName()`的工具类。wrapper/旧工具类单列不等于默认可见；以AgentToolCollectionFactory各分支装配为准。字段摘要不能代替完整nested JSON Schema；完整契约定位至`toParams()`，类型/items/enum/limits/description均需冻结，不擅自加required。动态schema在P0导出运行快照。

| 模型工具名 | properties摘要 / required | schema权威位置 |
| --- | --- | --- |
| `delegate.getName()` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [ContextScopedTool.java:82](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/ContextScopedTool.java#L82) |
| `Agent` | `description, prompt, subagent_type, resume_agent_id, run_in_background`；required `description, prompt` | [AgentDispatchTool.java:110](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/AgentDispatchTool.java#L110) |
| `code_execution` | `source, inputs, fileNames, files, timeoutSeconds, memoryBytes, importTier, resetWorkspace, workspaceFile`；required未在摘要提取（按源码） | [CodeExecutionTool.java:40](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/CodeExecutionTool.java#L40) |
| `code_interpreter` | `task, fileName`；required `task, fileName` | [CodeInterpreterTool.java:67](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/CodeInterpreterTool.java#L67) |
| `data_analysis` | `task, businessKnowledge, reportFileName`；required未在摘要提取（按源码） | [DataAnalysisTool.java:62](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/DataAnalysisTool.java#L62) |
| `deep_search` | `query, reportFileName`；required `query, reportFileName` | [DeepSearchTool.java:85](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/DeepSearchTool.java#L85) |
| `image_generation_tool` | `prompt, mode, fileNames, maskFileNames, size, n`；required `prompt` | [ImageGenerationTool.java:54](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/ImageGenerationTool.java#L54) |
| `memory` | `action, target, content, old_text, operations`；required `action, target` | [MemoryTool.java:47](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/MemoryTool.java#L47) |
| `multimodalagent_tool` | `question`；required `question` | [MultiModalAgent.java:95](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/MultiModalAgent.java#L95) |
| `session_search` | `query, limit, scope, role_filter, session_id, around_message_id, window`；required未在摘要提取（按源码） | [SessionSearchTool.java:53](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/SessionSearchTool.java#L53) |
| `WebFetch` | `url, prompt`；required `url, prompt` | [WebFetchTool.java:70](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/WebFetchTool.java#L70) |
| `WebSearch` | `query, allowed_domains, blocked_domains`；required `query` | [WebSearchTool.java:69](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/WebSearchTool.java#L69) |
| `canvas_publish` | `title, html_path, open_in_panel`；required `html_path` | [CanvasPublishTool.java:57](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/CanvasPublishTool.java#L57) |
| `emit_ui_patch` | `patches, canvas_id, seq`；required `patches` | [EmitUiPatchTool.java:41](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/EmitUiPatchTool.java#L41) |
| `emit_ui_tree` | `tree, canvas_id`；required `tree` | [EmitUiTreeTool.java:59](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/EmitUiTreeTool.java#L59) |
| `get_genui_guide` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [GetGenuiGuideTool.java:35](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/GetGenuiGuideTool.java#L35) |
| `get_html_canvas_guide` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [GetHtmlCanvasGuideTool.java:40](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/GetHtmlCanvasGuideTool.java#L40) |
| `list_ui_components` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [ListUiComponentsTool.java:36](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/canvas/ListUiComponentsTool.java#L36) |
| `data_aggregate` | `operation, data, source_path, group_by, aggregations, pivot_index, pivot_columns, pivot_values, pivot_aggfunc, output_format`；required未在摘要提取（按源码） | [DataAggregateTool.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/DataAggregateTool.java#L17) |
| `data_clean` | `operations, data, source_path, output_format`；required未在摘要提取（按源码） | [DataCleanTool.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/DataCleanTool.java#L17) |
| `data_merge` | `operation, how, on, left_data, right_data, left_on, right_on, datasets, axis`；required未在摘要提取（按源码） | [DataMergeTool.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/DataMergeTool.java#L17) |
| `data_transform` | `transformations, operations, data, source_path, output_format`；required未在摘要提取（按源码） | [DataTransformTool.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/DataTransformTool.java#L17) |
| `data_validate` | `schema, rules, data, source_path`；required未在摘要提取（按源码） | [DataValidateTool.java:17](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/DataValidateTool.java#L17) |
| `sql_query` | `query, tables, data, source_path, limit, explain, output_format`；required未在摘要提取（按源码） | [SqlQueryTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/dataprep/SqlQueryTool.java#L18) |
| `chart_generator` | `chart_type, data, title, x_label, y_label, theme, output_format, output_path, show_legend, stacked, fileName`；required未在摘要提取（按源码） | [ChartGeneratorTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/ChartGeneratorTool.java#L18) |
| `checklist_generate` | `output_path, format, title, description, items, groups, theme, fileName`；required未在摘要提取（按源码） | [ChecklistGenerateTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/ChecklistGenerateTool.java#L18) |
| `document_generate` | `output_path, format, content, blocks, title, subtitle, author, date, subject, keywords, theme, toc, cover, numbered_headings, justify, numbered_figures, section_pages, header, footer, watermark, page, encryption, merge_sources, fileName`；required未在摘要提取（按源码） | [DocumentGenerateTool.java:19](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/DocumentGenerateTool.java#L19) |
| `document_template` | `action, name, kind, description, content, slides, theme, variables, defaults, values, output_path, format, overwrite`；required未在摘要提取（按源码） | [DocumentTemplateTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/DocumentTemplateTool.java#L18) |
| `excel_generator` | `output_path, sheets, preset, workbook_properties, fileName`；required未在摘要提取（按源码） | [ExcelGeneratorTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/ExcelGeneratorTool.java#L18) |
| `slides_generate` | `output_path, title, subtitle, author, theme, aspect, slides, fileName`；required未在摘要提取（按源码） | [SlidesGenerateTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/SlidesGenerateTool.java#L15) |
| `template_filler` | `template_source, template_string, template_path, template_url, variables, output_path, output_format, strict_mode, fileName`；required未在摘要提取（按源码） | [TemplateFillerTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/TemplateFillerTool.java#L18) |
| `theme_designer` | `action, name, kind, primary, accent, mode, heading_font, body_font, east_asia_font, overrides, payload, dry_run`；required未在摘要提取（按源码） | [ThemeDesignerTool.java:18](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docgen/ThemeDesignerTool.java#L18) |
| `citation_extractor` | `file_path`；required未在摘要提取（按源码） | [CitationExtractorTool.java:16](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/CitationExtractorTool.java#L16) |
| `csv_processor` | `operation, file_path, output_path, delimiter, encoding, limit, offset, query, columns`；required未在摘要提取（按源码） | [CsvProcessorTool.java:16](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/CsvProcessorTool.java#L16) |
| `excel_reader` | `file_path, sheet_name, sheet_index, cell_range, has_header, output_format`；required未在摘要提取（按源码） | [ExcelReaderTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/ExcelReaderTool.java#L15) |
| `html_processor` | `operation, file_path, output_path, output_format`；required未在摘要提取（按源码） | [HtmlProcessorTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/HtmlProcessorTool.java#L15) |
| `image_ocr` | `file_path, lang, prompt`；required未在摘要提取（按源码） | [ImageOcrTool.java:16](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/ImageOcrTool.java#L16) |
| `markdown_processor` | `operation, file_path, content, output_path, heading, title, format`；required未在摘要提取（按源码） | [MarkdownProcessorTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/MarkdownProcessorTool.java#L15) |
| `pdf_reader` | `operation, file_path, start_page, end_page, query, output_path, output_dir, max_chars`；required未在摘要提取（按源码） | [PdfReaderTool.java:16](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/PdfReaderTool.java#L16) |
| `pdf_structure` | `file_path`；required未在摘要提取（按源码） | [PdfStructureTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/PdfStructureTool.java#L15) |
| `text_processor` | `operation, file_path, data, pattern, replacement, encoding, transform_type`；required未在摘要提取（按源码） | [TextProcessorTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/TextProcessorTool.java#L15) |
| `word_reader` | `file_path, extract_tables, extract_headers, preserve_structure`；required未在摘要提取（按源码） | [WordReaderTool.java:15](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/docread/WordReaderTool.java#L15) |
| `ListMcpResources` | `server`；required未在摘要提取（按源码） | [ListMcpResourcesTool.java:40](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/mcp/ListMcpResourcesTool.java#L40) |
| `ReadMcpResource` | `server, uri`；required未在摘要提取（按源码） | [ReadMcpResourceTool.java:37](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/mcp/ReadMcpResourceTool.java#L37) |
| `ToolSearch` | `query, max_results`；required `query` | [ToolSearchTool.java:46](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/mcp/ToolSearchTool.java#L46) |
| `AskUserQuestion` | `questions`；required `questions` | [AskUserQuestionTool.java:49](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/AskUserQuestionTool.java#L49) |
| `EnterPlanMode` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [EnterPlanModeTool.java:49](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/EnterPlanModeTool.java#L49) |
| `ExitPlanMode` | `plan, planFilePath`；required未在摘要提取（按源码） | [ExitPlanModeTool.java:58](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/ExitPlanModeTool.java#L58) |
| `SendMessage` | `to, message, summary`；required `to, message` | [SendMessageTool.java:42](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/SendMessageTool.java#L42) |
| `TaskCreate` | `subject, description, activeForm`；required `subject, description` | [TaskCreateTool.java:40](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskCreateTool.java#L40) |
| `TaskGet` | `taskId`；required `taskId` | [TaskGetTool.java:38](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskGetTool.java#L38) |
| `TaskList` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [TaskListTool.java:39](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskListTool.java#L39) |
| `TaskOutput` | `task_id, block, timeout`；required未在摘要提取（按源码） | [TaskOutputTool.java:43](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskOutputTool.java#L43) |
| `TaskStop` | `task_id, shell_id`；required未在摘要提取（按源码） | [TaskStopTool.java:40](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskStopTool.java#L40) |
| `TaskUpdate` | `taskId, subject, description, activeForm, status, owner, addBlocks, addBlockedBy`；required `taskId` | [TaskUpdateTool.java:42](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TaskUpdateTool.java#L42) |
| `TodoWrite` | `todos`；required `todos` | [TodoWriteTool.java:44](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/planmode/TodoWriteTool.java#L44) |
| `bash` | `command, timeout_sec`；required `command` | [BashTool.java:65](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/shell/BashTool.java#L65) |
| `skill_tool` | `skill_name`；required未在摘要提取（按源码） | [SkillTool.java:54](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/skill/SkillTool.java#L54) |
| `reddit` | `operation, query, subreddit, post_id, username, sort, time_filter, limit`；required未在摘要提取（按源码） | [RedditTool.java:25](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/social/RedditTool.java#L25) |
| `twitter` | `operation, query, tweet_id, username, limit`；required未在摘要提取（按源码） | [TwitterTool.java:25](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/social/TwitterTool.java#L25) |
| `xueqiu` | `operation, symbol, query, stock_type, limit`；required未在摘要提取（按源码） | [XueqiuTool.java:25](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/common/social/XueqiuTool.java#L25) |
| `mcp_tool` | 空schema/委托，详见定义；required未在摘要提取（按源码） | [McpTool.java:58](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/mcp/McpTool.java#L58) |
| `workspace_edit` | `path, old_string, new_string, replace_all`；required `path, old_string, new_string` | [WorkspaceEditTool.java:42](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceEditTool.java#L42) |
| `workspace_glob` | `path, pattern`；required `pattern` | [WorkspaceGlobTool.java:32](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceGlobTool.java#L32) |
| `workspace_grep` | `path, pattern, regex, case_sensitive`；required `pattern` | [WorkspaceGrepTool.java:33](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceGrepTool.java#L33) |
| `workspace_list` | `path, max_depth`；required未在摘要提取（按源码） | [WorkspaceListTool.java:31](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceListTool.java#L31) |
| `workspace_read` | `path, start_line, line_count`；required `path` | [WorkspaceReadTool.java:44](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceReadTool.java#L44) |
| `workspace_write` | `path, content`；required `path, content` | [WorkspaceWriteTool.java:36](../../Reactor-agent-domain/src/main/java/org/wwz/ai/domain/agent/runtime/tool/workspace/WorkspaceWriteTool.java#L36) |

## 附录 E：MySQL表字段与唯一约束

初始化snapshot，不代表已检查live数据库。完整column类型/default/colllation/索引在schema.sql引用处；SQL CAS/upsert/排序在mapper，必须同时遵守。

| 表 | 字段 | unique keys（除PK） | schema |
| --- | --- | --- | --- |
| `admin_user` | `id, user_id, username, password, status, create_time, update_time` | `user_id` | [schema.sql:25](../../Reactor-agent-app/src/main/resources/db/schema.sql#L25) |
| `ai_client_api` | `id, api_id, base_url, api_key, completions_path, embeddings_path, status, create_time, update_time` | `api_id` | [schema.sql:39](../../Reactor-agent-app/src/main/resources/db/schema.sql#L39) |
| `ai_client_model` | `id, model_id, api_id, model_usage, supports_thinking, context_window, model_name, model_type, status, create_time, update_time` | — | [schema.sql:54](../../Reactor-agent-app/src/main/resources/db/schema.sql#L54) |
| `ai_client_tool_mcp` | `id, mcp_id, mcp_name, transport_type, transport_config, request_timeout, status, create_time, update_time` | `mcp_id` | [schema.sql:72](../../Reactor-agent-app/src/main/resources/db/schema.sql#L72) |
| `ai_agent_session_capability` | `id, session_id, kind, ref_id, enabled, update_time` | `session_id, kind, ref_id` | [schema.sql:86](../../Reactor-agent-app/src/main/resources/db/schema.sql#L86) |
| `ai_agent_sub_agent_definition` | `id, agent_key, display_name, when_to_use, system_prompt, allowed_tools_json, disallowed_tools_json, max_steps, status, create_time, update_time, deleted` | `agent_key, deleted` | [schema.sql:98](../../Reactor-agent-app/src/main/resources/db/schema.sql#L98) |
| `chat_model_info` | `id, code, type, name, content, use_prompt, business_prompt, yn` | — | [schema.sql:116](../../Reactor-agent-app/src/main/resources/db/schema.sql#L116) |
| `chat_model_schema` | `id, model_code, column_id, column_name, column_comment, few_shot, data_type, synonyms, vector_uuid, default_recall, analyze_suggest, yn` | — | [schema.sql:128](../../Reactor-agent-app/src/main/resources/db/schema.sql#L128) |
| `sales_data` | `row_id, order_id, order_date, ship_date, ship_mode, customer_id, customer_name, segment, city, state_province, country, region, product_id, category, sub_category, product_name, sales, quantity, discount, profit` | — | [schema.sql:144](../../Reactor-agent-app/src/main/resources/db/schema.sql#L144) |
| `ai_agent_visitor_identity` | `id, visitor_id, token_digest, status, first_seen_at, last_seen_at, last_ip, last_user_agent, username, create_time, update_time, deleted` | `visitor_id`; `token_digest` | [schema.sql:167](../../Reactor-agent-app/src/main/resources/db/schema.sql#L167) |
| `ai_agent_dialogue_run` | `id, run_uid, request_id, session_id, visitor_id, entry_agent, status, query_text, final_summary_text, llm_call_count, tool_call_count, artifact_count, prompt_tokens_total, completion_tokens_total, total_tokens_total, error_code, error_msg, started_at, finished_at, duration_ms, create_time, update_time, deleted` | `run_uid`; `request_id` | [schema.sql:186](../../Reactor-agent-app/src/main/resources/db/schema.sql#L186) |
| `ai_agent_dialogue_session` | `id, session_id, visitor_id, title, status, latest_request_id, latest_query_text, latest_summary_text, run_count, finished_run_count, failed_run_count, started_at, last_active_at, create_time, update_time, deleted` | `session_id, deleted` | [schema.sql:218](../../Reactor-agent-app/src/main/resources/db/schema.sql#L218) |
| `ai_agent_llm_invocation` | `id, run_id, invocation_seq, agent_name, step_no, call_kind, streaming, model_name, response_text, reasoning_content, tool_call_count, prompt_tokens, completion_tokens, total_tokens, system_fingerprint, est_total_tokens, est_system_tokens, est_message_tokens, est_tool_tokens, message_count, tool_count, cached_prompt_tokens, prompt_text_tokens, prompt_audio_tokens, prompt_image_tokens, completion_text_tokens, completion_audio_tokens, reasoning_tokens, cache_status, cache_risk_flags, finish_reason, status, error_msg, started_at, finished_at, duration_ms, create_time, update_time, deleted` | `run_id, invocation_seq` | [schema.sql:241](../../Reactor-agent-app/src/main/resources/db/schema.sql#L241) |
| `ai_agent_tool_invocation` | `id, run_id, llm_invocation_id, tool_call_id, parent_tool_call_id, sub_agent_id, sub_agent_type, sub_agent_description, dispatch_index, agent_name, step_no, tool_name, tool_provider, input_json, llm_oberserve, status, error_msg, started_at, finished_at, duration_ms, create_time, update_time, deleted` | `run_id, tool_call_id`; `llm_invocation_id, dispatch_index` | [schema.sql:287](../../Reactor-agent-app/src/main/resources/db/schema.sql#L287) |
| `ai_agent_user_question` | `id, question_id, visitor_id, session_id, source_run_id, source_request_id, tool_invocation_id, tool_call_id, questions_json, answers_json, status, expires_at, resume_request_id, resume_context_json, create_time, update_time, deleted` | `question_id, deleted`; `resume_request_id, deleted` | [schema.sql:319](../../Reactor-agent-app/src/main/resources/db/schema.sql#L319) |
| `ai_agent_plan_approval` | `id, approval_id, visitor_id, session_id, source_run_id, source_request_id, tool_invocation_id, tool_call_id, plan_content, plan_file_path, decision_json, status, expires_at, resume_request_id, resume_context_json, create_time, update_time, deleted` | `approval_id, deleted`; `resume_request_id, deleted` | [schema.sql:345](../../Reactor-agent-app/src/main/resources/db/schema.sql#L345) |
| `ai_agent_tool_output_deep_search` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, query, answer_summary, stages_json, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:372](../../Reactor-agent-app/src/main/resources/db/schema.sql#L372) |
| `ai_agent_tool_output_code_interpreter` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, code_output, content, code, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:393](../../Reactor-agent-app/src/main/resources/db/schema.sql#L393) |
| `ai_agent_tool_output_data_analysis` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, task, summary, content, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:415](../../Reactor-agent-app/src/main/resources/db/schema.sql#L415) |
| `ai_agent_tool_output_multimodal_agent` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, summary, markdown_content, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:436](../../Reactor-agent-app/src/main/resources/db/schema.sql#L436) |
| `ai_agent_tool_output_image_generation` | `id, tool_invocation_id, run_id, request_id, request_source, session_id, tool_call_id, status, error_msg, prompt, mode, summary, size, batch_count, source_image_count, mask_image_count, used_fallback, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:456](../../Reactor-agent-app/src/main/resources/db/schema.sql#L456) |
| `ai_agent_tool_output_canvas_publish` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, title, mode, primary_file_name, preview_url, download_url, open_in_panel, salvaged, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:484](../../Reactor-agent-app/src/main/resources/db/schema.sql#L484) |
| `ai_agent_tool_output_emit_ui_tree` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, canvas_id, salvaged, tree_json, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:509](../../Reactor-agent-app/src/main/resources/db/schema.sql#L509) |
| `ai_agent_tool_output_emit_ui_patch` | `id, tool_invocation_id, run_id, request_id, session_id, tool_call_id, status, error_msg, canvas_id, seq, patches_json, created_at, updated_at` | `tool_invocation_id`; `request_id, tool_call_id` | [schema.sql:530](../../Reactor-agent-app/src/main/resources/db/schema.sql#L530) |
| `ai_agent_artifact` | `id, run_id, request_id, tool_invocation_id, tool_call_id, artifact_role, visibility, source_type, source_name, file_name, storage_key, download_url, preview_url, mime_type, file_size, file_hash, metadata_json, create_time, update_time, deleted` | `request_id, tool_call_id, storage_key` | [schema.sql:551](../../Reactor-agent-app/src/main/resources/db/schema.sql#L551) |
| `ai_agent_featured_conversation` | `id, featured_id, session_id, title, summary, cover_resource_key, cover_url, tags_json, sort_order, status, published_by, published_at, updated_by, updated_at, create_time, update_time, deleted` | `featured_id`; `session_id` | [schema.sql:580](../../Reactor-agent-app/src/main/resources/db/schema.sql#L580) |
| `ai_agent_ltm_curated_entry` | `id, stream_id, owner_type, owner_id, scope, content, status, source_session_id, source_request_id, write_origin, create_time, update_time, deleted` | — | [schema.sql:604](../../Reactor-agent-app/src/main/resources/db/schema.sql#L604) |
| `ai_agent_working_memory_turn` | `id, session_id, memory_scope, request_id, run_id, turn_seq, entry_agent, status, schema_version, message_count, token_estimate, started_at, finished_at, create_time, update_time, deleted` | `request_id, deleted`; `session_id, memory_scope, turn_seq, deleted` | [schema.sql:623](../../Reactor-agent-app/src/main/resources/db/schema.sql#L623) |
| `ai_agent_working_memory_message` | `id, session_id, memory_scope, turn_id, request_id, origin_message_key, run_id, seq_no, role, content, reasoning_content, tool_call_id, tool_calls_json, base64_image, message_kind, visibility, token_estimate, create_time, update_time, deleted` | `turn_id, seq_no, deleted` | [schema.sql:648](../../Reactor-agent-app/src/main/resources/db/schema.sql#L648) |
| `ai_agent_working_memory_compaction` | `id, session_id, trigger_request_id, compact_request_id, strategy, status, before_tokens, after_tokens, before_message_count, after_message_count, threshold_tokens, summary_text, before_messages_json, after_messages_json, error_message, create_time, update_time, deleted` | — | [schema.sql:680](../../Reactor-agent-app/src/main/resources/db/schema.sql#L680) |
| `ai_agent_ltm_fork_execution` | `id, session_id, trigger_request_id, fork_request_id, fork_kind, status, skip_reason, owner_type, owner_id, user_turns, snapshot_message_count, max_steps, timeout_seconds, duration_ms, entries_before, entries_after, applied_count, error_message, detail_json, create_time, update_time, deleted` | — | [schema.sql:706](../../Reactor-agent-app/src/main/resources/db/schema.sql#L706) |
| `ai_agent_session_todo` | `id, session_id, task_id, subject, description, active_form, owner, status, blocks_json, blocked_by_json, metadata_json, seq_no, create_time, update_time, deleted` | `session_id, task_id, deleted` | [schema.sql:737](../../Reactor-agent-app/src/main/resources/db/schema.sql#L737) |
| `ai_agent_background_task` | `id, session_id, task_id, type, status, description, command, agent_id, agent_type, prompt, output, error_msg, total_tool_use_count, total_duration_ms, started_at_ms, ended_at_ms, create_time, update_time, deleted` | `session_id, task_id, deleted` | [schema.sql:758](../../Reactor-agent-app/src/main/resources/db/schema.sql#L758) |

### SQLite / 文件 / 向量存储补充

- 文件服务：`SQLITE_DB_PATH`（缺省autobots.db），[file_table.py:15](../../reactor-tool/reactor_tool/db/file_table.py#L15) 的SQLModel表`fileinfo`，不是兼容ORM [file_info.py:18](../../reactor-tool/reactor_tool/model/file_info.py#L18) 的`file_info`。主字段id/file_id/filename/file_path/description/file_size/status/request_id/create_time；异步engine aiosqlite（[db_engine.py:45](../../reactor-tool/reactor_tool/db/db_engine.py#L45)）。
- MRAG：`SQLITE_PATH`，tables `t_knowledge_base,t_kb_file,t_kb_doc,t_mrag_session,t_mrag_turn`，[store_factory.py:22](../../reactor-tool/reactor_tool/tool/mrag/storage/store_factory.py#L22) 和各`*_sqlite_impl.py`；store构造可能create_all，只在Tool Runtime保持现有行为。
- 磁盘：FILE_SAVE_PATH/WORKSPACE_ROOT共享skilloutput，Skill库SKILL_DIR、主题/模板/SOP等按原组件路径；preview/download公共URL与internal URL分开。
- 检索：MRAG Qdrant collections、数据问数Qdrant/ES与embedding配置、OSS object key/token、可选OpenViking/holographic语义服务数据不做清空或重建。collections/namespace/endpoint需在授权集成环境取证。
- GenUI/UI与文件真实历史应联查MySQL artifact→storage_key→SQLite file_id/request_id→磁盘/对象存储，不修改旧ID关联。

## 附录 F：MyBatis 实际 SQL / 状态操作索引

此表补充schema快照：保留affected rows、条件UPDATE、排序、软删除和upsert语义。尤其HITL的claim/decision与markFailed不是相同CAS条件；迁移须逐语句对照，不能凭状态图增加或遗漏条件。

| Mapper | 操作ID | 涉及表 | 实现 |
| --- | --- | --- | --- |
| `admin_user_mapper` | `insert`, `updateById`, `updateByUserId`, `deleteById`, `deleteByUserId`, `queryById`, `queryByUserId`, `queryByUsername`, `queryEnabledUsers`, `queryByStatus`, `queryAll`, `queryByUsernameAndPassword` | `admin_user`, `id` | [admin_user_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/admin_user_mapper.xml#L1) |
| `ai_agent_session_capability_mapper` | `listBySessionId`, `upsert` | `ai_agent_session_capability`, `enabled` | [ai_agent_session_capability_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ai_agent_session_capability_mapper.xml#L1) |
| `ai_client_api_mapper` | `insert`, `updateById`, `updateByApiId`, `deleteById`, `deleteByApiId`, `queryById`, `queryByApiId`, `queryEnabledApis`, `queryAll` | `ai_client_api`, `id` | [ai_client_api_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ai_client_api_mapper.xml#L1) |
| `ai_client_model_mapper` | `insert`, `updateById`, `updateByModelId`, `deleteById`, `deleteByModelId`, `queryById`, `queryByModelId`, `queryAllByModelId`, `queryByApiId`, `queryByModelType`, `queryEnabledModels`, `queryAll` | `ai_client_model`, `id` | [ai_client_model_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ai_client_model_mapper.xml#L1) |
| `ai_client_tool_mcp_mapper` | `insert`, `updateById`, `updateByMcpId`, `deleteById`, `deleteByMcpId`, `queryById`, `queryByMcpId`, `queryAll`, `queryByStatus`, `queryByTransportType`, `queryEnabledMcps` | `ai_client_tool_mcp`, `id` | [ai_client_tool_mcp_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ai_client_tool_mcp_mapper.xml#L1) |
| `artifact_ledger_mapper` | `batchInsertArtifacts`, `queryByRunId`, `queryByRunIds`, `queryByToolInvocationIds`, `queryInputArtifactsByRunIds`, `queryOutputArtifactsByToolInvocationId`, `queryOutputArtifactsByRunIdAndToolCallId`, `queryOutputArtifactsByRequestIdAndToolCallId`, `countBySourceName`, `queryBatchHeadsBySourceName` | `ai_agent_artifact` | [artifact_ledger_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/artifact_ledger_mapper.xml#L1) |
| `background_task_mapper` | `selectBySessionId`, `selectBySessionAndTaskId`, `upsert` | `ai_agent_background_task`, `type` | [background_task_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/background_task_mapper.xml#L1) |
| `dialogue_run_ledger_mapper` | `insertRun`, `updateRunFinish`, `queryByRequestId`, `queryRecentBySessionId`, `queryBySessionId` | `ai_agent_dialogue_run`, `id` | [dialogue_run_ledger_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/dialogue_run_ledger_mapper.xml#L1) |
| `dialogue_session_ledger_mapper` | `upsertSession`, `queryBySessionId`, `querySessionView`, `queryRecentSessions`, `querySessionViewByVisitor`, `queryRecentSessionsByVisitor` | `ai_agent_dialogue_session`, `visitor_id` | [dialogue_session_ledger_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/dialogue_session_ledger_mapper.xml#L1) |
| `featured_conversation_mapper` | `upsert`, `queryByFeaturedId`, `queryBySessionId`, `queryOnlineList`, `countOnline`, `updateStatus`, `queryAdminList`, `countAdminList` | `ai_agent_featured_conversation`, `title`, `id` | [featured_conversation_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/featured_conversation_mapper.xml#L1) |
| `llm_invocation_ledger_mapper` | `insertLlmInvocation`, `updateLlmInvocationFinish`, `queryByRunId`, `queryByRunIds` | `ai_agent_llm_invocation`, `id` | [llm_invocation_ledger_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/llm_invocation_ledger_mapper.xml#L1) |
| `ltm_curated_entry_mapper` | `insert`, `softDeleteById`, `updateContent`, `selectActive` | `ai_agent_ltm_curated_entry`, `id` | [ltm_curated_entry_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ltm_curated_entry_mapper.xml#L1) |
| `ltm_fork_execution_mapper` | `insertEvent` | `ai_agent_ltm_fork_execution` | [ltm_fork_execution_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/ltm_fork_execution_mapper.xml#L1) |
| `plan_approval_mapper` | `insert`, `selectByApprovalId`, `selectByResumeRequestId`, `selectOpenBySessionId`, `countOpenBySessionId`, `casDecidePending`, `casClaimResume`, `markAnswered`, `markFailed`, `casCancel`, `cancelBySourceRequestId` | `ai_agent_plan_approval`, `id` | [plan_approval_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/plan_approval_mapper.xml#L1) |
| `session_todo_mapper` | `selectBySessionId`, `selectMaxSeqNo`, `upsert`, `softDelete`, `softDeleteAllBySessionId` | `ai_agent_session_todo`, `subject`, `id` | [session_todo_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/session_todo_mapper.xml#L1) |
| `sub_agent_definition_mapper` | `queryEnabled`, `queryAll`, `queryByAgentKey`, `insert`, `updateByAgentKey`, `softDeleteByAgentKey` | `ai_agent_sub_agent_definition`, `id` | [sub_agent_definition_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/sub_agent_definition_mapper.xml#L1) |
| `tool_invocation_ledger_mapper` | `insertToolInvocation`, `updateToolInvocationFinish`, `queryByRunId`, `queryByRunIds`, `queryByLlmInvocationIds`, `queryRecentByToolName` | `ai_agent_tool_invocation`, `id`, `ai_agent_dialogue_run`, `ai_agent_artifact` | [tool_invocation_ledger_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_invocation_ledger_mapper.xml#L1) |
| `tool_output_canvas_publish_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_canvas_publish`, `DUAL` | [tool_output_canvas_publish_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_canvas_publish_mapper.xml#L1) |
| `tool_output_code_interpreter_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_code_interpreter`, `DUAL` | [tool_output_code_interpreter_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_code_interpreter_mapper.xml#L1) |
| `tool_output_data_analysis_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_data_analysis`, `DUAL` | [tool_output_data_analysis_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_data_analysis_mapper.xml#L1) |
| `tool_output_deep_search_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_deep_search`, `DUAL` | [tool_output_deep_search_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_deep_search_mapper.xml#L1) |
| `tool_output_emit_ui_patch_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_emit_ui_patch`, `DUAL` | [tool_output_emit_ui_patch_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_emit_ui_patch_mapper.xml#L1) |
| `tool_output_emit_ui_tree_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_emit_ui_tree`, `DUAL` | [tool_output_emit_ui_tree_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_emit_ui_tree_mapper.xml#L1) |
| `tool_output_image_generation_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall`, `countByRequestSource`, `queryPageByRequestSource` | `ai_agent_tool_output_image_generation`, `DUAL` | [tool_output_image_generation_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_image_generation_mapper.xml#L1) |
| `tool_output_multimodal_agent_mapper` | `insert`, `queryByToolInvocationId`, `queryByRequestToolCall` | `ai_agent_tool_output_multimodal_agent`, `DUAL` | [tool_output_multimodal_agent_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/tool_output_multimodal_agent_mapper.xml#L1) |
| `user_question_mapper` | `insert`, `selectByQuestionId`, `selectByResumeRequestId`, `selectOpenBySessionId`, `countOpenBySessionId`, `casAnswerPending`, `casClaimResume`, `markAnswered`, `markFailed`, `casCancel` | `ai_agent_user_question`, `id` | [user_question_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/user_question_mapper.xml#L1) |
| `visitor_identity_mapper` | `insert`, `queryByTokenDigest`, `queryByVisitorId`, `updateLastSeen`, `bindUsernameIfAbsent` | `ai_agent_visitor_identity`, `id` | [visitor_identity_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/visitor_identity_mapper.xml#L1) |
| `working_memory_compaction_mapper` | `insertEvent` | `ai_agent_working_memory_compaction` | [working_memory_compaction_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/working_memory_compaction_mapper.xml#L1) |
| `working_memory_message_mapper` | `batchInsertMessages`, `selectBySessionIdOrdered`, `selectByTurnIds`, `searchFullTextBySession`, `searchFullTextByVisitor`, `scanBySession`, `scanByVisitor`, `selectHistoryBySession`, `selectRecentSessions`, `selectSessionSummary` | `ai_agent_working_memory_message`, `ai_agent_working_memory_turn`, `ai_agent_dialogue_session` | [working_memory_message_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/working_memory_message_mapper.xml#L1) |
| `working_memory_turn_mapper` | `insertTurn`, `selectMaxTurnSeq`, `selectByRequestId`, `selectReadyBySessionIdAndScope`, `markReadyInvalidBySessionIdAndScope` | `ai_agent_working_memory_turn`, `id` | [working_memory_turn_mapper.xml:1](../../Reactor-agent-app/src/main/resources/mybatis/mapper/working_memory_turn_mapper.xml#L1) |

## P0协议冻结与待决变更（2026-10-02）

机器索引：[runtime-routes.json](fixtures/runtime-routes.json)为Spring真实映射反射，108方法；[source-contracts.json](fixtures/source-contracts.json)登记绑定参数/default/DTO/SQL/工具返回分支（C）；[tool-schemas.json](fixtures/tool-schemas.json)为67命名工具动态schema、显式工厂配置/MCP测试发现（V，非真实外部发现）。老mcp_tool的toParams实际null，ContextScopedTool只委托底层tool，不发明新名称或schema。

原MVC/Boot默认Jackson捕获见[java-behavior.json](fixtures/java-behavior.json)：普通非法stop/inject仍HTTP200+0002+data:null；坏JSON/缺body和缺previewData参数400；导出非法tree400；data/allModels为数字code200；健康text/event-stream UTF-8文本ok。主SSE只有data JSON行和双换行，finished/retryMs/null/long零值保留，无named event/SSE id/[DONE]。这是standalone MockMvc/Boot默认mapper证据，不是实际TCP/Nginx/部署配置抓包。默认LocalDateTime为ISO文本；GptProcessResult无参默认与builder结果不同，fixture逐字段保留。

原历史fixture实际执行query/replay，以测试DAO提供固定ledger。projector taskId为动态UUID、tool与summary引用同一值；比较只归一声明指针，不删除ID。生成HITL resume ID亦保留重复回答的引用等价/格式断言。实际Mapper在新H2内存库执行answer/claim/cancel/finish的affected rows：expired answer=1、首次claim=1/重复=0、cancel RESUMING=0、markAnswered后late markFailed=1；最终FAILED。不是MySQL并发验收。

A2/A3拟外部行为改变、当前Java结果和负例验收见[p0-decisions.md](p0-decisions.md)。P0未引入认证Cookie、拒绝他人stop、sweep过期、修改终态CAS或自动恢复副作用。副本DDL/旧文件/历史验证见[copy-validation.md](copy-validation.md)，缺真实数据/代理/browser证据的契约保持U。

## P1 已实现子集（2026-10-03）

本节不替代上述原Java契约。Python已实现的入口：`/web/health`、原query及`/1/`alias、visitor bootstrap/naming、conversation sessions/detail、run follow。原Builder的null/default/data-only/UTF-8语义、request normalization、归属与cookie、Run/LLM/tool/artifact状态/ID、`llm_oberserve`错拼列均保留；失败不是成功文本，模型工具参数坏JSON为真实失败observation。跨轮读取只使用原READY main working-memory表，不新增消息/展示真相表。

ReAct工具批先登记dispatch序，再并行调用原Tool API，observation按模型原顺序回填；批内部异常等待所有已启动工具收口，再结束Run。SSE observer与任务owner分离，TCP断线不取消业务；128帧缓冲及cursor/follow，终态写库后发布。单worker限制由启动参数和workspace owner文件锁落实。进程崩溃后的恢复不在此能力内，不能把follow_pending当重启恢复已实现。

历史同时恢复通用tool_result及原持久化rich工具读侧：code、data_analysis、markdown、image file/result、canvas HTML、DeepSearch阶段、GenUI tree/patch、AskUserQuestion原参数/observation/附属状态。GenUI旧typed表优先，缺失时按原GenUiSchema恢复输入；不把旧ui_tree降为普通文本，不启用新GenUI生成/导出或HITL写接口。历史模型窗口按原model配置，缺省100000；工具输出绑定优先且仅以历史原服务实际使用的tool_invocation_id读取，不猜测跨工具记录。

本轮固定模型HTTPfixture仅在`reactor-backend/tests/`；生产adapter始终向显式模型服务发起真实HTTP。隔离MySQL实际新账本/合成旧专用表，经原Javaprojector逐字段对照（仅动态taskId归一）。真实供应商/真实旧数据副本U，其他未迁移入口保持明确未实现，原UI相关404已记录。完整测试命令、数据关联与限制见[p1-report.md](p1-report.md)。A2/A3具体外部协议仍不擅自改变。


## P2 落地契约与已授权修复（2026-10-03）

本轮授权覆盖P0已确认owner/恢复方案的P2接口，不受上述历史“待确认”限制。原方法/路径/DTO/SSE/status及两步decision→resume保持；新增Python接线详见[P2报告](p2-report.md)。启用模型目录保留原UI `/api/v1/admin/ai-client-model/query-enabled` 元数据DTO（11键，无baseUrl/apiKey）；这是工作台选择器读侧，管理员凭证/配置CRUD没有在P2公开接入。

- RunA WAITING_INPUT=5→question/approval PENDING→decision CAS RESUME_PENDING→claim CAS RESUMING→唯一RunB；请求/审批/提问/源Run/源tool关联使用原字段。重复decision返回原resume ID；重复resume只follow既有执行或idle。MySQL RR需claim后locking read观察当前态。
- 准入拒绝且无RunB才CAS释放RESUMING→RESUME_PENDING；ANSWERED/FAILED只从RESUMING收口，不被迟到回调覆盖。停待输入取消PENDING/RESUME_PENDING，保留RunA事实；RESUMING由RunB取消收口，claim→admission间token保留stop。
- control/HITL/capability/task先查server visitor和实际session owner，不因缺session放行；普通拒绝HTTP200+0001、SSE failed/finished=true。旧无owner记录需授权映射，query/history不首次认领。过期PENDING CAS TIMEOUT并拒绝answer/decide。
- 注入FIFO下一模型步生效，queued事件保留text/source/status；mailbox目标必须当前session活跃子Agent。子Agent独立上下文和读编辑状态、共享session Todo与能力快照，禁止递归Agent/HITL及主Agent控制工具。
- follow缓冲128业务帧，heartbeat不占位；cursor只发更大seq；旧observer解绑不能影响替代observer。缺registry持久RUNNING最多park10秒→follow_pending/retryMs800；不存在/terminal follow_idle。HTTP断线不cancel。
- root先持久成功，后台未排空时根结果finished/finish=false，排空后stream_settle+EOF；已成功root不被晚child停止/失败重写。TaskOutput timeout shield保留子任务，TaskStop原子status running→stopped。
- 排他恢复以workspace锁+MySQL数据库owner锁为前置，显式声明旧Java/Python已停；RUNNING→FAILED/PROCESS_RESTART、后台→failed、RESUMING按RunB事实ANSWERED或FAILED。没有副作用自动重放，无新生产DDL。

真实TCP/原UI/CAS/恢复证据新增V；真实供应商、旧数据/代理仍U。管理员Cookie/私有Tool file/KB/image ACL与服务认证等A2剩余范围随P3/P5接入；H2不删除。原Java保留对照与回滚，未自动切生产。

## P3 实现与验证（2026-10-03）

- 原Tool SSE由独立 `adapters/tool_stream.py` 解码；要求显式完整结果+`[DONE]`，主Agent仍data-only finished终帧。DeepSearch保留extend/search/chapter_summary/report、未知事件字段、完整章节/来源/文件；未知事件留原始持久化阶段，不替换来源。错误、断流和超时落失败并保留已有证据，不伪造最终研究报告。
- CodeAct累积正文和最终codeOutput分别保留；四个专用输出表沿用原列、request/session/run/tool关联，在finish_tool终态CAS同事务写入。stdout/stderr/result/失败前文件进入实际Tool观察；Bash保留exit_code/timed_out等原DTO。
- `/data`入口全部实现原JSON和独立ChatDataMessage SSE：DEBUG/THINK/finished_stream/CHART_DATA/ERROR/READY；NL2SQL真正解析及执行业务SQL，输出原表格/图表DTO，完整CSV、chart配置和来源文件。SQL AST替换只改模型关系，保护字符串字面量；UNION/CTE保留查询形态。Java三组query column/filter原值已对照（fixtures/p3-sql-java.json），未声称所有SQL语法都已穷尽对照。
- 原WebFetch明确提炼失败字段degraded/extractError/hint保留；内联截断不会截断文件正文。五个Java原生搜索与六个DeepSearch Tool引擎分开，Skill/MCP不列为原生内置。
- 用户已批准三守卫开关透传与原静态/runtime open/io.open接线；隔离负例验证跨工作区拒绝和正常执行。原I/O guard不等同OS安全隔离。外部Tool文件/KB统一owner、403、服务token/代理和旧无owner隔离方案仍待确认，未启用。`REACTOR_TOOL_SERVICE_TOKEN`配置能力不表示原Tool会鉴权。
- H2保留原Java实际mem依赖，不替换MySQL账本；Python H2未启用，明确失败，不假称MySQL/SQLite可替代。真实部署和可选JDBC过渡决定见P0证据。

测试命令/结果/外部限制见[P3报告](p3-report.md)。原React源码未改；SOP依赖Qdrant，缺服务明确错误，与KB/history的SQLite成功分别记录。


## P3 收尾契约落地

- 原 `/data/chatQuery` 的 ChatDataMessage（DEBUG/THINK/finished_stream/CHART_DATA/ERROR/READY）、原Tool SSE、主Agent SSE分开处理；不将三者互换。独立问数入口原本不创建主Agent Run账本（原UI sendDataMessage只传content）；其图表/表格实测，不宣称其具有主Agent的历史恢复。主Agent data_analysis 的原专用输出/产物关系及刷新恢复另有真实证据。
- 原 `/v1` 及 `/tool/v1` 文件、document、MRAG历史入口经backend可信Cookie校验；backend至Tool服务认证使用独立32+字符token，分析回调还校验HMAC visitor/session/expiry。客户端owner/token header不能代替访客身份。原URL路径、JSON与ID保留，公开域名指向受保护backend。
- B访问A的私有文件/KB/document/query产物返回HTTP403；缺身份/错误服务认证/未知旧owner/公开register_file也拒绝。持久owner加法表001，文件物理命名碰撞单独登记；session上传错误ValueError已转换为403。
- 原File Tool没有独立物理文件删除路由；不发明新协议。现有KB/document删除入口先校验owner，保留实际外部删除失败。原SOP是共享配置，仅验证可信身份，不将它称为私有KB。
- SQLite金额列使用DECIMAL_TEXT；精确聚合/比较/算术及group/order/distinct使用Decimal。不能无损投影为原numeric JSON时明确失败，可CAST AS TEXT交付准确文本；NUMERIC affinity已落为REAL的DECIMAL列拒绝假称可还原。整数9007199254740993在服务端JSON/CSV保持整数；浏览器JS数值精度限制不被伪称消失。
- 原Java未加AS的聚合DTO不分类为measure，Python按新补的Java fixture保留该行为；使用显式AS生成标准图表。SQLite真实结果label与该GUID对齐，避免decimal_sum内名或COUNT的星号替代字段名。
- 私有部署中，原S3公开permanent_url不能靠owner映射保护外部字节；该上传分支明确503，不静默切本地。原真实S3 SDK路径保留在Java/legacy Tool对照，私有object gateway未验证，正式启用S3另行验收。

## P4 当前契约（2026-10-04）

实现位置与逐项证据见 [P4报告](p4-report.md)。工具 schema 冻结在 `reactor-backend/reactor_backend/tools/p4_schemas.json`，生产模型/Tool wire 仍使用原名字及返回结构；压缩、记忆 fork 没有新增 SSE 事件。所有写入保留原 MySQL ID、scope、source request/run、reasoning/media/origin_key。

- working-memory 原 READY 读取；压缩替换原投影为 INVALID 并增写 synthetic 投影，历史检索 origin 去重。Java `sub:<id>` 与 P2 `subagent:<id>` 兼容读取，主 scope 不混入 child。原 tool-use/result 原子配对，永久摘要失败保留完整原上下文；瞬态/空/超时采用有证据的本地摘要/整组裁剪，失败审计单列。
- `memory` 原 user/curated targets 与 add/replace/remove/批处理，UTF-16 预算 1375/2200（含分隔符）、重复/歧义和原 success/result。写 `ai_agent_ltm_curated_entry`，fork 写 `ai_agent_ltm_fork_execution`，不借普通消息表假实现。可信 visitor owner；不采信请求 user/ERP 作为身份，不自动认领旧 USER owner。
- `session_search` 保留 query/scope/limit/role_filter/session_id/around_message_id/window、匹配消息 ID、read/scroll 结构；真实 FULLTEXT 优先，索引不可用时明确标 scan。只有当前可信访客 main 历史，子 Agent 禁父长期记忆/检索。
- Skill 发现/手册/脚本原工作流可用，`${SKILL_DIR}`/`${PYTHON}`、Unicode metadata、物理目录/虚拟路径兼容。用户明确批准的行为改变：访客的 skills 写/执行转入自己的 `.reactor/skill-library`，不能覆盖共享库。失败保留原工具结果结构。共享维护只供 OS 管理员 CLI，管理 HTTP 随 P5 接原认证。
- macOS Bash session-copy 请求通过内核文件策略，拒绝跨会话、共享库写、symlink；非 login shell 与清洁执行环境避免宿主初始化和凭证继承。其他平台不静默降级，缺原生边界明确要求 E2B，live U。原 Java 回滚 library 路径未替换。
- MCP 三协议固定官方 SDK，原 descriptor 字段/timeout 单位、FQ 正规化和原 wire 映射；ToolSearch 延迟 schema/alwaysLoad/searchHint，资源 text/blob 表达，调用失败 wire observation。每 scope 独立连接 actor，关闭/超时/取消释放子进程和 session。

P4 确定性141通过/1环境门控skip、隔离50通过、Java70通过。远端provider/MCP/E2B和真实旧数据U，不能把本机端点等同生产服务；完整索引 [p4-evidence.json](fixtures/p4-evidence.json)。

## P5 已实现契约增量

完整 108 Java method/path 索引由 `test_original_route_manifest_and_admin_auth` 对装配后的 Python 路由检查；64 原管理路由冻结于 `reactor_backend/resources/admin_routes.json`，另 5 精选管理与 3 公开精选、原图片与 GenUI 路径保留。管理拒绝保持 HTTP200/0003；私人文件/外访客引用 403；无效 GenUI 导出 400。模型 public query-enabled 只输出原 metadata，不含 API Key/password。已批准 admin Cookie opaque 32 字节、DB SHA256 摘要、8h、每请求校验 enabled/expiry/revoke；CSRF拒绝，CORS包裹拒绝响应；validate-login不签发Cookie。原 React 增加必要登录弹窗，敏感凭证不写浏览器持久存储。

新加法表 002 admin_session、003 featured_resource，均保留原 utf8mb4_unicode_ci；启动不执行DDL，离线 migration/init 必须显式指定授权副本，init非空表拒绝。精选上线快照只公开注册输出URL；输入/整个archive不公开，下线即撤销。上传/文件旧URL、Unicode/nested/new-old MD5/MIME 保持，Range/HEAD代理；受保护原Tool通过anchored FD发送文件并拒绝symlink。

GenUI 7 原工具schema与guides/catalog冻结；typed输出同事务，实时 ui_tree/ui_patch/html 与历史合并。独立 PDF/DOCX遵循Java文本块/表格/图表与3D占位语义，slides有分页，不以浏览器截图替代。OFL Noto SC字体随发行资源嵌入，不依赖阅读器CID字库。docgen仍复用原全部渲染器；访客自定义theme/template按visitor独立，共享只读；docread读当前会话，模板 include逐文件拒绝symlink/越界和Jinja内部属性访问。

图片原gateway由Python backend承担，Tool只负责真实文件注册；默认gpt-image-2.5-flare、Grok配置分支、images/edits/mask/参考文件、尺寸、重试与fallback保留。workspace批次request_source=workspace/空run，Agent来源request_source=agent/真实调用关联；历史按持久owner隔离，不认领未知legacy owner。真实供应商未验证。
