# H2 路径核实与兼容决策

> 2026-10-03 P3收尾更新：用户已授权独立SQLite替代H2业务源及可信身份/持久owner/内部认证方案。下文原审计的待确认记录为历史；最新实现、验收与边界见 [P3收尾报告](p3-closure-report.md)。Reactor MySQL账本及Tool SQLite保持，Java/H2保留回滚；P4未启动。

2026-10-02。区分 V 隔离执行、C 代码支持和 U 实际部署。本轮未读取环境秘密、未连接任何已有H2/MySQL数据源，未执行原schema/data初始化。

| 路径 | 证据与结论 |
| --- | --- |
| `Reactor-agent-app/pom.xml:60` | **C/V** com.h2database:h2 scope=runtime；classpath实际h2-2.3.232。模块CLAUDE.md称“测试用”不准确，不能据此删依赖 |
| `Reactor-agent-domain/.../reactor/config/data/DataAgentConfig.java:12`、`DbConfig.java:9` | **C** 配置 `autobots.data-agent.db-config.{type,url,host,port,schema,username,password,key}`；完整url优先；Reactor主账本另由 `spring.datasource.mysql.*` 管理，两者不是一个库 |
| `Reactor-agent-app/.../config/reactor/DataAgentInitRunner.java:58` | **C** type=h2时真实启动入口会经JdbcConnectionFactory执行db/schema.sql，并尝试db/data.sql；异常只日志记录。P0不运行该入口或脚本，不将它用于新后端启动 |
| `Reactor-agent-trigger/.../http/dataagent/DataAgentController.java:97` → `Reactor-agent-case/.../dataquery/DataAgentApplicationService.java` → `Reactor-agent-domain/.../rag/DataAgentQueryServiceImpl.java:136`、`Nl2SqlQueryService.java:191` | **C** testQuery/NL2SQL查询通过DataQueryExecutionPort使用DbConfig；元数据同步另见ChatModelInfoService/ColumnValueSyncService。H2属于业务问数链路的可选源，不只是测试数据库 |
| `Reactor-agent-infrastructure/.../dataquery/util/JdbcUtils.java:14` → `DataQueryExecutionAdapter.java:30` → `provider/jdbc/JdbcDataProvider.java:62` → `jdbc/connection/JdbcConnectionFactory.java:18`、`JdbcConnectionPoolFactory.java:34` | **C/V** URL解析、连接池、SQL方言及结果类型转换为真实可执行路径；P0以新建H2内存表经原adapter成功取BIGINT 9007199254740993、DECIMAL 1.2300和中文列，连接池关闭 |
| `jdbc/dialect/h2/H2DialectFactory.java:15`、`DialectEnum.java:10` | **V** SPI能选择内存H2，driver=org.h2.Driver；工厂只匹配jdbc:h2:mem。file和tcp URL返回false，与“内存/文件都共享前缀”的注释不同；未静默修复 |
| `jdbc/catalog/h2/H2CatalogFactory.java:11`、`H2SqlCatalog.java` | **V/C** SPI实际选择H2SqlCatalog；catalog实例已执行创建，元数据所有分支尚未逐项实测 |
| `Reactor-agent-app/.../test/domain/ReactorMapperNamespaceBindingTest.java:42` | **V** H2内存MyBatis装配测试通过；P0额外直接执行原user_question_mapper的answer/claim/cancel/markAnswered/markFailed SQL，affected rows符合捕获fixture。不能替代MySQL并发/事务/JSON验证 |

上表省略号为模块下 `src/main/java/org/wwz/ai/` 或 `src/test/java/org/wwz/ai/`，完整源码路径保存在 source-contracts 与 runtime fixture。测试入口是 [CaptureBaseline.java](../../tests/python_migration/java/CaptureBaseline.java) `captureH2/captureSql`。

本地配置检查器 [InspectH2Config.java](../../tests/python_migration/java/InspectH2Config.java) 只记录键存在、占位符未解析及是否明确选H2，支持多document YAML，不跟随外部imports。结果在 ignored `target/python-migration-p0/config-presence.json`。当前application.yml没有上述数据源键；dev/test文件不存在；prod的type/url为未解析占位符，mysql相关键存在，没有明确H2值。没有加载.env、环境覆盖或生产配置，因此**实际部署是否启用H2为U**；不能推断永久不用。

处理决定：P0保留H2依赖、Java方言与初始化入口，不换SQLite。P1主账本按已确认的MySQL兼容方案，与H2业务问数分开。P3保留H2能力为单独验收/决策项：

1. 若明确授权部署副本确认未使用H2，可提出取消正式H2路径的范围变更，需用户确认，不能凭本地搜索自行删掉。
2. 若存在真实H2业务数据，先获取授权副本、版本/URL类别及只读SQL/元数据样本。建议显式迁移业务源至已支持MySQL，验证类型、大小写、NULL、decimal/time、SQL方言、历史模型schema和回滚；这是数据源迁移，需要单独确认和副本演练，不是本轮动作。
3. 保留Java H2 sidecar/JDBC桥可作过渡，**仍需要JVM，无法满足P7无JVM目标**；不能以Python JDBC包装器声称正式迁移完成。未获H2范围/数据源决策前，正式无JVM验收保留阻断项，其他能力继续。

file/tcp URL支持问题独立记录为现实现缺陷；即使后续决定支持这两类，也属于可观察行为变化，应新增对应fixture并确认，不能顺便扩大现基线。


## 最新决定与SQLite数据兼容/回滚（2026-10-03）

用户已明确采用独立SQLite替代H2业务问数源，不做JDBC/JVM过渡。调整只涉及这个业务角色；Reactor自身MySQL账本不更换，Tool fileInfo/KB/history SQLite保持各自文件。原Java/H2依赖、方言、初始化入口不自动删除。实际旧H2文件/连接/部署是否存在仍U，本轮没有打开旧文件。

SQLite业务连接配置为 `db.type=sqlite, db.path=绝对已存在文件, timeout=秒`；读侧使用mode=ro/query_only和SELECT解析/authorizer，禁止ATTACH、扩展加载、写入、SELECT INTO。`maintenance sqlite-init`只在绝对新路径以xb创建，接受CREATE/INSERT，拒绝覆盖已有文件和DROP。示例 [SQLite配置](../../reactor-backend/examples-p3-sqlite.json)、[建库样本](../../reactor-backend/examples/sqlite-business-schema.sql)。启动/显式迁移命令见backend README。

| 数据/SQL | 当前兼容处理/证据 |
|---|---|
| JOIN/CTE/子查询/UNION | AST模型关系替换、CTE具名列保留、金额按SQL作用域传播；同名文本列不误投影为金额 |
| 聚合/算术/比较/排序/group/distinct | DECIMAL_TEXT使用Decimal函数/聚合与数值collation；超出计算或原numeric JSON精度明确失败，CAST TEXT可无损交付 |
| INTEGER/BIGINT | SQLite signed64整数原样进入Python JSON/CSV；9007199254740993实测，无自动转float；JS图表整数精度仍有限 |
| 金额 | 导入用DECIMAL_TEXT文本affinity，保存源系数/小数位；原DECIMAL/NUMERIC affinity若已写成REAL，不能从浮点推断原准确金额，拒绝假还原 |
| 日期/时间 | 新源使用ISO文本与SQLite date/strftime函数；DATE元数据映射保留，NULL为None/JSON null；旧H2 timezone/interval/特有函数尚未副本验收 |
| Unicode/大小写/NULL | 原中文数据与不敏感字段/表名查询实测；结果列按原查询投影小写，字段发现保留原名称；NULL不伪空串 |
| schema/模型metadata | 原modelList TABLE/SQL发现、fewShot/alias/recall/analyze/UUID初始化及显式刷新；软退役保存旧行和ID，失败保留active metadata |

若后续实际旧H2需要数据迁移，先在明确授权环境取得只读副本/一致快照及原版本、URL类别、schema、行数、PK/FK/模型ID映射；不能在本轮猜路径打开。离线从副本导出原始类型/精确decimal文本/ISO时间，建立新的SQLite文件和显式类型映射，再对比每表行数、主键唯一性、关联、NULL/Unicode、金额总和/边界值、日期时区、代表查询及产物SHA256。旧H2文件、导出、模型元数据和检索索引快照都保留；不同方言特性逐条转换和核对，不宣称任意H2 SQL都可直接运行。

回滚只在授权副本演练：停止单worker Python owner→保留SQLite/owner加法表/原ledger ID→恢复对应旧active metadata与索引快照→使用原Java/H2已授权配置。不得运行会自动DROP的原DataAgentInitRunner初始化路径，不清库或删除001表。正式网络入口/认证与旧Java兼容须单独验证，不能通过关闭内部认证让私有文件暴露。当前默认Java部署未切换，因此本轮无需生产回滚。
