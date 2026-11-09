---
primaryTarget: static/topic-handoffs.js
relatedTargets:
  - static/workbench.css
  - static/maintenance-trace.css
  - frontend/flow.js
mode: Operate
---

# 材料沿革

范围为 #141、固定规格2.0的协作流程；保留 #136 已实现的当前／历史阅读。研究员在同一份材料中核对真实版本、原件与该版负责人意见，继续当前提交或审阅。沿用并列工作台，不改变权限、阶段、旧流程身份及原件。

## Direction contract

THESIS: 以版本为锚的双责任轨道，让提交与审阅的实际对应直接可点；每份材料保持独立阅读和写入目标。

OWN-WORLD: 继承现行蓝白灰工作台、金色焦点与原生控件。选中节点、细连线和阅读身份共同表达选择，完整中文状态不依赖颜色。

STORY: 先见当前版待审，再点历史版本或真实审阅，原件与意见同步替换；回当前版后接续现有表单，输入和文件不被阅读切换重建。

FIRST VIEWPORT: 左侧既有工作清单；右侧材料题名和当前状态下直接展示“成员提交／负责人审阅”两列及逐版实际连线，单一阅读区紧随其后，当前动作在其下。手机改为文字顺序入口、版本选择和回当前版；邻近版本选择的显式定位按钮随所选版本更新，滚动时保持可达，只有点击才定位原件与意见，不抢选择焦点。

FORM: 本轮作为既有 Operate 界面扩展，沿用现有项目与原型，未执行新的 visual-world / seed 流程。签名交互是节点—责任线—原件与意见同时选中；可用 WAAPI 时仅阅读区短反馈，减少动态或不支持时直接切换。

图形使用局部 React Flow 根及同源 ELK classic Worker。版本登记顺序与此版真实审阅分别标明；布局不推断审阅导致后续提交。材料使用150×80紧凑节点和短角色／状态标签，短沿革在桌面默认近1倍完整呈现，提供放大、缩小、定位所选节点和显式全图。图选择与文字选择共用版本阅读；上传及审阅表单始终在 React 根以外。手机保留图入口及原生版本选择、44px定位按钮；模块或布局失败保留文字阅读并可重试。刷新保留视口，失权立即移除图与历史，恢复后重新核权读取。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

独立审查和统一detector由父集成任务执行。本组件保留初版与两轮以内实际渲染截图；无新raster。既有PRODUCT/设计sidecar陈旧提示不在本轮修复。

公开HTTP及实际浏览器检查入口为 `tests/test_topic_handoffs.py` 与 `scripts/check_collaboration_lineage_browser.py --evidence <隔离输出目录>`；后者核对真实图节点、Worker、逐版原件／审阅附件字节、草稿、闭期、失权恢复与原生200%。`--baseline-flow` 仅用于固定旧版界面的失败对照。
