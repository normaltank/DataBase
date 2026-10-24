# 人物 Wiki 首版：开发验收与交付证据

日期：2026-10-24。状态：七项流程已实现并集成，开发及指挥方独立验收完成；Standards 原 3 项 P3、Spec 原 1 项 P2 均已修复并分别复查关闭。本记录集中维护本轮验收结果，交付入口为 [PR #13](https://github.com/normaltank/DataBase/pull/13)，精确提交的 CI、合并与本机切换结果由 [父任务 #1](https://github.com/normaltank/DataBase/issues/1) 维护。

范围依据：[父任务 #1](https://github.com/normaltank/DataBase/issues/1)、[最后一项 #12](https://github.com/normaltank/DataBase/issues/12)、[规格 v1.1 固定发布](https://github.com/normaltank/DataBase/blob/985b3d3cf857938e4eaed9f37051b278cb081a29/docs/specs/作者档案与研究对象关联.md)。业务场景与验收条件未改；[当前规格](../docs/specs/作者档案与研究对象关联.md) 只更新状态和证据入口。

## 源码、环境与证据归属

#12 在 `codex/wiki-delivery` 独立工作树实施，起点为 `b6d32f983dfda266e796888f6322d819041579cd`，包含已集成的 #6—#11，结构版本为 10。本轮应用代码没有新 DDL，结构版本仍为 10；源码以包含本记录的 #12 提交及 Issue 交付摘要追溯。

开发验收只使用自建合成资料、演示成员、真实临时 SQLite 和受控文件。服务限定 127.0.0.1:8857；未访问或改写真实 8848、主工作树数据、ThinkTank、真实账户材料或指挥方的独立样本。当前与历史头像均为本机生成的纯色测试图。数据库、备份、下载包、日志和截图留在本地，仓库仅保存合成摘要及可重建的固定夹具。

本轮本机证据根目录为 `%TEMP%\wiki-delivery-20261024-builder`，**仅原环境可查**。下列文件名均相对此目录。`browser-results.json` 区分真实页面操作与 HTTP 预置，列出对象编号、视口测量、截图和浏览器日志。完成时自己的页面已关闭、临时视口已 reset，8857 进程按完整命令及数据路径核对后停止，端口无监听。

历史证据单独使用：#6 `86031c5`、#9 `75654bd`、#7 `32a60f5`、#8 `b7af13d`、#10 `188bebd`、#11 `0aeafb8` 各任务的当次结果见 [施工说明](../docs/施工说明.md)。其中 #11 的桌面／390px 连续合并及私人笔记延后处理证据位于 `%TEMP%\wiki-split-20261024-builder`；指挥方另在集成 `b6d32f9` 实际走通前半段页面流程，见其本机 `wiki-root-acceptance-20261024/browser-front-half-results.json`。这些只证明所列版本与操作，不冒充最终 #12 的独立验收。

## 本项实现与红绿结果

人物详情增加可操作的离线导出入口，复用既有内容导出、正文、引用及表格渲染。新增 [公开导出投影](../platform_app/content_export.py)，在同一 ZIP 中保留姓名写法、介绍／出处、任职依据、当前与历史身份、可读作品与笔记关系、头像及附件。人物参数真正限定范围，空值 400、未知编号 404；旧编号解析到当前人物。HTML、JSON 与文件列表使用同一投影，包内链接为相对路径。

权限按导出时的成员逐条检查。已主动共享的当前笔记保留可见，旧私人原记录的编号、标题、链接和自动别名仍过滤；身份事件的内部 before／after／choices JSON 不进入可读包。只使用已公开的身份组件与可见关系；私人第三人端点仍可参与内部并发检查。待复核研究对象保留状态、原对象及依据，单列且不计入已确认笔记；已移除／待确认署名不计入当前确认作品。同名关系附稳定端点编号，历史任职显示实际人物。

完整恢复增加语义图校验：历史头像引用、研究对象当前／原始／历史端点和版本链、署名历史前后连续性、事件前后关系集合完整性、当时的事件依赖、幂等结果与事件人物一致性。兼容合法历史状态与后续类型变化；对重新计算文件清单的恶意损坏也拒绝，失败后目标新目录不存在。

新增 [6 项导出验证](../tests/test_person_export.py) 与 [8 项恢复验证](../tests/test_person_recovery.py)。通过公开 HTTP、真实临时库、完整 ZIP 与文件读取验证结果；仅在受控备份副本中主动损坏 SQL 并重算清单，用于证明恢复拒绝。关键红→绿日志如下：

- 人物限域与完整关系：`export-scope-red.txt`／`export-scope-green.txt`、`export-relations-red.txt`／`export-relations-green.txt`。
- 被省略的关系快照、错误重试人物、悬空对象历史、旧历史头像：`restore-snapshot-red.txt`、`restore-retry-red.txt`、`restore-subject-history-red.txt`、`restore-old-avatar-red.txt` → `restore-four-gaps-green.txt`。
- 捏造署名前值及遗漏真实依赖：`restore-byline-chain-red.txt`／`restore-byline-chain-green.txt`、`restore-dependency-red.txt`／`restore-dependency-green.txt`。
- 原文引用笔记缺少导出版本字段、空人物误报身份循环：`export-evidence-red.txt`、`export-empty-scope-red.txt` → `export-evidence-empty-green.txt`。前者由指挥方异源样本发现，本项另建合成样本复现后修正。
- 实际离线阅读发现同名端点与历史任职归属不够清楚：`export-identity-label-red.txt`／`export-identity-label-green.txt`。

第一轮完整检查为 154 项、153 通过、1 外部导入跳过，159.213 秒；此后修正离线身份标签，因此在最终冻结的应用代码上再次执行 `python -B scripts/check.py`：**154 项，153 通过，1 跳过，155.470 秒，退出码 0**，日志 `full-regression-final-code.txt`。跳过项为默认关闭的真实外部导入，未探测或读取试点源目录。`node --check static/people.js`、`git diff --check` 通过，最新集成基线合并返回 Already up to date；7 份修改文档 UTF-8、151 处仓库相对链接／锚点核查，无新增断链。施工说明原有一处被忽略的历史本机 JSON 在克隆中不存在，已明确标为“仅原环境可查”，未上传原产物。结果见 `document-check-results.json`。指挥方集成后检查和 CI 不由这份开发结果替代。

## 旧版兼容与恢复继续操作

原有真实固定 schema 5 及 `affiliations_v8` 夹具继续随全量复跑；旧的手写 schema 6、由升级过程取得的中间 7／9 备份仍保留各自身份。本项补充 [单一生成器](../tests/fixtures/build_person_delivery.py) 和 `person_delivery_v6`—`v9` 的 SQL／JSON，按以下真实旧版应用依次通过合成 HTTP 产生，正常测试无需 Git 或外网：

- schema 6：`86031c59290c3f52b39c4fe1e568ed5b8a9fbb09`，非空人物、两张历史头像、原始资料／附件／笔记／固定引用。
- schema 7：`75654bdc5fef76f0bd7b530d30ced2fcb407a2fc`，增加多对象、研究对象修改及移除历史。
- schema 8：`32a60f5786b379cbafe4256a5a5b24fb60663c4c`，增加个人／机构／待确认署名及解除历史。
- schema 9：`b7af13d698c6ecdf8dd75d7577caa7346852fffa`，增加多时期任职、文章单位及其修订／移除历史。

1—4 没有据此声称取得冻结旧应用：测试从明确的基础 schema 1 重建合成资料、作者、附件、专题和修订，通过实际增量迁移链生成 2／3／4 的备份。每版均恢复到新目录、启动至 10、重复初始化、检查旧字段与文件／历史，继续编辑原始资料；旧个人成果仍待作者显式确认，未授权改写拒绝。真实旧版 6—9 另逐项比较原应用 HTTP 输出、头像与上传文件，继续修订人物、译文及署名，固定报告快照保持。日志：`legacy-fixture-build.txt`、`legacy-real6-9.txt`、`legacy-base1-4.txt`。

本轮 UI 创建的合成库进一步加入两次活动合并、后续任职、私人笔记及头像替换（这一阶段为明确记录的 HTTP 预置），生成 `active-chain-complete-backup.zip`，恢复到全新 `ui-recovered-active-chain`。清单 4 个文件含数据库、上传附件和两张当前／历史头像，逐个 SHA 一致；三成员共 **108 份 HTTP 响应完整一致**。证据：`recovery-files-results.json`、`recovery-http-before.json`、`recovery-http-comparison.json`。

在恢复后的 390px 页面先看早期合并的依赖阻断，打开后续合并并分配新增任职，依次拆回后续与早期合并；独立改归第三人、已解除署名和后续字段保持。作者随后明确将私人待复核对象改选为恢复后的另一人物，机构对象和正文保持，另一私人待复核关系仍待其处理。再编辑人物介绍／出处并从详情导出。HTTP 补验 5 份记录的正文、原始署名、作者确认／授权、固定原文及报告采用快照保持，两条原合并同键返回原结果；重新备份并第二次恢复至新目录成功。证据：`verify_after_ui.py`、`recovery-after-ui-results.json`。读取时的动态 `current_version` 会随所引笔记变化；固定采用版本及快照逐项不变。

## 实际页面与离线文件

本轮 Edge 经 CUA 在 **1366×900** 实际创建三个人物（含两份同名档案）、姓名写法、介绍表格、出处及头像；创建机构、期刊、任职、期刊文章、署名／文章单位与附件；从人物创建四对象研究笔记，选择原文、定位和文件；比较并显式选择五项身份字段后合并、访问旧入口；纠正第三人署名、解除原署名、新增署名及任职后由同事拆回。预览后私人笔记的 HTTP 并发改动触发 409，页面分配和依据保留，重比清除旧确认，再确认成功。私人笔记／固定报告及并发编辑明确为 HTTP 预置，不称为页面录入。

**390×844** 本轮重点实际执行恢复后的依赖顺序、拆回分配、作者延后复核、继续编辑与人物导出；前半程窄屏建档／关系／冲突操作另有上述 `b6d32f9` 和 #11 历史证据，不冒称本轮重做。关键截图均实际查看过：`desktop-created-person.jpg`、`desktop-multiple-subject-note.jpg`、`desktop-split-conflict.jpg`、`mobile-restored-dependency.jpg`、`mobile-restored-export.jpg`、`mobile-restored-pending.jpg`、`mobile-restored-author-reviewed.jpg`、`mobile-restored-continued-edit.jpg`。`desktop-work-relations.jpg` 记录填写文章单位的表单，不用它证明已保存详情。

实际页面按钮下载了三份 ZIP：桌面同事、恢复后窄屏同事、作者继续修订后的窄屏人物。`inspect_export.py` 分别核验 42／70／60 个相对 href／src 都存在于包内，JSON 与文件列表一致；同事包不含两条私人笔记标题，作者包含自己可读的笔记。证据为 `desktop-export-results.json`、`mobile-colleague-export-results.json`、`mobile-author-export-results.json`。

解压目录经仅绑定本机、仅提供该合成包的静态预览读取，实际点击人物→笔记／作品→附件，原文附件文本正确；该服务没有应用 API。最终包在桌面与窄屏实际查看，当前及历史头像均加载，表格可读。DOM 核验窄屏 `innerWidth=390`、`scrollWidth=375`，截图内容宽 375（不含滚动条）；桌面 `innerWidth=1366`、截图内容宽 1351。关键图为 `mobile-offline-profile.jpg`、`mobile-offline-note.jpg`、`mobile-offline-table.jpg`、`mobile-offline-final-profile.jpg`、`desktop-offline-final-profile.jpg`。

限制如实保留：浏览器自动化禁止 `file://`，因此没有声称自动化直接打开文件协议；相对文件实际通过上述静态根验证。下载事件通知一次超时，但页面 200／下载状态与实际 ZIP 均已独立核实。初次移动离线截图误用了仍为桌面的标签，发现后重设选中标签、测量 DOM 并重新截图，旧画面不计窄屏证据。恢复后浏览器日志只有 Zotero 扩展连接错误，未见应用来源脚本错误，不宣称浏览器绝对零错误。

## A01—A20 开发覆盖索引

以下自动场景在最终 154 项检查中全部实际执行。页面证据注明本轮或历史，不以单一截图替代 HTTP 权限与恢复检查。

- **A01**：[人物基础测试](../tests/test_people.py) 的独立同名建档及安全介绍／历史场景；本轮桌面建档、空作品状态、头像／表格截图。
- **A02**：人物基础测试覆盖原名、中文名、别名及同名隔离；本轮桌面独立同名 Gamma，离线关系以编号区分。
- **A03**：[署名测试](../tests/test_bylines.py) 的多个人／机构／待确认及顺序场景；本轮桌面期刊作品录入与离线作品实际阅读。
- **A04**：署名纠正、待确认、解除／历史恢复场景；本轮桌面改归第三人及移除，恢复后仍不复活。
- **A05**：[任职与文章单位测试](../tests/test_affiliations.py) 的并行时期、未知日期、稳定署名及发布关系区分；本轮 UI 机构／任职／文章单位，#8 历史两端窄屏验证。
- **A06**：[笔记研究对象测试](../tests/test_note_subjects.py) 的四对象、移除及引用不推定关联；本轮桌面四对象共用笔记，恢复后机构对象保留。
- **A07**：上述笔记授权／撤权／代交与隐藏结果场景，身份测试的私人来历及第三人过滤，导出按三成员权限投影；本轮同事／作者页面及 108 份跨成员恢复比较。
- **A08**：人物、署名、任职和对象集合版本冲突的 HTTP 验证；#6—#9 当次桌面／窄屏保稿证据，指挥方 `b6d32f9` 第二窗口修改后保稿记录。
- **A09**：[身份测试](../tests/test_person_identity.py) 的比较选择、旧入口及旧选择解析；本轮 UI 明确五项选择、合并、打开旧编号。
- **A10**：身份测试覆盖人物／关系／隐藏端点／事件变化、重复键和事务失败；本轮复杂拆回预览 409 及重比，#10 当次合并预览变动证据。
- **A11**：身份测试的后续字段、独立纠正、解除、新增作品／任职及显式分配；本轮桌面合并后新增与拆回、恢复后窄屏分配。
- **A12**：身份测试的逆依赖拆回、循环／类型拒绝、系统版本不误阻断；本轮 390px 实际先拆后续再拆早期，第三人纠正及解除保持。
- **A13**：身份、署名、笔记测试及新增导出原文版本场景验证固定依据、正文和作者权；本轮补验 5 份记录并第二次恢复。
- **A14**：人物基础测试的真实图片类型／大小、替换、移除、历史恢复；#6 当次 390px 无效上传保稿；本轮蓝／橙当前与历史头像导出、恢复及实际加载。
- **A15**：旧版兼容章节所列真实固定及明确重建夹具，逐版恢复升级、重复启动、正文／文件／历史／作者确认保持；本轮没有真实材料导入。
- **A16**：[导出测试](../tests/test_person_export.py) 全六项；三份 UI 下载、权限区别、全部相对链接存在、实际离线图片／表格／作品／附件可读。
- **A17**：[恢复测试](../tests/test_person_recovery.py) 全八项及身份完整恢复／私人复核场景；本轮 108 响应、两次新目录、当前／历史头像、继续操作与同键重试。
- **A18**：本轮桌面全前半链路与 390px 恢复后流程、导出／离线；前半程窄屏使用明确版本的指挥方 `b6d32f9` 及 #11 页面证据补足，见本记录页面章节。
- **A19**：署名、任职、笔记和身份测试的既有来源／资料合并、类型更正、历史恢复；新关系、原始来历与现有正文权限保持，错误类型阻断。
- **A20**：身份测试的隐藏私人新增边、独立更正／移除、当前端点新鲜度、待复核／作者明确分配；本轮桌面 409 保稿、重新比较、恢复后 390px 作者改选，正文及其他对象不变。

## 操作契约与后续衔接

所有业务读取须登录，修改带当前 `X-CSRF-Token`。`/api/people`、单个人物及 `/history` 提供稳定人物 ID、当前版本、姓名／介绍与头像；`/works`、`/research-notes`、`/employments` 读同一身份关系。署名 `/api/records/<id>/bylines`、文章单位 `/affiliations`、任职集合及笔记研究对象保存携带当前对象／集合版本，历史保留稳定关系编号与依据；权限仍由原有可读范围及作者授权决定。

`/api/people/merge-preview` → `/api/people/merge` 和 `/api/people/identity-events/<event_id>/split-preview` → `/api/people/split` 先取得服务端预览编号，再提交显式字段／关系选择、依据、确认和成员绑定的幂等键。预览后状态改变返回 409，重比并重新确认；同键同意图返回持久化原结果。身份历史按当前权限投影，内部全图用于事务、新鲜度和完整恢复。笔记研究对象待复核经独立的授权确认操作处理，普通正文保存不冒充确认。

`GET /api/export/content?person=<id>` 使用真实范围，返回原 `research-content-v1` 包，在既有内容旁加入 `people`、`avatars` 及路径元数据；JSON 与相对 HTML／附件对应。完整备份与恢复继续使用现有管理及维护命令，恢复只接受不存在的新目录，验证失败不发布目标。使用方法见 [README](../README.md#备份与恢复)，没有新增在线上传恢复界面。

旧版 6—9 恢复后，测试通过相同稳定 ID 继续修改人物版本、原有译文字段和署名关系；报告固定引用不变。本轮真实 UI 也在恢复后继续使用原 ID 完成身份纠错与笔记改选。这些已用的身份、关系、证据和版本可供未来评价／翻译引用；未构造空评分或翻译 API，未冻结评价算法或外部翻译服务。

## 指挥方独立验收与发布

以下由指挥方直接执行，原始证据位于 `%TEMP%\wiki-root-acceptance-20261024`，**仅原环境可查**。与开发方的数据、备份和页面样本独立，未用开发自测代替独立验收。

初次 #12 精确提交 `29ba608851eb51893f038c163359999a10648ab2`：三成员 82 份恢复后 HTTP 响应与既有独立基线完全一致，6 份不同成员／范围的可读导出通过，4 类主动损坏并重算清单的备份在目标发布前被拒绝。连续合并、后续独立纠正／解除、私人笔记延后复核、固定正文／引用和两次新目录恢复均通过。记录为 `phase12-independent-final12.json`、`phase11-result-delivery-final.json`。

该版本实际页面验收从先前独立 UI 备份恢复新目录，修订人物介绍 v3→4，多对象笔记正文及身份说明保留；页面下载包的 47 条相对链接有效，390／1366 离线阅读、8 个当前／历史头像引用及人物↔作品链接通过。`browser-final-source.json` 的 42 个应用文件指纹与 `29ba608` 完全一致；`browser-final-results.json`、`browser-final-export-results.json` 与已查看截图记录实际操作。此次页面日志无 warn／error。初次集成 `ee586e4266644a94dd66879aecda3863abaf2dcb` 的 [Windows／Ubuntu CI](https://github.com/normaltank/DataBase/actions/runs/40082482141) 通过。

双轴审查后，修复提交 `fced71a8411859be7a39ca0f347c49eaadc68c01` 合入 `fcf34174c2e836017f035df2b0cf896bbcb2cd6e`，两者 tree 都是 `b7aa5548b748cb377b887666a7daf63f6ccc1a04`。指挥方在干净的精确修复提交重新运行独立样本：

- 旧基线 82 份响应的既有字段保持，唯一许可增量 `institution_hints` 的结构、去重及实际任职依据另行验证；随后将新响应完整备份恢复到新目录，三成员 82 份响应逐字段一致（含权限拒绝）。结果为 `phase12-independent-reviewed.json`，完整响应往返备份 SHA-256 为 `419c776614fa01cfcd5b516e135d8dad274363b12caeaa4270b11b430d6c1205`。
- 6 份当前代码生成的权限导出、4 类损坏备份拒绝，以及恢复后继续编辑人物／笔记和处理待复核对象通过；不把“忽略新增字段后的旧基线比较”称为新 API 全字段比较。
- `phase11-result-reviewed.json` 再次通过连续合并依赖、逆序拆回、第三人独立纠正／解除、隐藏私人改动使旧预览 409、作者延后确认及两次新目录恢复；正文、负责作者权限与固定引用保持。
- 独立页面复验在 1366×900 和 390×844 搜索两份无简介的同名人物，用各自机构线索辨认；历史任职明确显示 2010—2014。页面保存人物草稿，工作台／我的草稿类型一致，继续编辑恢复原输入；研究对象候选保留机构线索，辅助文字实测 `rgb(82,97,116)`，390px 无横向溢出。`browser-reviewed-results.json` 与六张已查看截图记录结果，本次日志无 warn／error；`browser-reviewed-source.json` 将 42 个应用文件指纹绑定到 `fced71a`。自己的页面关闭、临时视口复原，8858 按完整进程命令核对后停止。

最终应用的开发全量为 156 项，155 通过、1 项真实外部导入按条件跳过；精确集成 `fcf3417` 的 [Windows／Ubuntu CI](https://github.com/normaltank/DataBase/actions/runs/40084156656) 均通过。后续交付文档提交没有改应用；最终 PR head 的 CI 结果由 PR 与父任务同步，避免把旧提交检查写成新提交检查。

真实 schema 5 一致备份分别在初次交付与 `fcf3417` 的全新隔离目录升级至 10；旧表全部原字段的行指纹及登记附件保持，重复初始化、升级后完整备份再恢复一致，16 张新增表均为空。原报告在本机 `%TEMP%\wiki-live-upgrade-20261024`，不上传真实内容。此处记录隔离预检；切换时另停旧进程、再做新备份和精确版本预检，之后核验本机实际库，最终执行结果以父任务 #1 为准。

35 个用户场景与 A01—A20 的业务范围未变。首次升级不按姓名自动建档；人物与作品需有据人工关联。正式影响力评价、自动翻译、真实多人部署及外网公开仍在本轮范围之外。

收尾同步 PRODUCT、README、文档目录、施工说明、长期路线、规格与本验收记录；另检查已有工作流文档，共 8 份 UTF-8 文档、158 处仓库内链接／锚点通过，`git diff --check` 通过。既有被忽略的历史本机 JSON 仍标为仅原环境可查，没有为补链接上传旧产物。记录为 `documents-release.json`。

## 整组审查修复：开发方补验（2026-10-24）

本节只记录开发方对指挥方交回的 Standards 三项、Spec 一项发现的修复及补验。起点为原交付 `29ba608`，工作树干净后快进到指定集成 `ee586e4266644a94dd66879aecda3863abaf2dcb`；只在 `codex/wiki-delivery` 工作树修改。原审查报告、指挥方独立补验、集成及发布结果由指挥方另行记录，不据本节提前认定部署完成。

修复保持 v1.1 业务含义、原权限／正文／引用与 schema 10：

- **辅助文字颜色：** 研究对象选择器使用既有语义变量 `--text-muted`，替换未定义的 `--muted`。按低风险样式修正处理，没有新增复述 CSS 实现的测试。
- **系统修订来历：** 拆回识别系统版本改用已完成身份事件中相同人物／版本的真实 after 快照，与修订快照核对；不再从历史显示文案前缀判断。当前事务未完成的 `{}` 事件不会被当成已完成快照。已有事件／备份无需迁移，真实人工补充仍保留。
- **草稿类型：** 工作台与“我的草稿”调用同一标签映射，覆盖人物、署名、任职、文章单位、来源、专题及原有资料种类；没有扩展草稿路由框架。
- **同名辨认：** 人物目录及署名、任职、合并、笔记对象候选共用简介／机构线索。支持多机构，含已登记的历史时期，排除已解除关系，显示“任职登记”，不推断唯一单位或现任。

新增公开字段 **`institution_hints: [{id, name}, ...]`**：机构 ID／姓名按当前未解除任职登记去重、排序生成，不含任职之外的私人研究内容。适用于 `/api/people` 的 `items`、`/api/people/<id>` 及共用详情服务的创建／更新／历史恢复响应，合并比较的 `keep`／`duplicate` 与人物导出投影也带该字段；历史修订和内部身份事件快照仍保留原结构。该列表是已登记机构的辨认线索，不能作为当前任职时间或身份自动确认依据。旧响应的既有字段含义保持。

新增两项公开 HTTP／真实临时 SQLite／完整备份边界的红→绿验证：

1. [恢复测试](../tests/test_person_recovery.py) 只在合成完整备份中改变历史显示文案：两次连续合并的系统修订换成另一种文案，真实人工补记又故意使用“人物合并”开头。修复前拆回丢失人工新介绍；修复后两次新目录恢复、倒序拆回正确恢复各自姓名并保留人工介绍，覆盖当前事件尚未写完的事务顺序。
2. [人物测试](../tests/test_people.py) 创建同名、无简介的两个人物，分别登记 Alpha／Beta 机构，并给前者增加 Gamma 历史任职、移除误登机构。修复前公开响应缺少机构线索；修复后三成员的列表与详情提供全部未解除机构，历史时期保留，误登机构排除。

本轮证据单独保存在 `%TEMP%\wiki-delivery-reviewfix-20261024-builder`，**仅原环境可查**。`identity-label-red.txt`／`identity-label-green.txt`、`institution-hints-red.txt`／`institution-hints-green.txt` 分别保存失败及通过；受影响的原 22 项身份场景全部通过，9 项恢复场景全部通过（含新增）。不改写上一轮原始证据。

实际 Edge 页面使用新建独占合成目录和 8857 隐藏服务。人物、机构、任职和一份作品通过明确标记的 HTTP 预置，页面再实际检查 1366×900 与 390×844 同名目录、署名人物搜索、390px 笔记研究对象选择器；两份无简介的同名人物可由 Beta 与 Alpha／Gamma 线索区分，多机构文字可换行，390px 页面与抽屉没有横向溢出。辅助文字实测 `rgb(82,97,116)`，对应 `--text-muted: #526174`。

另在实际页面建立人物、任职及署名三类本机草稿，经工作台和“全部草稿”两入口检查，均显示相同具体类型。没有把草稿提交到资料库。截图 `same-name-desktop.jpg`、`same-name-mobile.jpg`、`dashboard-draft-labels.jpg`、`my-draft-labels.jpg`、`subject-hints-mobile.jpg` 均实际查看；`browser-results.json` 保存界面文本、候选、颜色、尺寸和操作归属。页面日志捕获一条未复现的媒体 `NotSupportedError`，源码未发现音视频元素或播放调用，与 #11 已记的同类观察一致；不宣称控制台零错误，也不据此推断产品媒体功能故障。

页面补验后临时视口已 reset，自己的测试页已关闭，8857 按命令及独占数据路径核对后停止。最终冻结应用代码的 `python -B scripts/check.py` 返回 **156 项，155 通过、1 外部导入跳过，158.796 秒，退出码 0**，日志 `full-regression.txt`；7 个修改的 JavaScript 文件语法、差异空白及本轮文档 153 处相对链接／锚点检查通过，历史本机 JSON 缺失边界与前述一致。合入最新集成返回 Already up to date。精确修复提交由本轮交付摘要绑定，指挥方仍将独立复验并集成。

## 审查范围与报告归属

固定审查基线为 `b7b6c69f83f6efe85d4418ccac547d95ce5a0a5b`，首次完整审查目标为 `ee586e4`，业务规格固定为 `985b3d3` 的 v1.1。Standards 使用新审查子 Agent；Spec 因任务线程数量限制复用仅做过集成、未编写本轮实现的子 Agent。两者均为 `gpt-6.1-sol` / `max`，分别自行取证。以下完整保留两轴初审与复查报告，只把本地源码链接改为相应固定提交的公开链接，本机证据改为明确的本地路径。

## Standards

### 初审报告

审查版本：`ee586e4266644a94dd66879aecda3863abaf2dcb`。发现 **1 项规范偏离、2 项启发式问题，均为 P3，无阻塞项**。

1. **规范偏离：未使用有效主题变量。** [note-subjects.css:2](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/static/note-subjects.css#L2) 使用 `color:var(--muted)`，全仓库未定义此变量，辅助说明会继承普通文字颜色。违反 [施工说明:63](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/docs/施工说明.md#L63)“颜色由 `static/styles.css` 的语义变量统一维护”。改为已有 `--text-muted` 即可。

2. **possible Primitive Obsession：展示文案承担事件类型判断。** [person_identity.py:643](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/platform_app/person_identity.py#L643) 用 `.startswith(("人物合并", "人物拆回"))` 判断系统修订。内存探针仅将动作文案从“人物合并”换成“合并人物”，同一系统修改便被判成后续独立编辑，会影响拆回时保留哪些字段。当前文案下未复现错误；建议依据身份事件中的人物及版本识别系统修订，展示文案仅用于呈现。

3. **possible Repeated Switches：草稿类型标签已分叉。** [workflow.js:141](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/static/workflow.js#L141) 新增 `d.type==='person'?'人物档案':…`，但 [ux.js:60](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/static/ux.js#L60) 仍只有旧类型分支。同一人物、署名或任职草稿在工作台显示“内容”，在“我的草稿”显示具体类型。建议两处复用一个类型标签映射。

依据为源码阅读、静态变量检查及最小内存探针；探针结果：`%TEMP%/wiki-standards-review-ad2c66dfe1bf43c1ac42d9b22c548e5d/probe-results.json`（仅原环境可查）。未重跑全量回归，未逐值复算迁移夹具。源码未修改，结束时 HEAD 与工作树状态保持不变。

### 修复后定向复查

精确版本 `fced71a8411859be7a39ca0f347c49eaadc68c01`，工作树干净。原三项 **全部关闭，未关闭 0 项**。

1. **规范偏离已关闭。** [note-subjects.css:2](https://github.com/normaltank/DataBase/blob/fced71a8411859be7a39ca0f347c49eaadc68c01/static/note-subjects.css#L2) 改用既有 `--text-muted`；独立静态检查确认该样式文件没有未定义变量。

2. **possible Primitive Obsession 已关闭。** [person_identity.py:639](https://github.com/normaltank/DataBase/blob/fced71a8411859be7a39ca0f347c49eaadc68c01/platform_app/person_identity.py#L639) 按已完成身份事件中的人物、版本及完整快照识别系统修订，不再读取展示文案。独立运行新增恢复 HTTP 场景通过：系统文案改名、人工补记使用旧系统前缀后，两次恢复及逆序拆回仍保留人工介绍并正确恢复姓名。

3. **possible Repeated Switches 已关闭。** [workflow.js:5](https://github.com/normaltank/DataBase/blob/fced71a8411859be7a39ca0f347c49eaadc68c01/static/workflow.js#L5) 提供统一 `draftTypeLabel`，“我的草稿”与 [工作台](https://github.com/normaltank/DataBase/blob/fced71a8411859be7a39ca0f347c49eaadc68c01/static/ux.js#L60) 均调用它。独立执行两处真实渲染函数，8 种草稿类型的标签一致。

定向复查证据：`%TEMP%/wiki-standards-recheck-473d2962537e486b80d7eb80a1d651ec/results.json`（仅原环境可查）。本轮未重跑全套、未修改仓库或服务；同名辨认修复留给 Spec 轴复查。

## Spec

### 初审报告

已审 SHA：`ee586e4266644a94dd66879aecda3863abaf2dcb`。Spec 发现 **1 项 P2 部分实现**；未确认范围扩张或其他行为错误。

**[P2] 同名搜索缺少已知机构辨认线索。** 规格 4.2 要求：“同名结果显示各自介绍或机构线索供辨认。”[people.py:254](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/platform_app/people.py#L254) 未返回机构摘要，[people.js:18](https://github.com/normaltank/DataBase/blob/ee586e4266644a94dd66879aecda3863abaf2dcb/static/people.js#L18) 仅渲染姓名写法和简介。

独立复现：创建两个同名、无简介但分别有已核实 Alpha／Beta 任职的作者；HTTP 搜索返回两项，原 `peoplePage()` 渲染均显示同名及“介绍待补充”，两家机构均未出现。用户必须逐项进入详情反查，搜索结果无法按已有事实辨认。最小修正：为目录摘要提供并展示有依据的机构线索，避免将未知结束日期解释为现任。证据位于自建 Temp 的 `wiki-spec-review-20261024-yd1n0uvy/same-name-response.json`、`same-name-render.html`。

独立针对性检查通过：公共关系与正文权限隔离、隐藏关系过期拆回、后续纠正保留、私人笔记延后复核、固定引用、离线隐私过滤、当前备份恢复，以及合成 v5 备份恢复升级至 10 后的旧字段／历史／附件保全和重复启动。

限制：未重跑完整 154 项及完整浏览器验收；上述页面复现使用原 JS 渲染。仓库保持只读、HEAD 未变，未访问真实数据。

### 修复后定向复查

合并 SHA：`fcf34174c2e836017f035df2b0cf896bbcb2cd6e`。无冲突，源／目标 tree 均为 `b7aa5548b748cb377b887666a7daf63f6ccc1a04`，两侧干净。

**Spec 复查：原 P2 已解决，未发现新增规格问题或范围扩张。**

独立重跑原反例，并验证历史／未知时段、多机构去重、机构改名、解除、合并旧入口及拆回后的线索均正确；发布作品不会被误作任职。原 JS 渲染确认目录及任职、合并、署名、笔记和延后复核候选均显示机构线索，“任职登记”未推定现任。

公共正文权限、隐藏关系过期拆回、独立纠正、私人笔记延后复核、固定引用、离线隐私及备份恢复复查通过；另确认独立档案修改能跨连续合并／拆回保留。

证据：独立复查记录：`%TEMP%/wiki-spec-recheck-20261024-n0zl84a8/findings.md`（仅原环境可查）。限制：本次使用自建合成 HTTP 数据及原 JS 渲染，未重跑完整 156 项或完整浏览器验收。未编辑实现、推送或操作真实数据与服务。
