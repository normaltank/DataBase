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
