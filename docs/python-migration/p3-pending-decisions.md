# P3 决策记录（原方案已获批准）

2026-10-03最新授权：执行下述ACL方案；使用独立SQLite业务源替代H2，不采用JDBC过渡；缺凭证项逐服务保持未验证。下文“待批准/未确认”为历史方案，已被本记录替代。收尾实现和验证见progress。

本页只列新增P0证据引起的外部协议决定；不覆盖用户已批准的P2 owner/恢复与两次Sandbox守卫接线。当前代码及默认入口不自动切换。

## A2 私有Tool文件/知识库/问数入口

证据：原file/KB接口没有creator/ACL，requestId可定位产物；主Agent已有owner检查不能保护直接访问Tool URL。仅配置service token不能声称原Tool已验证它。

建议保持原URL、JSON、原session/KB/doc/file ID和文件前缀；公开入口经可信网关转发，逐请求从原Cookie身份解析visitor，与资源owner比对。后端到Tool使用独立service token，Tool只接受可信内部调用。身份缺失拒绝、跨访客403，不能接受客户端自己提供的owner。新增版本化资源ACL映射及data-query requestId→visitor映射，不更换Reactor MySQL持久库。新建资源在创建事务登记owner；旧无owner资源拒绝首次访问认领，需在授权副本显式映射。原文件路径和ID关系保留。

具体验收：A创建文件/KB/doc/query后A原URL可读；B同URL 403；无身份拒绝；旧无owner不能由A自动认领；内部token缺失/错误失败；删除及上传检查相同owner；原React预览/下载/KB入口正常；重新启动后映射仍有效。只在新隔离库执行加法迁移，并验证可撤销网关配置的回滚。上述外部拒绝与连接调整已明确获批并实施，001加法迁移仅在本轮新建隔离库执行；Tool身份/内部认证/原入口和重启owner证据见P3收尾报告。

## H2业务DB

P0实际验证原工厂仅支持h2:mem，file/tcp与旧注释不符；部署type/url占位符没有真实配置证据。原Java依赖、配置及回滚保留。本轮Python业务SQLite替代H2已获授权，MySQL/ClickHouse真实adapter保留，不更换账本库。

历史候选（最新用户已决定不采用JDBC，以下不再构成确认门）：若授权保留已确认的mem业务路径，增设仅H2使用的可选JDBC过渡adapter，明确仍依赖JVM，先用新mem库核对原catalog/metadata/query返回；若实际部署无H2，再以授权配置证据关闭该路径。未确认前Python收到H2配置明确失败，不伪造查询成功、不冒称无JVM完成。本轮未读取生产连接或创建业务H2副本。

## 已批准且执行

用户批准三个既有CODE_INTERPRETER_ENABLE_*守卫开关透传、隔离配置全部开启；随后批准执行前静态校验与builtins.open/io.open复用原路径检查。守卫修复仍仅修改原三个Tool文件；本轮另加原Tool内部认证/分析回调/私有下载接线，已有权限执行器保持。越界失败与正常文件执行已有隔离证据，无需再次批准。


## 收尾结果

ACL与H2业务源两项决策均已闭合，P3代码/隔离验收完成。真实供应商、搜索、社媒、MRAG/OCR/向量/ES/SOP、ClickHouse、E2B及私有S3 gateway逐服务U，保留真实adapter与明确失败；按用户授权作为正式切换前验收，不再重复请求批准或阻止本轮P3闭合。完整Skill/MCP留P4，新授权后才开始。
