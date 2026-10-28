# LIIA 自动采集与快照：2026-10-28 开发验证

任务 [#62](https://github.com/normaltank/DataBase/issues/62)，固定规格 [1.0@b674040](https://github.com/normaltank/DataBase/blob/b67404070ed0960268a1c611b7036189e8858e02/docs/specs/自采集资料库与阅读前端重构.md)。这是本任务施工者的开发自测记录，独立审查、集成及最终放行以 Issue 的实际提交交接为准。

## 输入、边界与实现

从 `ef40db9c2f7fcb7a6ec89dbf5abb687f9553fed3` 的干净独立树开始，分支 `codex/autonomous-ingestion-build-20261028`。依赖 #60 已由 merger 集成并验证。本任务按已批准公开 HTTP、worker、真实浏览器及新目录恢复接缝执行 TDD，没有写真实库、读取 ThinkTank 或调用付费 AI。

结构17增加来源配置、持久 run／entry、专属禁登录系统主体和自动处理待办。后台入口与网页分离；固定 RSS、文章页及原始字节使用既有受控公网取得，阶段、租约和逐条结果在数据库中可续作。正式入库、出处、快照、历史和待处理接缝由记录服务在同一事务提交。网页快照原字节保存在 DB，因而不引入未登记文件或文件半写状态。

当前 LIIA 的页面文字统一保守视为来源网页说明，`work_body_available=false`，`work_body=null`、依据留缺，记录本身不填虚假摘要或实质正文。后续真正文适配须明确提供正文及依据，`substantive_input()` 只在两个条件满足时返回实质正文；页面文字非空或较长本身不授权概述／全文处理。原始 RSS 日期、点号描述、清洗页面内容、侧栏署名和正文署名均继续保留，角色不自动合并，研究对象国留待有据分类。

## 软件检查

- `python -m unittest tests.test_ingestion -v`：HTTP 配置权限、持久化、后台无会话入库、真实字节下载、失败后题录先读与重试、人工字段保护、历史／导出／新目录恢复、并发领取、进程中断续作、事务末尾失败回滚、隐藏重复、合并身份转向、相同字节不制造新版本、侧栏标签与空标签边界。
- TDD 的初始失败分别为缺少配置路由（404）、缺 worker 入口、缺 run 明细／导出快照、系统主体可被成员接口启用、重复巡检额外增加版本、侧栏 `Author` 标签误入姓名；对应实现后专项通过。附加故障检查最初有测试连接未关闭和错误选择不同提交责任记录合并，已关闭测试连接、改用合法同责任合并场景。
- `python scripts/check_ingestion_browser.py -v`：UI8903、独立动态端口合成 HTTP 源、Temp 数据库。实际启用→后台收到503→管理页查看错误→重跑→成功→阅读快照，1366／390两种宽度均通过；页面脚本错误0、全页无横溢、原站脚本未执行。截图和 `evidence.json` 在 `C:/Users/27451/AppData/Local/Temp/ingestion-browser-fsp9fo6y`，仅原环境可查。
- 显式 `start.ps1 -Port 8903 -NoBrowser -NoImport -DataDir <新Temp目录>` 实际启动 Web PID20224、worker PID104528；单停 worker 后再次启动，既有 Web 分支补启 worker PID97988；`stop.ps1` 后两个运行 PID均不存在。演练目录 `C:/Users/27451/AppData/Local/Temp/ingestion-launcher-5ce1e04df0da49399112a6139541bbed`，仅原环境可查。
- Python 完整合成检查与同步后检查结果在 #62 最终交接评论绑定准确提交；本文件不将运行中的检查预记为通过。

## 真实材料忠实性与覆盖

复用独立代理于2026-10-27 15:26—15:27 UTC保存的原始输入：`C:/Users/27451/AppData/Local/Temp/database-public-source-sample-20261027T1526Z/REPORT.md`、RSS、三份 HTML 和独立核对 CSV，仅原环境可查。没有重跑取得脚本或新增外站请求。离线对照报告 `C:/Users/27451/AppData/Local/Temp/ingestion-material-check-20261028.json`，仅原环境可查。

独立预期的 RSS20条、30天窗口6条得到一致结果。三份 HTML 原字节摘要值一致；1622侧栏 Dana Duda 与正文 Dana Dūda、Konstantinas Andrijauskas、Björn Cappelin 的名单分别保留；1621侧栏 Sara Elizabete Vinberga 与节目／制作角色分别保留；1620侧栏 Una Aleksandra Berzina-Cerenkova 与一条参与短句保持原状。三者清洗说明分别2669、820、111字符，均没有被长度升级为作品全文。政策简报原件、录音和电视逐字稿未取得，点号描述未变成摘要，没有自动生成观点、确认作者身份或补对象国。

RSS 当前20条只证明所见响应，不证明栏目完整覆盖；未遍历73页目录、未取得其余近期页或 Adobe／媒体原作品。网页原件与摘要值证明当时所取材料可复核，不证明来源观点真实、真人研究员复核、译文／身份正确率或跨人研究成果。正式服务主机、长期运行和备份责任仍须按部署安排落实。

## 恢复接续与同步复验（2026-10-28）

原施工树因工具路由故障改由受管工作树 `C:/Users/27451/.codex/worktrees/autonomous-ingestion-managed/DataBase`、分支 `codex/autonomous-ingestion-managed-20261028` 接续；原树保留只读。指挥逐字节核对后复制的25份 WIP 已保全为 `55b3af7`，没有重建实现或丢弃源码。接手者先核对 HEAD 与16项 tracked／9项 untracked，再读固定规格、Issue 全部评论和本记录。

合入集成 `ff02a2edc53c15568138b6c47487e1e132f4a79d` 后，`87c652d` 执行 `python -m unittest tests.test_ingestion tests.test_reading_feed tests.test_people.PeopleTests.test_v5_upgrade_backs_up_preserves_old_work_and_repeated_start_does_not_create_people tests.test_bylines.BylineTests.test_intermediate_v6_v7_v8_backups_upgrade_preserving_old_authors_without_matching -v`：24项、43.270秒全部通过。日志 `C:/Users/27451/AppData/Local/Temp/ingestion-managed-sync-ff02-20261028.log` 仅原环境可查。此为本次接续新结果；此前341项完整检查的2项失败及后续修复验证仍保留其历史身份，不改记为完整套件全绿。

同期 `node --check` 检查 `static/ingestion.js`、`app.js`、`sources.js`、`ux.js`，四份起停 PowerShell 脚本通过解析，`git diff --check ef40db9 HEAD` 通过。已复看原浏览器桌面管理与窄屏阅读截图、原材料对照报告；未增加外站请求。核对原起停演练目录已无进程状态文件，未见本任务原树／接续树后台残留。最终交接须再同步 #61 实际已集成的最新提交，相关结果以 Issue #62 交接为准。
## #61 集成后的最终复验（2026-10-28）

指挥确认 #61 已由独立 merger 集成后，合入实际集成 `28594fdefdc36146b48e1268b583dc938d4f4ee7`，得到 `069d7afc29b6587653dd9087b79a4d987dbb17ac`；无冲突，保留 #61 成品报告／资料夹行为、阅读正文顺序、译文兼容及本任务的管理卡片／阅读快照注入。结构仍为17，未取后续18迁移。

按指挥具体阅读反馈，先扩充已有浏览器接缝，在旧实现得到预期失败（缺少简洁“未取得所指作品全文”提示与默认折叠的取得依据）；`9840300` 将侧栏角色、内容摘要值／字节／适配器、详细取得说明和原字节下载收拢到“取得依据”，网页说明、简洁无全文提示与原站链接保持直接可读，取得尝试继续折叠。red 日志 `C:/Users/27451/AppData/Local/Temp/ingestion-managed-reader-red-20261028.log` 仅原环境可查。

在上述合并提交上实际执行：

- `python scripts/check_ingestion_browser.py -v`：1项、7.893秒通过；覆盖管理员启用→503→重跑→成功，新增普通研究员从新文章打开条目，1366／390 视口分别取得题名首屏、快照及展开依据截图。默认依据关闭、原始下载在展开后可见、脚本未执行、页面错误0、无横溢。共11张图及 `evidence.json` 在 `C:/Users/27451/AppData/Local/Temp/ingestion-browser-kaxap0t7`；日志 `ingestion-managed-reader-green-20261028.log` 位于同级 Temp，仅原环境可查。接手者已实际复看桌面／手机首屏及手机快照／依据。
- `python -m unittest tests.test_ingestion tests.test_reading_feed tests.test_discovery tests.test_people.PeopleTests.test_v5_upgrade_backs_up_preserves_old_work_and_repeated_start_does_not_create_people tests.test_bylines.BylineTests.test_intermediate_v6_v7_v8_backups_upgrade_preserving_old_authors_without_matching -v`：33项、55.247秒全部通过；日志 `C:/Users/27451/AppData/Local/Temp/ingestion-managed-final-sync-20261028.log` 仅原环境可查。
- 同步后的13份相关 JS 均通过 `node --check`；四份 PowerShell 起停脚本解析、`git diff --check ef40db9 HEAD` 通过。文档新增仓库路径有效；原有离线导出历史本机产物缺失仍有明确标注，没有补造证据。当前相关 Python 后台残留0、8903监听0。
- 当前适配器离线重读独立保存原件，RSS20／窗口6、三份HTML字节摘要值、侧栏署名及清洗字符2669／820／111一致，均不提供实质正文。新报告 `C:/Users/27451/AppData/Local/Temp/ingestion-managed-material-check-20261028.json` 仅原环境可查；没有外站新请求、真实库或 AI 调用。

本节为施工自测，不代替 merger 独立验收或 Standards／Spec 审查。未宣称完整套件已在当前提交全部重跑、原站全覆盖、真实作品全文、人工核对、研究结论或正式部署；既有341项与2项失败的历史状态不改写。最终交付 SHA 和同步 SHA 以 Issue #62 的交接评论绑定。
### 阅读内容顺序的补充复验

指挥复看上轮截图后要求网页内容先于维护折叠出现。本任务只将自己的快照注入从来源发现依据之后移动到摘要／正文之后，#60／#61 其余阅读、证据和权限逻辑保持。先增加首屏内容位置断言，旧位置 red 为1111.875px，超出900px视口；移动后 `python scripts/check_ingestion_browser.py -v` 1项、6.944秒通过，1366／390 的首次打开、快照和依据重新取视口图，下载依据图也滚动到完整证据块。

最新截图与 `evidence.json` 在 `C:/Users/27451/AppData/Local/Temp/ingestion-browser-5o3nnt5x`；red／green 日志为 Temp 下的 `ingestion-managed-reader-order-red-20261028.log`／`ingestion-managed-reader-order-green-20261028.log`，均仅原环境可查。已实际复看：390手机的题名、网页说明与原站入口同处900px首屏；桌面首屏可见快照标题和卡片开头，正文按现有内部阅读区滚动继续。`static/ux.js`、`ingestion.js` 的语法及 diff 空白检查通过；这次只变更显示顺序，33项接口结果保持为移动前相同后端内容的验证，不称已在显示顺序移动后重跑接口组。