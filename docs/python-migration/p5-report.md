# P5 交付、图片与管理验收报告

2026-10-04（Asia/Shanghai）。P5 实现与本地隔离验收收口；原 Java、React 工作台、Tool/Sandbox、MySQL/SQLite 和默认部署保留。仅本地开发，无 push/PR/remote/生产/.env/DROP 操作。用户批准的管理员认证和访客独立 theme/template 方案已执行；不重复申请旧文档中的确认。

## 实现与契约

- `reactor-backend/reactor_backend/delivery/{genui_tools,genui_export,images,artifacts}.py`、`projection/genui.py`、`runtime/react.py`：原7 GenUI工具schema/catalog/guides，tree/patch白名单、实时事件与历史合并、canvas_publish真实文件；独立 PDF/DOCX 与 slides 分页。原导出是文本块与占位语义，不冒充 WebGL 或浏览器截图导出。
- `adapters/image_gateway.py`直接迁移 Java Micu gateway，保留默认模型、生成/编辑/mask/多参考、尺寸/批次/重试/fallback、Grok分支和文件注册。`delivery/images.py`共享 HTTP 与 Agent 内核；原 typed image 表存 request_source、Run/调用与产物关系，历史按持久owner隔离。
- `adapters/tool_api.py/tools/schemas.json`补齐24项原 docgen/docread/dataprep；复用原实际 PDF/DOCX/HTML/MD/PPTX/XLSX/清单/模板/图表、主题与模板能力，结构化统计/警告保持，不以普通消息替代产物。
- `adapters/{admin_store,featured}.py`、`transport/{admin,delivery,private_tool}.py`覆盖完整原108个method/path、64原管理方法和5精选管理方法。原API/模型/MCP/SubAgent DB配置CRUD、查询、模型真实连接测试、Skill ZIP/URL导入/reload实际生效；原public query-enabled只返回模型metadata。
- 002管理员session/003精选resource为显式加法迁移，原collation保持；opaque Cookie 32随机字节，DB仅SHA256，8h、enabled/expiry/revoke每次检查与CSRF；拒绝仍HTTP200/0003。离线首管理员init仅空表可运行，非空拒绝。CORS包裹认证拒绝；原React补必要登录弹窗，Cookie HttpOnly，不将密码存localStorage。
- 原Tool `docgen/paths/themes/templates/theming`按visitor保存自定义配置、共享只读；`docread/paths`限制当前会话；`docgen/service`保留合法Jinja include并逐文件检查 symlink/越界与sandbox属性。CPU/I/O渲染在线程执行，原渲染全局状态用锁保护。`util/scoped_files.py`通过anchored FD发送受保护文件；旧URL、Unicode/nested、new/old MD5/MIME及Range/HEAD/ZIP保持。
- 精选上线只允许注册输出URL的精确快照；私有输入与工作区archive不公开，下线立即撤销。未知legacy owner不自动认领。原Model3D增加Cookie与正确session namespace，asset URL保留Unicode嵌套路径。

## 可复现命令

在项目根目录执行，不自动借用本机连接、不读取.env：

```bash
UV_CACHE_DIR=target/python-migration-uv-cache uv sync --project reactor-backend --frozen --group integration
reactor-backend/.venv/bin/python -m pytest reactor-backend/tests -q
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p5
# 原页面：以下命令创建新隔离root并保持服务，另终端使用打印的root：
reactor-backend/.venv/bin/python reactor-backend/tests/integration.py --phase p5 --serve
reactor-backend/.venv/bin/python reactor-backend/tests/ui_copy.py /absolute/new/reactor-p5-root
# 后端正常启动配置/离线加法迁移见 README，不以 serve 测试模型替代生产上游。
```

`ui`目录：`npm test -- --reporter=dot`、`npm run build`。后台本机MCP/原生Sandbox检查以及新建mysqld启动需要本机进程权限；受限沙箱不能加载系统Sandbox profile，不以其环境失败算生产代码失败。模型/图片仅测试目录的真实TCP fixture；Tool/数据库/文件/渲染器实际执行。

## 结果与真实用户流程

- backend全目录 **159 passed / 55 skipped / 16 warnings**；skip为未提供集成环境的门控测试，独立harness实测不计为skip通过。P4三传输本机MCP/真实Skill脚本回归通过。
- 全新隔离TCP/MySQL/SQLite/原Tool **46 passed**；管理员完整CRUD、enabled/expiry/revoke/CSRF，公开模型metadata/真实HTTP配置测试、SkillZIP与URL导入，图片mask/多参考/高分辨率503→chatfallback、历史owner与文件关联、主Agent自动使用真实附件（request_source=agent/Run/调用关联）、GenUI实时SSE/导出/精选公开撤销、真实文档和路径负例。原Java对实际Python账本 **5+2+11帧PASS**。
- 原UI全套 **434 passed / 2 failed（436总数）**；两项为P3已在HEAD复现的 `GeneralInput/index.test.tsx`旧“深度思考”断言、`WorkspaceMRag/utils.test.ts`旧默认URL断言，保持原失败，不删除或记全绿。TypeScript/Vite production build通过；原lottie eval/chunk大小警告保留。
- 原工作台浏览器：命名→P5 GenUI→tree+patch→HTML iframe按钮“交互成功”、Button send_message触发实际续轮；Unicode嵌套glTF实际加载并拖拽；刷新→近期会话恢复原树/patch/文件。生图页面实际生成→图片文件→刷新历史。管理员认证弹窗登录→原新增模型/API配置→“连接成功”，实际本机TCP provider请求。
- 独立GenUI PDF/DOCX内容验证及中文逐页视觉通过；原docgen PDF/DOCX、PPTX/XLSX/模板/图表真实内容通过，PPTX两页、XLSX首表及图表视觉检查通过。PPTX仍遵循原Office字体引用，缺CJK字体的阅读器无法显示中文；验收仅给LibreOffice子进程指定随仓字体目录后中文可读，未安装主机字体，也不宣称PPTX已嵌入字体。视觉初测发现CID字库及DOCX阅读器缺CJK，修复为随资源携带OFL Noto SC；GenUI PDF内嵌字体，GenUI与原docgen DOCX嵌入OOXML字体，保留主题字体alias。最终中文、标题、表格可读。字体约10MB，DOCX体积增加；无需主机字体安装，OFL及固定来源/sha256见资源目录。
- 离线admin-init新隔离空表成功，再执行非空拒绝；启动不做DDL。Symlink替换已注册canvas后的GET403、外访客下载/图片引用403、共享theme/template写隔离、合法include成功、越界/内部属性失败均实际验收。

原始日志/数据库/失败记录保留于隔离root。最新root与文件SHA见[机器证据](fixtures/p5-evidence.json)，浏览器界限见[页面证据](fixtures/p5-browser-evidence.json)。中间失败包括遗漏doc工具schema、隔离依赖、错误测试参数、docread双重路径处理、mac临时路径alias、Range代理以及测试Agent工具名/字段；修复后重新建隔离环境，未在旧root清库重试。

## 未验证项与限制

| 项目 | 本轮证据与未验证范围 |
|---|---|
| Micu真实图片供应商 | 真实adapter和本机HTTP wire/文件完整；外部凭证、真实生成/编辑/mask与配额/网络 U |
| Grok | 生产分支保留model/aspect_ratio/resolution/reference_image/image_urls与mask不支持的原备注；真实远端凭证及本轮Grok TCP实测 U |
| 真实LLM | 生产HTTP adapter保持；浏览器模型为tests fixture，实际供应商生成质量 U |
| 真实旧数据/文件 | 原schema与Java回放/新旧MD5合成证据；未提供旧MySQL/SQLite/文件授权副本，实际迁移 U |
| HTTPS/Nginx | localhost Cookie/CORS/CSRF/私有文件与3D成功；真实反代TLS、跨域Cookie/Range/缓存部署 U |
| 外部图源/模板/文档依赖 | 本地真实渲染和合法工作流验证；远程资源网络、部分Office阅读器字体嵌入兼容 U |
| P4语义记忆/远程MCP/E2B | 延续P4逐项U，不以本轮文档/管理CRUD宣称远端实测 |
| Tool路径边界 | 静态及文件发送FD负例通过；docread各第三方解析库的全部动态路径竞争不声明OS级隔离 |

P5本地实现和隔离证据不等于全部迁移/生产切换完成。完成后停止；下一入口为 `plan.md` 的P6，等待另行授权。默认Java/原部署和H2保留用于对照与回滚；回滚时停止Python单worker、恢复原Java入口，额外加法表可以保留，不执行DROP。

终检：826 个本地文档链接、26 个归档文件SHA256、wheel/sdist/P5 schema/加法SQL/字体及OFL打包、compileall和Git diff check通过。原workflow哈希保持。已关闭本轮浏览器测试标签并reset视口；已停止自己创建的preview/helper/backend/Tool/model/隔离MySQL进程，数据和日志保留。
