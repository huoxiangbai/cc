# P0 验收与复现记录

日期：2026-10-02（Asia/Shanghai）。用户本轮授权仅“准备”和 P0；没有新增 Python 业务后端，没有开始 P1。

## 准备与恢复点

- 原 HEAD `cb6e389a5d03bee5bb56a2363d43a93e14a8cd46`；保留原 `.github/workflows/ocr-review.yml`、`.gitignore` 和全部审计文档。暂存区为空，未提交。
- 当前本地分支 `migration/python-p0`。origin 仍为 `https://github.com/OWWZO/ai-agent.git`，未 push、未创建 PR、未变更 remote。
- 原快照 `../local-snapshots/ai-agent-20261002-223215/manifest.json` 的七份文件哈希全部复核通过。开始本轮前另存八份文件（含 prompts）到 `../local-snapshots/ai-agent-p0-prep-20261002-225540.zip`；SHA-256 `46a713cecb0c1466ec89027cb3682595b990631c9e5610f4a40f96e3d09fdd72`。快照包含清单、HEAD、branch 和逐文件 SHA-256，恢复时先比较当前文件，不能直接覆盖后续工作。
- 可用 Python 3.11.12、3.12.13；选择现有 3.12.13 创建项目 `.venv`，未安装任何依赖，未改系统 Python。uv 0.11.32、Node 22.23.1、npm 10.9.8、JDK 21.0.12、Maven 3.9.11 可用。
- Maven 使用 `-o` 离线缓存；Mockito 5.14.2 缓存 agent 命令行预载。所有构建/日志/编译产物在 ignored `target/python-migration-p0/`；每次 Java 执行有独立临时根，退出即回收。只创建两个 H2 **内存**测试库，未连接 MySQL、SQLite 实际库、模型或工具服务，未加载应用 profile/.env、未执行原初始化 SQL。
- UI `node_modules` 和 Tool Runtime 虚拟环境仍缺失；P0 stdlib harness 无需安装它们。P1 另锁轻量 backend 依赖；本轮未安装重型工具依赖。

## 可运行入口

从项目根运行：

```bash
# 重建所有 Java 编译产物，执行固定隔离测试，再捕获并比较协议
.venv/bin/python tests/python_migration/run_baseline.py
# 已编译时复用缓存（不启动应用）
.venv/bin/python tests/python_migration/run_baseline.py --skip-build
# 检查源码索引漂移及对照器、数据副本校验器负例
.venv/bin/python tests/python_migration/export_source_contracts.py
.venv/bin/python -m unittest discover -s tests/python_migration -p test_harness.py -v
# P1 将 Python 侧产物保存为相同 capture 格式后进行比较
.venv/bin/python tests/python_migration/compare.py --java-capture \
  docs/python-migration/fixtures/java-behavior.json target/python-capture.json
```

首次需 JDK21/Maven 和可用的 Maven 缓存；离线缺依赖时命令明确失败，不自动联网。`.venv` 可用 `python3.12 -m venv .venv` 重建，无第三方 Python 依赖。runner 先执行 app reactor 的 SseEmitter 隔离测试，以 Surefire 生成的 classpath 加各模块 test-classes 编译独立 CaptureBaseline；然后直接 JUnitCore 执行白名单测试，绕过父 pom 对 case 的固定 skipTests，**不修改 pom 或业务**。不启动 SpringBoot 主应用、数据库初始化器或执行真实模型。

`--record` 只用于明确接受 Java 基线变化时更新 golden；默认检查绝不自动刷新 fixture。对照保留 key/null/数字与字符串类型/列表顺序及 ID 关系；HTTP JSON 比较忽略对象 key 顺序，SSE 保留 data 行和空行框架。动态归一仅限指定历史两个 replayFrames 的 projector taskId及两次过期问题回答的生成resumeRequestId，各自保留重复引用相等的约束；不删除所有 ID/时间。并行工具按 requiredEdges 偏序比较。原始字节文本仍保存在 golden 文件中。

## 资产与证据分层

| 资产 | 内容 | 证据与限制 |
| --- | --- | --- |
| [runtime-routes.json](fixtures/runtime-routes.json) | 108 个 Java 方法映射，HTTP 方法/路径/参数 annotation（含 defaultValue）/produces/consumes/返回类型 | 真正由 Spring RequestMappingHandlerMapping 反射产生；不是 108 个业务入口全部实测 |
| [source-contracts.json](fixtures/source-contracts.json) | 同一108路由的请求/响应索引、61个字段类、30个mapper完整SQL、33张MySQL表、Python API 路由、SQLite模型、工具返回分支、必需事件偏序及固定上游测试输入 | 源码推导 C；不冒充网络抓包、MySQL或SQLite副本DDL。固定模型/WebFetch输入是 synthetic test-only，未冒充真实供应商输出 |
| [java-behavior.json](fixtures/java-behavior.json) | 12种HTTP/SSE调用及2种历史HTTP：健康、三控制帧、错误body、stop/inject参数拒绝、follow idle、导出400、问数code=200、缺query参数、404；DTO默认/builder/null/BIGINT/decimal/time、请求规范化、工具成功/失败、GenUI tree/patch、HITL/SQL/H2 | 真执行原Controller、Boot默认Jackson、MVC序列化、历史query/replay投影和原mapper；下游query seam/DAO用隔离替身。MockMvc执行，不是TCP/Nginx/生产部署抓包；部署自定义配置另验 |
| [tool-schemas.json](fixtures/tool-schemas.json) | 67 个命名 BaseTool 的运行时 schema/description；显式全工具配置ReAct63个、PlanSolve完整池、空/配置白名单主池、dataAgent池；standard/always MCP发现fixture | 真实工厂与toParams执行，测试Skill/workspace；另3个旧工具只求schema，旧mcp_tool的schema实际为null，不能改成伪JSON。ContextScopedTool另记为委托包装，不是独立命名工具；未验证真实MCP发现/全部远程工具成功返回 |
| [test-results.json](fixtures/test-results.json) | 最终白名单JUnit分项数量、失败/排除项 | 102个测试，0失败、0ignored；另1个部署配置用例明确排除而非“通过” |
| [manifest.json](fixtures/manifest.json) | fixture哈希、证据类别和归一化边界 | 固定可复核资产；配置检查结果只记录键存在/是否选H2，不保存配置值 |
| [audit_copy.py](../../tests/python_migration/audit_copy.py) | 显式测试副本root内MySQL DDL/SQLite只读schema、integrity、行数、旧文件大小/MD5/ID关联检查 | 实际副本未提供；只有合成副本校验器负例通过，不能宣称真实旧数据兼容 |

102个JUnit包括原80个、case审批恢复1/子Agent配置1、工厂11、H2 mapper绑定1、工具observation/产物绑定8。还执行 Java capture 中的 HTTP线格式、H2 driver/SPI/catalog/adapter、审批 observation、归属缺口、CAS affected rows 与终态断言；这些 main assertions 不混入JUnit计数。Python harness 9个测试通过。

初次白名单95个中1个失败：`AgentToolCollectionFactoryTest.deployedPlanSolveMainToolListIncludesTaskOutputAndSendMessage` 读取未打包的 `application-dev.yml`。其余94个成功。保留 `target/python-migration-p0/initial-test-results.json` 和 `initial-baseline.log`；后续只排除此部署断言，其余11个工厂测试执行。没有为了该用例创造假profile或修改业务；部署profile检查仍U。开发capture期间修正了测试输入、反射调用、JSON key/UUID比较、重载路由反射排序和副本路径处理；对照器最终负例包含ID类型/关联漂移，不能自动更新golden掩盖不一致。

## 验收边界

| P0条件 | 结果 |
| --- | --- |
| 已有改动保留、本地恢复点、分支和环境 | 通过；原工作流哈希复核、remote不变、暂存区空 |
| 可复现Java runner/fixture/对照器，核心确定性执行 | 通过；102 JUnit + Java capture + 9 Python harness；默认重捕获比较通过 |
| 当前所有HTTP映射和工厂schema登记 | 通过；108个对应源码/反射映射集合完全一致。schema覆盖配置分支和旧工具，未混淆模型默认可见数 |
| H2实际入口、配置键、JVM约束 | 通过取证；见 [h2-evidence.md](h2-evidence.md)。部署是否选H2未知，不能删除 |
| A2/A3具体协议及负例方案 | 已给出，见 [p0-decisions.md](p0-decisions.md)；涉及行为变化待用户确认，未实现 |
| MySQL/SQLite旧副本、旧文件/旧历史对比 | 命令与检查器已交付；实际副本未提供，集成验收U |
| 真实浏览器/代理/SSE断线/全部远程工具/模型 | 本轮未验证；后续B01/B04/B09/B11/B12仍有门槛 |

P0基线与验证资产已完成；不代表Python迁移完成或全能力通过。可在下一轮明确授权 P1 后复用资产开展纵向链路；A2/A3协议改变及H2部署决策不能静默实施。
