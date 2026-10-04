# A2/A3：当前行为、具体修复方案与负例验收

2026-10-03 更新：用户已授权 P2 与已确认 P0 修复。本文以下为 P0 历史提案；P2 owner/expiry/CAS/排他恢复已落实，见 [P2报告](p2-report.md)。管理员、Tool资源与完整Skill边界随后续接口阶段实施，不重复请求已有批准。

2026-10-02。以下方案未改变Java/Python产品协议，未新增生产表或运行修复任务。用户已授权形成具体方案；这些成功→拒绝、状态收口和新身份Cookie行为应在后续实现前明确确认。P0其他工作已完成，不因待决项暂停基线。

## A2 身份和权限

当前证据：`VisitorIdentityFilter` 仅对选定Agent路径绑定匿名身份；`AdminUserAdminController.login/validate-login`查询凭证而不建立服务端会话；stop服务只比较可选sessionId；Session capabilities、生图history、Tool文件/MRAG和共享Skill边界见contracts Dxx。部署外部网关是否另有鉴权仍U，未断言线上完全无保护。

**已复现**：`java-behavior.json.hitl.foreign-stop-accepted` 中绑定visitor-other可凭req-foreign停止visitor-owner的活动Run；`missing-identity-answer` 中缺少上下文身份可获取另一个访客问题的已存在resumeRequestId。原mapper SQL visitorId为空时不加入owner谓词。测试是直接执行应用服务/原SQL，不代表带VisitorIdentityFilter的全部HTTP入口均可无Cookie绕过；外网可达性需独立验证。

建议采用以下固定方案，保留成功请求的路径、JSON键及旧访客token摘要算法：

| 范围 | 拟实现协议和存储 | 当前→拟改变 | 必须通过的负例 |
| --- | --- | --- | --- |
| 管理员 | `/api/v1/admin/admin-user/login`仍收原body并返回原Response；成功额外设置`reactor_admin_token`随机opaque HttpOnly Cookie，Secure随HTTPS、SameSite=Lax、Path=/，8小时过期。MySQL新增版本化`ai_agent_admin_session`（token_digest唯一、admin_user_id、expires_at、revoked_at、create_time）；只存SHA-256摘要。每请求核对账号enabled状态、expiry/revocation。新增POST logout撤销当前token；validate-login仍仅验证凭证，不赋会话。bootstrap/create首个管理员走离线授权初始化，API不得成为无鉴权建号口 | 管理路由当前无统一认证→统一要求admin Cookie；拒绝保留HTTP200 `Response{code:"0003",info:"需要管理员登录",data:null}`，不泄露配置/密钥。GET公开精选/health保持现语义。operator参数保留绑定，账本作者由认证admin事实决定，不信任传入operator | 匿名/visitor Cookie/伪造token/过期/撤销/被禁用admin均不能CRUD、test/reload/import、读配置；跨站写请求不通过Origin/CSRF检查；公开精选仍可读 |
| 访客归属 | 从Cookie解析server visitor，禁止以user、X-Device-Id或body visitor字段作为owner。所有普通session/run/task/question/approval入口先解析资源对应session，再查ledger owner；requestId有owner时不允许缺session绕过。服务边界也要求非空visitor，不能只靠HTTP filter | stop/inject/capability/图片history等漏校验入口的他人成功→拒绝；普通JSON拒绝HTTP200 `0001`，info统一“无权访问该资源”，data=null；SSE拒绝为data-only failed/finished=true终帧后EOF，不展示owner/任务内容。身份缺失业务拒绝，不执行CAS | 两访客跨session读历史、stop、inject、follow、answer/decide/resume、capability、TaskOutput/Stop均拒绝；伪造sessionId/省略sessionId也拒绝；同owner成功/幂等响应保持 |
| 文件/KB/图片 | 用file_id/storage_key找到fileinfo.request_id，再查Run/session owner和artifact绑定；KB关联明确的creator/ACL，列表按visitor；图片history查询加owner过滤，workspace无session记录按真实visitor。公开精选文件只通过已发布artifact allowlist可读。内部Tool API认证使用独立服务token+server传visitor/session，不信任公网任意header | 当前按全局ID/历史返回→加scope；binary/Tool私有资源采用HTTP403 `{code:"0001",info:"无权访问该资源"}`，需前端连接兼容和实际代理路径验收。旧owner为空记录先在授权副本建映射/隔离清单，不按首次请求认领 | 直接file URL、猜file_id、跨KB读取、图片历史串访客、盗用服务header、精选下线后私有文件访问均拒绝；旧授权文件URL/Unicode/嵌套路径继续可用 |
| 路径与共享Skill | workspace读写在可信root下以realpath/dirfd检查每个路径组件，拒绝绝对路径、`..`及symlink逃逸；压缩包提取验证条目和总大小。公共Skill库只允许admin import/package/reload写入；访客写会话副本，禁止bash sync-back覆盖全局库 | 原可疑全局写→明确scope拒绝；工具返回原ToolResultPayload失败结构，不能假成功。共享Skill行为和KB ACL如需新表同样版本化加法、确认后实施 | symlink/TOCTOU逃逸、ZipSlip、绝对路径、跨session workspace、访问OS配置、访客覆盖共享Skill、禁用Skill经别名调用均失败；允许脚本与目录仍真实运行 |

不默认启用“双兼容允许任意匿名管理”的模式。若既有部署网关承担认证，应先拿脱敏配置/实际拒绝证据，按同一owner约束映射可信身份；不能把用户可控header当网关证明。新增表仅是待确认DDL方向，正式SQL、备份/加法迁移/旧Java读兼容在后续隔离副本阶段交付，P0没有执行DDL到原库。

## A3 恢复、停止和过期

当前 V/C：正常answer/decide CAS `PENDING→RESUME_PENDING`，claim `RESUME_PENDING→RESUMING`，重复claim affected rows=0；审批恢复补齐tool-call/observation的原case测试已执行。H2原mapper实际执行证实过期问题answer rows=1、RESUMING不能casCancel、markAnswered成功后markFailed仍rows=1且状态变FAILED。MySQL并发事实仍需真实副本验证。stop对问题调用deprecated进程registry，审批调用持久repository；没有核实到Run RUNNING/RESUMING完整重启修复。

建议保持单worker、现有status数值/字符串、RunA/RunB关联和两步answer→resume协议，不引入副作用自动重放。

| 情况 | 拟状态/原子操作及返回 | 验收与边界 |
| --- | --- | --- |
| 孤儿RUNNING | **仅在已确认旧owner退出、该DB分区无其他活跃runtime的启动恢复窗口**执行：CAS仍RUNNING且owner已失效→FAILED，错误码`PROCESS_RESTART`，保留Run ID/账本/产物。history返回FAILED，follow发送原follow_idle并EOF；不重新调用模型/工具 | 杀进程后重启不重复工具副作用；已有SUCCESS/STOPPED不改；多实例/旧Java仍活跃时禁止仅靠“本进程registry为空”认定孤儿。初期部署排他性必须有证据；以后并行实例需要versioned owner_epoch/lease和fencing再启用 |
| 孤儿RESUMING | 核对resume_request_id对应RunB：终态SUCCESS→CAS RESUMING→ANSWERED；已停止/失败→CAS FAILED并给恢复中断说明；无RunB或RUNNING但owner已失效→FAILED，保留原resume ID/context，不退回RESUME_PENDING，不自动重派发。markAnswered/markFailed都限定期望状态及相同resume ID，迟到线程不能改已结束记录 | claim后/派发前、工具副作用后/结果落库前、RunB成功后/markAnswered前分别注入crash；不得用过期claim重试来实现未经证明的exactly-once。不能确定副作用是否发生时让用户新开明确请求，不能悄悄续跑 |
| 等待输入时stop | 先按server owner解析source_request_id；持久CAS question/approval `PENDING/RESUME_PENDING→CANCELLED`，再尝试停止活动Run/后台。RunA已WAITING_INPUT保持历史事实；活动RunB走取消令牌→STOPPED。注册表缺失但持久交互被取消时stop返回原字段 `{stopped:true,firstCancel:true}`；重复返回firstCancel=false | before bind、yield前后、浏览器断开、重启后pending、answer/stop竞争都测；原“registry缺失即stopped=false”在有pending交互时有意改变。RESUMING不直接取消claim记录，由RunB停止结果收口，不能出现取消卡片但工具继续且回写ANSWERED |
| expiry | 对question/approval保持expires_at语义，在DB NOW()检查，增加CAS条件 `(expires_at IS NULL OR expires_at>NOW())`；sweep只改PENDING→TIMEOUT。answer/decide与expiry同事务CAS竞争；已经RESUME_PENDING的有效决定不因原期限已到失效；RESUMING用执行owner恢复规则，不套提问deadline | 过期answer返回原Response envelope `0000`+`data{accepted:false,id,message:"请求已过期"}`（保持旧业务拒绝包装），状态TIMEOUT；重复已接受答案仍返回同resumeId。边界到期、NULL期限、DB时区、cancel/expiry/answer并发及page刷新都测；前端TIMEOUT卡片禁用输入 |
| late finish/claim拒绝 | 账本finish只允许RUNNING的首次终态转换；HITL收口只允许RESUMING且resume ID一致。保留executor拒绝后CAS退回RESUME_PENDING，但必须证明未开始RunB；进程异常/未知派发不可用此退回 | STOPPED不被迟到success覆盖；ANSWERED不被late FAILED覆盖；重复resume只派发一次；拒绝准入释放claim，再次resume可执行。原markFailed无状态限制与拟条件不同，需确认 |

负例矩阵在P2/P6同时用服务确定性测试和隔离MySQL并发测试验收；H2只用于P0原SQL行为取证，不承担MySQL事务等价保证。新增终态/错误信息须同步UI恢复和history/follow协议测试；仅保留enum TIMEOUT不算过期功能完成。

## 待确认项的准确范围

建议后续确认 A2 表格的admin Cookie/持久session、统一owner拒绝、私有文件/KB ACL和共享Skill写边界，以及 A3 的孤儿fail-without-replay、持久stop、expiry与终态CAS规则。上述设计涉及成功→拒绝、额外Set-Cookie/登出入口、status变化及可能的加法DDL；本轮只保存方案。H2部署决策另见 [h2-evidence.md](h2-evidence.md)。无需重新批准已确认的Python架构，也不因这些项阻止其他隔离迁移工作。

## P3 新证据与本轮具体授权（2026-10-03）

原local Sandbox `_sandbox_environment`丢弃三既有守卫开关；direct code_execution未接静态校验，runtime Path/pandas守卫未覆盖builtins.open/io.open。隔离negative实际返回ok，不输出所读内容。用户明确批准：透传三个开关；随后明确批准：执行前复用既有静态校验、runtime open/io.open接入同一既有路径校验器。当前修改仅在原三个Tool文件，未新增执行器/协议字段。101 backend/36实际集成已含动态open/io/Path跨工作区拒绝、原local normal写CSV、语法和超时；不据此宣称容器/OS全面隔离。

剩余 A2 私有file/KB资源403、旧无owner拒绝、可信服务token/代理的具体方案仍待确认；不重复请求P2已确认owner/恢复规则。H2保留原Java实证能力，部署mem/file/tcp决策仍按h2-evidence记录。


### P5 docgen/docread 补充授权（2026-10-04）

用户确认“采用：访客独立自定义配置，共享配置只读”。启用内部认证时 theme/template 保存与删除只影响 SHA256(visitor) 目录，读取优先自定义、回退原共享与内置配置；不删除原共享文件。docread/dataprep 本地输入和 docgen 本地图片、模板、数据文件、include/merge_sources 按当前签名 session 限制；合法模板使用受限 Jinja 环境保留变量/过滤器/循环，拒绝 Python 内部属性逃逸。实施与验证以 P5 检查点为准。
