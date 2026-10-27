# LIIA 近期发现开发验收

日期：2026-10-27。身份：[#56](https://github.com/normaltank/DataBase/issues/56) 的施工自测快照，尚不替代 merger 集成、独立 Standards／Spec 审查或正式发布。固定规格为 [1.0](../docs/specs/拉脱维亚来源发现试点.md)，基线提交 `564d4e6d35864da250248b8c836dcf8bad96ad86`；最终审查比较基线由指挥固定为 `07855ff3ef2c18858390247666e023f9908acf12`。

## 实现与隔离

施工仅在 `liia-discovery-build/DataBase`／`codex/liia-discovery-build-20261027`。测试创建 Temp 合成库，浏览器端口 8871，未操作真实库、ThinkTank 或 8848。没有结构迁移，既有 LIIA 官网及 publications 目录地址没有改写，也没有新增试点来源身份。

来源档案提供固定官方 Opinions RSS 的手动发现入口；取得与预览不入库。服务端固定 30 天 UTC 日历窗口，条目按原时区日期归窗，保留缺项、覆盖限制与排除统计。公开描述作为来源字段保留，默认类型“其他”，摘要、署名和语言保持未知。正式保存复用现有事务、表单和来源／署名边界。

XML 专用读取路径共享既有 DNS、公网、固定连接目标、80／443、逐跳跳转、总时限、1 MiB 和四并发限制；固定 feed 跳转不允许离开官方订阅地址。单篇 MIME 白名单保持。DTD／实体声明、超限及畸形 XML 明确失败，条目链接仅作为不可信数据核验，不访问正文或附件。

`discovery_evidence` 保留原始题名、link、pubDate、GUID、description、字段出处、栏目／feed、取得时间、窗口及保存采用字段；签名绑定账号，候选身份跨重复取得稳定。正式 URL／DOI 与已保存候选均在事务内复查，官方裸域与 www 归一，人工合并后跟随当前记录。受限重复只给通用提示。

## 红绿与检查

测试边界沿用规格事先确认的公开 HTTP、真实浏览器、可读内容包及新目录完整恢复。网络测试替换系统 DNS／外部 socket 与时间，数据库为真实临时 SQLite；期望值人工固定，未调用生产解析器生成期望。

- 首个公开 HTTP 测试先得到新接口 404，完成实现后通过：取得不写库、原时区首尾日期、公开描述与摘要分开、人工题名／摘要保存及原始依据可读。
- 官方 www 与裸域的受限重复测试先失败，修复后预览、状态与保存一致防重，未披露题名／编号。
- [8 项专项 HTTP 测试](../tests/test_discovery.py) 通过，覆盖窗口、乱序、缺失／无效／未来日期、重复 URL／GUID、恶意链接、XML 声明与上限、来源伪造、登录／停用／CSRF／跨账号／签名、重复竞态、合并重试、保存末尾故障回滚、历史、内容包独立校验及新目录完整恢复。
- 外部传输边界验证拒绝私网 DNS、实际连接目标不符、非官方跳转、非标准端口及超大响应；100 ms 总时限五次均释放容量，四个在途 feed 请求同时阻止第五个 feed 与单篇请求。
- 受影响回归首轮 46 项中 1 项因 Windows 测试连接未关闭而在清理时失败；采用显式关闭后 8 项专项重新通过。该失败未当作应用通过。首次完整检查在已加载旧测试夹具时启动，发现清理问题后取消，修复后再完成完整检查；取消日志独立保留。
- 一次完整结束的 `scripts/check.py` 执行 323 项／506.412 秒，1 项按要求跳过外部 ThinkTank 检查，1 项旧 v5 恢复快照失败：不支持发现的来源因新增 `discovery_supported: false` 改变原有精确响应。修复为仅在支持来源追加 `true`；修复后重新运行发现、旧 v5 恢复、来源档案及目录的 23 项全部通过。该次全量结果如实为失败，不写成最终全量全绿；按本轮一次完整检查的要求，最终修复采用受影响回归。
- [LIIA 浏览器流程](../scripts/check_discovery_browser.py) 在 1366px 与 390px 通过：来源档案→手动发现→覆盖／缺项→分别编辑两条→切换→关闭刷新续作→取得 406 保稿→非法日期保存失败保稿→逐条保存→打开资料与依据→返回→再次取得防重→另一账号无前账号草稿。检查长题名、错误可见性、页面宽度及无浏览器脚本错误。
- 复用队列的[既有 RIS 浏览器回归](../scripts/check_ris_import_browser.py) 5 项通过；覆盖双宽度、正文、附件／失败恢复、多来源选择、旧字符串草稿及跨账号迟到响应。一次 390px 断言早于异步编辑器恢复完成，已使测试等待“保存本条并接续”可用后再核对；专项及全部 5 项重新通过。

复跑命令（本机 Python 为 `C:/Python312/python.exe`）：

```powershell
python -m unittest tests.test_discovery tests.test_assisted_intake tests.test_intake_deadline tests.test_intake_dns_compat tests.test_ris_import tests.test_translation -v
python scripts/check_discovery_browser.py
$env:DATABASE_BROWSER_PORT='8871'
python scripts/check_ris_import_browser.py
python scripts/check.py
```

修复后的受影响回归为：

```powershell
python -m unittest tests.test_people.PeopleTests.test_v5_upgrade_backs_up_preserves_old_work_and_repeated_start_does_not_create_people tests.test_discovery tests.test_source_profiles tests.test_source_catalog -v
```

交付前已执行 `git merge --no-edit codex/liia-discovery-20261027`（Already up to date）和 `git merge-base --is-ancestor 564d4e6d35864da250248b8c836dcf8bad96ad86 HEAD`。实际同步 SHA 为 `564d4e6d35864da250248b8c836dcf8bad96ad86`；上述最终检查在该同步后运行。完整检查及修复回归结果在本轮 Issue 交接中绑定最终提交。

## 交接与页面复核返修（2026-10-27）

返修分支 `codex/liia-review-fixes-20261027` 从集成 `86acbba04811a7c8da46ccb7783419e8b651758b` 建立，原施工分支与上述失败历史保留。merger 的提交差异检查发现浏览器脚本与发现测试文件末尾多余空行，本次已移除。指挥页面复核发现默认覆盖框堆叠原始时间、零值细目与长规则，390px 候选列表迟至约 665px 出现。

默认展示现改为发表日期范围、候选数、简短覆盖提醒与核对提示；原始取得时间、UTC 范围算法、官方栏目／RSS 链接、最早有效日期、完整统计、原始覆盖警告及排除原因集中到可展开的“来源与取得详情”。覆盖说明使用 16px 正文字号，候选列表在 390px 约 428px 出现。仅调整发现页展示和局部样式，采集、保存及通用 RIS 语义未改。

既有浏览器脚本使用 Temp 合成库、8872 端口完成 1366／390px 流程，1 项通过；已实际查看两种宽度的队列截图。另实际展开详情，核对原始时间、全部统计、覆盖警告与官方链接均可找到，截图及观察值保存在 Temp `liia-discovery-browser-jwjr3y4p`。完整流程截图为 Temp `liia-discovery-browser-opbuznut`；均仅原环境可查。首次选择 Chromium 1187 因本机旧版 Playwright 的 headless 参数而未启动浏览器，实际未运行测试；改用既有 Chromium 1134 后通过。临时详情观察脚本首轮第二次建同官网来源被正常拒绝，改为两宽度复用同一合成来源后完成。

同步最新集成仍为 `86acbba04811a7c8da46ccb7783419e8b651758b`（Already up to date），同步后使用相同命令复跑既有双宽度流程，1 项／7.364 秒通过；最终截图目录为 Temp `liia-discovery-browser-yd1bcfd6`，结果绑定返修交接提交。复跑命令为：

```powershell
$env:DATABASE_BROWSER_EXECUTABLE='C:/Users/27451/AppData/Local/ms-playwright/chromium-1134/chrome-win/chrome.exe'
python -c "import scripts.check_discovery_browser as check; import unittest; check.PORT=8872; check.URL='http://127.0.0.1:8872'; unittest.main(module=check,verbosity=2)"
git diff --check 07855ff3ef2c18858390247666e023f9908acf12...HEAD
```

本次按授权只补展示层定向验证，不重跑完整检查；集成后的全量与双轴审查由指挥安排。原全量失败仍按上文保留，不将本次浏览器通过写为全量通过。8872 服务在检查后停止，真实库、8848 与 ThinkTank 未操作。

## 本地证据与材料限制

浏览器截图与合成运行库保存在本机 Temp 的 `liia-discovery-browser-dfgrr6fb`；RIS 最终回归为 `ris-browser-4rbsw78w`。测试日志为本机 Temp 的 `liia-full-check.log`、`liia-affected-check.log`、`liia-final-affected-check.log`、`liia-full-check-cancelled-fixture.log`、`liia-ris-browser-check-final.log`。这些路径仅原环境可查，未复制进公开仓库，也不含正式研究库。

独立原站核查由指挥另行完成，详情已记 [#56 评论](https://github.com/normaltank/DataBase/issues/56)：2026-10-27 05:06 UTC 普通 HTTPS GET 取得 RSS，8,726 bytes，SHA-256 `2e0c2c8dbcf85d98c587a961bc07737272824d2f7e31423f0391a36f24120a1`。独立解析显示 20 条、2026-09-28 至 2026-10-27 内 6 条、1 条非占位描述；1622 与 1621 的页面 h1／可见日期分别与 RSS 一致。1621 为广播介绍，1622 描述含系列背景，均不升格为已核实文章摘要。原始 RSS、两个 HTML 和对照 JSON 只保存在原环境 Temp `database-liia-independent-20261027`。

软件合成验证证明限定流程及错误边界；原站核查仅支持该时点的六条题录及两页抽样，不证明 30 天栏目全部覆盖、完整作者身份、文章观点、翻译质量或真人跨人研究复用。正式部署、独立双轴审查和最终交付继续由指挥与对应任务记录。
