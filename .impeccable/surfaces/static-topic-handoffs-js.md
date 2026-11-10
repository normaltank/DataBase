---
primaryTarget: static/topic-handoffs.js
relatedTargets:
  - static/workbench.css
  - static/maintenance-trace.css
  - frontend/flow.js
mode: Operate
---

# 材料沿革

当前按 #146 本期编译桌维护，保留 #136／#141 的真实版本、原件与草稿身份。当前构图及世界见 [编译桌](collaboration-desk.md) 与 [DESIGN](../../DESIGN.md)。

## Current direction contract

THESIS: 所看版本、实际写入目标和原件各自清楚；材料动作区直接处理当前有权审阅。

OWN-WORLD: 冷白、浅靛蓝、群青，沿用 DESIGN；Operate / Read。

STORY: 从材料打开原件，按需看逐版提交与对应审阅；查看历史不改投草稿，意见附件保留同一原生 form/File。

FIRST VIEWPORT: 紧凑材料／版本／写入上下文接原件开头。主历史为合并交接记录；完整图另外展开，窄屏显示完整链而非孤立节点。

FORM: React Flow 的显式 material-lineage 模式按真实 version_ref 固定同版分组坐标；桌面版列／角色行，手机逐版堆叠，节点文字不因显示全图缩小。材料端不调用无作用ELK；维护默认分支继续使用真实同源ELK Worker及原动作。材料图无审批按钮。

FINISH: 本轮开发证据交由原独立审查者复核；未获得独立结论前不作放行或部署声明。

## Historical #142 direction

以下保留当次方案与验证范围；其中节点审批和蓝白灰／金色世界已被上方 #146 取代。



THESIS: 当前有权待审节点直接完成决定；历史、原件与草稿均保留具体版本身份。

OWN-WORLD: 蓝白灰、14px无衬线、金色焦点与原生控件。中文状态不只靠颜色。

STORY: 查看当前版，直接通过或退回；意见/附件接续同一原生form。选择历史只换阅读，旧版不获得新审批。保存一份材料不重建其他材料文件。

FIRST VIEWPORT: 桌面材料题名与短图相邻，当前待审节点有通过、退回和意见/附件；完整文字责任记录按需展开。手机先显示当前原生操作，流程图有明确折叠入口；回当前版显式打开并定位最新节点，原件与意见也可独立定位。关闭图释放实例。

FORM: 局部React Flow根与同源ELK classic Worker只负责呈现及排列。adapter传入动作并处理权限与HTTP，原生textarea/file始终在React根外；按钮键盘事件不被节点选择吞掉。短图按真实包围框收紧，版本顺序与真实审阅仍各自连接；放大、缩小、定位、全图保留。模块或布局失败折叠不可用画布，展开文字责任记录并连续提供同一原生form；显式重试恢复图形，不重建textarea/file，重试只在失败时出现。React Flow署名保留。

STATE: 单次在途、防双击；未知结果只能用原决定、原request_id和原body重试。409、401及403保留本机草稿，移除失效阅读或动作。草稿的内存键含账号、期次与具体版本；新版本另建空白表单，不把旧稿改投。离页返回重新核权，重新载入浏览器不承诺保留File。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

公开HTTP与浏览器验证入口：tests/test_topic_handoffs.py、scripts/check_handoffs_http.py、scripts/check_collaboration_lineage_browser.py、scripts/check_modern_workbench_browser.py。当次证据见 work/现代研究工作台142开发验证.md；独立merger、双轴、统一detector及视觉复核由父任务执行，开发自测不替代放行。既有PRODUCT/设计sidecar陈旧提示未在本轮修复。
