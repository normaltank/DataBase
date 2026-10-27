# RIS 选中导出开发验收

日期：2026-10-27。范围：[#52](https://github.com/normaltank/DataBase/issues/52)，固定[规格 1.0](../docs/specs/标准题录交换.md)，规格提交 `d9129c294f428c61227dcb62c9a0f2389d4653eb`。本文为本任务开发验证快照；集成、独立双轴审查、最终 PR 交付由 Issues 记录，本文不另建待办台账。未部署或操作真实研究库、ThinkTank、8848 服务。

## 实现与接口

`POST /api/library/bulk/export-ris` 接收 `{ "ids": ["稳定编号"] }`，沿用当前登录／CSRF 和显式 1—100 条选择，单次读取事务核查有效状态、可读权限与类型，整次成功才返回附件。期刊文章 JOUR、外部报告 RPRT，仍为“其他”的已导入 WEB／ELEC 为 WEB，其余外部资料 GEN；个人成果、研究笔记、摘录和目录译稿拒绝本次导出。旧 CSV 接口与页面入口保留。

输出当前 TI、TT 与原题名不同时的明确 N1（`Original title: …`），不读取旧题录字段快照补空。当前完整署名文字与活动结构署名按序完全一致时逐项 AU，否则整行保留；待确认署名和机构署名同样保留，不按逗号猜人。规范 UTF-8 无 BOM、CRLF，单值中的控制符和换行变为空格，无法构造新标签／记录。RIS 不包含未知标签、内部路径、权限、成员身份与历史；内容包与完整备份保留其各自范围。

页面复用账号／页面／请求代际检查，在响应头及文件内容读取后分别检查当前上下文，失败保留选择，旧账号迟到结果不触发下载。

## 固定独立材料与证据边界

[合成样本](../tests/fixtures/ris_independent/README.md)由 Agent 在导出实现前独立制备，不是真人资料或真人复核。`expected.json` SHA-256 保持 `6849e5ad000d32eef2846d2b8ba071ac5040f260d6bde0247035dd4c10da7e7e`。实际 HTTP 和浏览器下载交给独立进程中的 rispy 0.10.0，逐字段比对 core／resolved_conflict；故意改错题名的样本 10 必须失败。参考输出 08 只供工具自检，不充作应用验收。

修订冲突样本时，测试通过公开保存接口显式提交已修订的两条 pending 结构署名；随后仅改整行署名时，测试要求回退成一条 AU，不猜分号或姓名边界。额外固定断言覆盖 TT、N1 语义及清空后不复活。原始固定期望未按输出修改。

rispy 为测试依赖，经 [requirements-test.txt](../requirements-test.txt) 与 CI 安装；缺失或版本不符会失败，不静默跳过。reader 默认对重复 SN、别名和结构损坏的局限在样本说明中保留，本轮不声称任意 RIS 方言无损兼容。

## 实际验证

同步集成：`git merge codex/ris-exchange-20261027` 返回 `Already up to date`，实际同步 SHA 为 `4ea265a3591b895040f124aba20be9bb7b53ffcb`。以下受影响检查在此同步后执行，没有运行整组 `scripts/check.py`。

- `python -m unittest tests.test_ris_export tests.test_ris_import tests.test_bulk tests.test_assisted_intake tests.test_bibliography_search -v`：35 条通过，37.872 秒，无跳过。覆盖独立逐字段输出、BOM 输入、当前修订和清空、多语题名、有序及机构署名、日期精度、页段／文章号、多 ISSN、缺项、TAG 注入、选择顺序／去重／上限、未登录／CSRF／停用、权限变化、不支持类型与失效合并编号；既有 CSV、辅助录入、出版字段、历史及恢复相关回归通过。既有导入用例出现一条临时文件 `ResourceWarning`，不影响测试结果；未将其描述成无警告运行。
- 同组导出测试将实际下载导入另一个新临时库，逐条从公开详情读取并比对固定语义；原库编辑后历史恢复，下载仍匹配 core。管理员完整备份恢复至新目录，重新登录后原始依据保持；可继续修改题名、署名、清空 ISSN 并导出当前值。
- `python scripts/check_ris_export_browser.py`：真实 Chrome，2 个测试通过，10.208 秒；两个测试均在 1366px 和 390px 执行。五条 core 实际选择／RIS 下载在两宽度分别通过独立 reader，CSV 实际下载保持。混入笔记、权限收回时均不下载且保留选择；跨标签退出并切换账号后，释放旧请求的成功响应也不下载。检查页面无横向溢出、无脚本错误；已查看窄屏 core 和桌面混合失败截图，按钮与提示完整。
- `node --check static/bulk.js`、Python 定向语法检查、新增／修改文档链接检查及 `git diff --check` 通过。施工说明原有历史本机证据链接不作为公开可用证据；整文件扫描仍可发现其未随仓库保存的旧 `browser-checks.json`，本轮保留历史身份。

红阶段分别保留其实际身份：恢复后先运行新增真实浏览器选择测试，1366／390 均因页面缺 RIS 按钮失败，添加入口后通过。另将当前公开 HTTP 下载测试复制到隔离的集成基线源代码副本（上述同步 SHA，无真实数据），确认旧基线以 `404 != 200` 失败；这是接续后的测试敏感性负证据，不冒称为原代理实现前日志。原代理已保存的首个 HTTP 测试在接续初查时通过。

本机原始产物仅原环境可查，未提交数据库、下载文件或截图：

- 最终浏览器：`C:\Users\27451\AppData\Local\Temp\ris52-final-1f6685d13d644608948fa5ffa56e31ef`，含 `browser.log`、两宽度 core／单条 RIS、CSV 和成功／混合类型／权限／账号切换截图；脚本结束后停止 8862 服务。
- HTTP 基线负证据：`C:\Users\27451\AppData\Local\Temp\ris52-http-baseline-red-49vke6qp\baseline-red.log`。
- HTTP 回归末段日志：`C:\Users\27451\AppData\Local\Temp\ris-export-browser-3en64cvl\http-regression-tail.log`；完整命令输出另见当次工具记录。

本轮证明限定格式映射及合成软件流程。真实资料真实性、专业译文质量、任意供应方兼容、真人跨人研究复用及生产部署均未据此验收。最终提交 SHA、clean 状态、merger 接收和完整检查／独立审查由任务交接继续绑定。
