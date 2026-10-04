# 授权测试副本的DDL、文件和历史验证命令

P0没有真实旧数据副本。下列命令交给后续明确授权的副本环境执行，本轮仅以新建合成副本测试校验器；不得把原.env连接、真实库或生产volume代入。日志包含schema/元数据，只留ignored target，不提交用户历史/路径内容。

## MySQL和SQLite

从项目根为副本创建独立目录。MySQL必须是由用户指定的测试副本、独立端口/账号；下例login-path应由用户预先设置为这个副本，密码不出现在参数/日志中。命令不包含DROP和数据写入：

```bash
mkdir -p target/python-migration-p0/copy
mysqldump --login-path=reactor-p0-test --host=127.0.0.1 --port=13306 \
  --no-data --skip-add-drop-table --skip-comments reactor_p0_test \
  > target/python-migration-p0/copy/mysql-schema.sql
.venv/bin/python tests/python_migration/audit_copy.py \
  --copy-root target/python-migration-p0/copy --ack-test-copy \
  --mysql-ddl mysql-schema.sql --sqlite fileinfo-copy.db --sqlite mrag-copy.db \
  --output target/python-migration-p0/copy-report.json
```

SQLite必须来自同一一致性点，使用SQLite backup API或既有已验证备份，而非活跃主文件裸copy遗漏WAL。本校验器不做备份，不 import Tool Runtime（防止create_all），用mode=ro+immutable+query_only读取已静止backup快照（不读活跃WAL数据库）。输出sqlite_master、table_info、index_list、foreign_key_list、行数和integrity_check；与已知正确的同点snapshot可加`--sqlite-schema expected-sqlite.json`，该文件是报告的sqlite数组。SQLModel `fileinfo`不是旧`file_info`；MRAG五表的源码字段索引见source-contracts.sqliteModels。

MySQL比对以仓库schema.sql为参考，保留所有列、NULL/default、keys、comment、engine/collation定义，忽略dump前言和AUTO_INCREMENT当前计数；DDL格式或列定义顺序变化会产生差异，需要人工分类，不能自动认定语义等价/自动修库。真实MySQL还需记录版本、SQL mode、timezone、collation并运行事务/CAS/JSON/decimal/旧数据查询；H2测试不替代这些。schema.sql本身可能落后于live副本，差异应更新决策/迁移版本，不清库。

## 旧文件和ID关联

仅在上述copy-root内放置完整授权文件副本和JSON数组`files.json`。每项必填：artifactId、fileId、requestId、storageKey、relativePath、fileSize、previewUrl、downloadUrl；可选fileHash为内容MD5。清单由副本中MySQL artifact→SQLite fileinfo.request_id/file_id→磁盘映射生成，不从真实生产API自动拉取。不得把绝对旧生产路径直接用于读取，应显式映射为副本相对路径。

```bash
.venv/bin/python tests/python_migration/audit_copy.py \
  --copy-root target/python-migration-p0/copy --ack-test-copy \
  --files-manifest files.json --output target/python-migration-p0/files-report.json
```

校验大小/哈希、必需ID/URL、重复storageKey关联冲突和root越界/所有symlink。只读文件，不请求公网URL或对象存储；URL可用性、旧新MD5 ID计算、MIME、Unicode/嵌套路径及ZIP预览下载另做Java/Python隔离HTTP/浏览器验证。缺失文件必须与history的missing/reason投影一致，不能跳过记录。

## 旧历史和写入回滚

用同一只读snapshot分别启动已隔离Java和将来的Python测试进程，连接到副本且禁用模型/工具副作用。分别导出同一访客cookie身份下的sessions/list/detail HTTP JSON；可用本P0runner的同形 capture `history.list/detail{status,contentType,body}`，将数据仅存ignored copy-root。

```bash
.venv/bin/python tests/python_migration/compare.py --java-capture \
  target/python-migration-p0/copy/java-history.json \
  target/python-migration-p0/copy/python-history.json
```

内置归一仅针对P0单run两帧taskId；真实旧历史有不同数量时先列出逐case精确JSON pointer数组及引用一致性约束，保存为ignored文件，并加`--dynamic-pointers target/python-migration-p0/copy/dynamic-pointers.json`。pointer指向protocol_view中的路径，例如`/history/detail/body/json/data/runs/0/replayFrames/0/resultMap/eventData/taskId`；非P0 session不会自动套用两帧规则，不能全局删除UUID/时间。比较HTTP/error/null/时间/ID、run status/count、LLM/tool/artifact关联、working memory scope、GenUI tree/patch、来源与missing文件事实。仅比较详情不是旧会话续轮验证；新写入和回滚使用分开的两份可写副本，验证Python新行由Java读取，再drain→切回Java→canary。不得让两者争写同session、重放真实外部副作用或把空库通过写成历史兼容。

目前以上真实副本、HTTP浏览器、rollback证据均U。P0提供命令和校验工具；实际数据/用户Cookie/外部服务必须由后续授权环境提供。
