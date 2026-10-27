# RIS 统一返修验证快照

日期：2026-10-27。范围：[#36](https://github.com/normaltank/DataBase/issues/36) 的 [#51](https://github.com/normaltank/DataBase/issues/51)／[#52](https://github.com/normaltank/DataBase/issues/52)，固定[标准题录交换规格 1.0](../docs/specs/标准题录交换.md)，规格提交 `d9129c294f428c61227dcb62c9a0f2389d4653eb`。依据为 [PR #53 独立双轴审查](https://github.com/normaltank/DataBase/pull/53#issuecomment-6433197208)：Standards 无阻塞，Spec 的 S1、S2 由一个返修代理统一处理。本文记录开发验证，最终复核、集成与交付状态仍以 Issues／PR 为准。

审查基线 `2f6845bb65e23df565b684e0ade600bd1a606c9f`，被审及返修起点 `b6d33dd39d1992e02847a4e74cba58ac490456b8`。返修树为 `ris-review-fixes/DataBase`，分支 `codex/ris-review-fixes`；实际执行 `git merge codex/ris-exchange-20261027`，返回 `Already up to date`，同步 SHA 同为 `b6d33dd39d1992e02847a4e74cba58ac490456b8`。

## S1：人工合并后同一预览条目可重复入库

在[公开 HTTP 回归](../tests/test_ris_import.py)中，预览无 DOI／网址的 GEN 条目，保存后以管理员公共合并接口保留另一条资料，再原样提交旧 token。修复前实际返回 `201` 新编号，断言 `409` 失败；修复后返回通用 `409`，原 token 的状态查询返回存活资料的当前编号和题名。

修正沿用归档中的单条交换依据，从原编号沿人工合并关系找到当前资料。写事务对旧条目的稳定身份继续防重；状态查询只在当前资料可读时返回当前信息。没有搬动归档依据到共享正文，也未新建身份、自动合并或改变合并权限。

补充回归通过两级合并、同成员重预览、旧／新 token 重试和状态恢复。私有记录对另一成员的独立预览及状态查询不返回题名或编号，跨账号 token 返回 `403`，响应不含旧／当前编号与题名。合法公共流程要求合并双方责任相同，外部资料的提交者不可转移，因此未通过绕过接口制造“原 token 的成员不再可读其本人提交资料”的状态；实现保留对当前资料的可读检查。

## S2：队列切换静默丢失多选关联来源

在[真实浏览器回归](../scripts/check_ris_import_browser.py)中，通过现有来源选择器的可见复选框选择两个期刊来源，切换到第二条再回第一条。修复前 1366px／390px 均只剩第一项；修复后两项完整保留。关闭并保留草稿后重新进入，仍有两项；保存后从公开资料详情读取，实际 `related_source_ids` 包含两条关系。

队列草稿现在按数组捕获多选值，恢复继续使用当前来源选择器。桌面回归另在本机持久草稿边界构造旧版单字符串值，重新打开后恢复第一来源，再通过当前选择器加入第二来源并保存，两关系均保留。原有正文、附件、显式身份确认、保存响应丢失后的恢复、账号隔离和迟到响应测试同时复跑。

## 实际验证与本机证据

所有资料与数据库均为临时合成材料；浏览器使用真实 Chrome、独立端口 `8864`。没有操作真实主树、研究库、ThinkTank 或 8848 服务。未修改固定独立 RIS 样本及 `expected.json`，未运行整组 `scripts/check.py`。

红阶段命令与结果：

- `python -m unittest tests.test_ris_import.RisImportTests.test_merged_entry_retry_is_blocked_and_status_follows_current_record -v`：1 条失败，实际 `201 != 409`；修复后同命令 1 条通过。
- `python scripts/check_ris_import_browser.py RisBrowserTests.test_multiple_related_sources_survive_switch_close_restore_and_save`：修复前两宽度均因第二来源丢失失败；修复后两宽度切换、关窗恢复及保存后的关系检查通过。补充截图时再次临时使用起点提交的原始 `static/ris.js`，同一回归仍在两宽度失败，随后恢复修正文件；日志准确记录这次原始版本的负对照。

浏览器命令统一先设置 PowerShell 环境变量 `$env:DATABASE_BROWSER_PORT='8864'` 和 `$env:DATABASE_BROWSER_EXECUTABLE='C:/Program Files/Google/Chrome/Application/chrome.exe'`。

同步后实际检查：

- `python -m unittest tests.test_ris_import tests.test_ris_export tests.test_assisted_intake tests.test_record_revisions -v`：30 条通过，97.390 秒，无跳过。覆盖新增合并重试及权限场景，以及既有辅助录入、独立 RIS 导出／跨库导入、历史／完整恢复和写入失败回滚。既有超限上传测试出现一条临时文件 `ResourceWarning`，不影响结果；不将其记作无警告运行。
- `python scripts/check_ris_import_browser.py`：真实 Chrome 5 项通过，27.272 秒；新增多来源场景与原主流程均在 1366px／390px 执行，旧字符串草稿场景在桌面执行。
- `node --check static/ris.js` 和定向 `python -m py_compile platform_app/ris.py platform_app/record_revisions.py tests/test_ris_import.py scripts/check_ris_import_browser.py` 通过；`git diff --check` 通过，新增／修改 Markdown 的 5 个本地链接目标均存在。固定 `expected.json` SHA-256 仍为 `6849e5ad000d32eef2846d2b8ba071ac5040f260d6bde0247035dd4c10da7e7e`。
- 测试结束后核查 `8864` 无监听服务。

原始日志保留于返修工作树的 `tests/artifacts/ris-review-fixes/`：`s1-red.txt`、`s1-green.txt`、`s1-merge-permissions.txt`、`s2-red.txt`、`s2-green.txt`、`post-sync-http.txt`、`post-sync-browser.txt`。此目录被忽略，仅原环境可查，未把日志或数据库上传到公开仓库。

已查看两宽度切换后的截图；窄屏修复前仅显示一个已选来源，修复后显示两个，选择器按钮和表单仍可读。截图目录仅原环境可查：

- 红阶段：`C:\Users\27451\AppData\Local\Temp\ris-browser-i4pitm8q`，`multiple-selected-1366.png`／`multiple-selected-390.png` 与 `multiple-switched-1366.png`／`multiple-switched-390.png`。
- 绿阶段：`C:\Users\27451\AppData\Local\Temp\ris-browser-u1tqf16c`，含同名截图和 `multiple-saved-1366.png`／`multiple-saved-390.png`。

上述结果证明本轮软件缺陷的修正及受影响流程的合成回归，不代表独立复核已通过、真实资料质量或真人跨人复用已获验证。
