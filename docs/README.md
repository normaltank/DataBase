# 项目文档目录

整理日期：2026-10-26。本页按用途导航，不另建任务台账；待办与依赖以 [GitHub Issues](https://github.com/normaltank/DataBase/issues) 为准。文档职责与归档方法见 [写作约定](agents/documentation.md)。

## 当前入口

| 需要了解什么 | 阅读位置 |
| --- | --- |
| 产品目标、已确认规则与未决项 | [PRODUCT](../PRODUCT.md) |
| 业务词义 | [GLOSSARY](../GLOSSARY.md) |
| 启动、使用、备份与开发 | [README](../README.md) |
| Agent 接手任务 | [AGENTS](../AGENTS.md) |
| Matt 工作流与派工方式 | [工作流](agents/workflow.md) |
| Markdown 写作和归档 | [文档约定](agents/documentation.md) |
| GitHub 任务操作、分流及领域文件 | [任务跟踪](agents/issue-tracker.md) · [标签](agents/triage-labels.md) · [领域约定](agents/domain.md) |
| 当前实现及尚缺能力 | [施工说明](施工说明.md) |
| 用户决定及历史答复 | [需求讨论记录](需求讨论记录.md) |
| 长期研究方向与分期建议 | [长期愿景](长期研究愿景与演进路线.md) |

## 个人常用检索

[规格 1.0](specs/个人常用检索.md)定义个人保存查询、动态重查、管理与权限／恢复边界，授权与本轮选取依据见 [R018](需求讨论记录.md#r018继续内化-zotero-的基础资料管理)，实施由 [#34](https://github.com/normaltank/DataBase/issues/34)跟踪。本任务继续借鉴 Zotero 的基础资料工作方式；已有返回位置及候选完整性问题分别由 [#30](https://github.com/normaltank/DataBase/issues/30)、[#31](https://github.com/normaltank/DataBase/issues/31)跟踪；本轮交付入口为 [PR #35](https://github.com/normaltank/DataBase/pull/35)。

[整组验收](../work/常用检索与资料工作流验收.md)记录常用检索、连续工作位置及完整候选的实际复现、升级恢复、浏览器回归与 Standards／Spec 审查。它补齐一批资料管理能力；标准题录交换由 [#36](https://github.com/normaltank/DataBase/issues/36)继续细化。

## 基础数据库查找与来源选择

[本轮规格](specs/基础数据库查找与来源选择.md)覆盖来源范围查询、长来源选择、筛选上下文及发现网站入口；主动检查范围包括查找、阅读、录入、档案、专题与导出。授权出处见[R016](需求讨论记录.md#r016基础数据库建设与完整使用流程)，[验收记录](../work/基础数据库查找与来源选择验收.md)区分本轮改动、独立验证、审查修复及后续问题；执行和交付见[任务 #28](https://github.com/normaltank/DataBase/issues/28)／[PR #29](https://github.com/normaltank/DataBase/pull/29)。

## 链接与编号辅助录入

[规格 1.0](specs/链接与编号辅助录入.md)覆盖 DOI／文章网址的题录取得、预览核对、已有档案候选与保存，授权出处见[R017](需求讨论记录.md#r017链接与编号辅助录入开工)。[前期调研](../work/链接与编号辅助录入可行性.md)区分单篇录入与全站持续采集，保留当时未知项；实际支持范围以本轮验收为准。

[原站有限抽样](../work/辅助录入原站抽样.md)记录一个 DOI、对应期刊页与两篇智库页的实际题录、缺项和访问差异，不代表覆盖率。[本轮验收](../work/链接与编号辅助录入验收.md)分别记录开发、独立页面与网络验证、双轴审查及修复；实施与本机交付见[任务 #32](https://github.com/normaltank/DataBase/issues/32)／[PR #33](https://github.com/normaltank/DataBase/pull/33)。

## 机构与期刊研究档案

[本轮规格](specs/机构与期刊研究档案.md)将来源详情补为独立档案，保留快速预览并区分资料、目录译稿和研究笔记；用户确认见[需求讨论 R015](需求讨论记录.md#r015机构与期刊的研究档案)。[验收记录](../work/机构与期刊研究档案验收.md)区分开发、独立页面验证和双轴审查；当前交付由 [任务 #26](https://github.com/normaltank/DataBase/issues/26)／[PR #27](https://github.com/normaltank/DataBase/pull/27) 跟踪。

## 研究质量与导出复核

[质量与复核条件](../PRODUCT.md#研究质量与复核) 定义原始材料、推理边界和分层完成证据；[一手标准调研](../work/研究平台深度标准调研.md) 回答专家方法、原始素材、工具及独立验证。[本轮核查与验收](../work/研究复核深化验收.md) 区分真实库盘点、原站抽查、软件验证和未完成的真人研究复核。施工及交付由 [任务 #24](https://github.com/normaltank/DataBase/issues/24) 跟踪，授权出处见 [R014](需求讨论记录.md#r014深化项目与独立复核)。

## 全站布局与视觉整理

[施工规格 1.0](specs/全站布局与视觉整理.md) 定义公共导航、查找与阅读、来源和人物详情，以及工作台、专题、草稿和维护页面的统一整理。[讨论与取舍](../work/全站布局与视觉讨论.md) 保留本地观察及参考依据；授权顺序见 [R013](需求讨论记录.md#r013全面布局整理与本轮收尾的顺序)。[验收与审查记录](../work/全站布局与视觉验收.md) 区分开发、独立验证与已知限制；交付入口为 [PR #23](https://github.com/normaltank/DataBase/pull/23)，状态由 [父任务 #19](https://github.com/normaltank/DataBase/issues/19) 与子任务 #20—#22 维护。

## 基础资料管理第一批

[施工规格 1.0](specs/基础资料管理第一批.md) 定义资料库紧凑列表与连续阅读、批量整理和选中导出、本地附件全文检索。授权出处见 [R012](需求讨论记录.md#r012基础资料管理第一批开工)，发布与交付由 [父任务 #14](https://github.com/normaltank/DataBase/issues/14) 及子任务 #15—#17 维护；来源文章采集另列后续批次。

开发证据：[列表与连续阅读](../work/基础资料管理列表阅读开发验收.md) · [批量整理](../work/基础资料管理批量整理开发验收.md)。[整组验收与双轴审查](../work/基础资料管理第一批验收.md) 区分开发、指挥方独立验证和审查处置；交付入口为 [PR #18](https://github.com/normaltank/DataBase/pull/18)，合并与本机切换结果由父任务维护。

## 人物 Wiki 首版：交付与验收

[人物 Wiki 与研究对象关联](specs/作者档案与研究对象关联.md) v1.1 由 [父任务 #1](https://github.com/normaltank/DataBase/issues/1) 跟踪，七项流程的确认与覆盖依据见 [拆分发布记录](../work/人物Wiki任务拆分草案.md)。#6—#12 已集成并完成整组验收；统一 [验收记录](../work/人物Wiki首版开发验收.md) 区分开发、历史页面、指挥方精确版本独立验证与 Standards／Spec 审查。交付入口为 [PR #13](https://github.com/normaltank/DataBase/pull/13)，合并、本机切换与执行状态仍以 Issues 为准。

## 历史档案

以下按原路径保留，记录对应日期的工作与证据。“运行中”“待验收”“暂停”和旧对话派工均按当时语境阅读；当前工作流见上方入口。部分截图、测试产物和绝对路径证据仅原本地环境可查，公开克隆不包含这些材料。

### 资料修订与历史（2026-10-23，已合并并完成本地切换）

- [执行与审查记录](../work/资料修订与历史执行记录.md)：恢复测试修正、完整修改动作、受控失败验证及备份后的本地切换。任务和合并记录见 [Issue #2](https://github.com/normaltank/DataBase/issues/2)／[PR #3](https://github.com/normaltank/DataBase/pull/3)。
- 后续复盘已落实默认合成检查及双系统 CI，见 [Issue #4](https://github.com/normaltank/DataBase/issues/4)／[PR #5](https://github.com/normaltank/DataBase/pull/5)；统一入口见[自动验证](../README.md#自动验证)。

### 产品讨论与方案

- [早期业务讨论](../work/domain_discussion.md)：原始意图及后续确认前的提议。
- [五 Agent 产品脑暴与用户最新取舍](需求讨论记录.md#r011产品脑暴与基础数据库来源采集的建设顺序)：2026-10-24 的候选方向、分歧与基础数据库优先、随后采集的决定；当前路径见长期愿景。
- [文档体系调研](项目文档体系调研.md)：2026-10-21 的 Matt 等一手资料调研；当前文档规则已另行制定。
- [Pro 审查材料快照](项目现状与发展审查材料_2026-10-23.md)：转交时的状态，不是实时项目说明。
- [原方案补充修订计划](../work/task_plan.md) · [方案重写记录](../work/proposal_rewrite_plan.md)：Word 方案阶段已完成，旧计划项不是当前待办。
- [候选来源核查](../work/phase2_source_verification.md) · [ThinkTank 试点盘点](../work/thinktank_pilot_inventory.md)：有限范围的历史事实核查。

### 本地 MVP（2026-10-21 完成）

- [试用验收](试用验收记录.md)：基础版证据，不包含后续所有改进。
- [计划](../.planning/2026-10-21-local-platform-mvp/task_plan.md) · [发现](../.planning/2026-10-21-local-platform-mvp/findings.md) · [进度](../.planning/2026-10-21-local-platform-mvp/progress.md)。

### 来源目录（2026-10-21—22 完成）

- [交付规格](specs/来源目录改进.md) · [执行与验收](../work/来源目录改进执行记录.md)。
- [数据核查](../work/来源目录改进数据核查.md) · [机构关系样本](../work/来源机构关系样本核查.md)：保留各自输入、依据层级及未知范围，不表示所有来源事实均已核实。

### 前端主题与文案（2026-10-22 完成）

- [视觉参考](../work/北外主题视觉参考.md) · [执行与验收](../work/前端主题与文案改进执行记录.md)。

### 研究资料工作流程（2026-10-23 完成）

- [交付规格](specs/研究资料工作流程.md) · [最终执行记录](../work/研究资料工作流程执行记录.md) · [指挥方浏览器验收](../work/research-workflow-validation/commander-browser-checks.md)。
- [前端执行](../work/研究流程前端执行记录.md) · [当次接口契约](../work/研究流程接口契约.md)。
- [早期独立验收准备](../work/研究资料工作流程独立验收.md)：准备材料，不等同于其中全部场景已执行；最终结果以本组验收入口为准。
- [计划](../.planning/2026-10-22-research-workflow/task_plan.md) · [发现](../.planning/2026-10-22-research-workflow/findings.md) · [进度](../.planning/2026-10-22-research-workflow/progress.md) · [当时的暂停交接](../.planning/2026-10-22-research-workflow/handoff.md)。暂停已解除，本轮已完成。

### 使用体验与 UI（2026-10-23 完成）

- [交付规格](specs/使用体验与UI改进.md) · [最终独立验收](../work/使用体验独立验收.md)。
- [后端执行](../work/使用体验后端执行记录.md) · [前端执行](../work/使用体验前端执行记录.md) · [当次接口契约](../work/使用体验接口契约.md)。开发交接阶段的待验收或启动受阻状态保留为历史，后续交付结果见最终验收。
- [计划](../.planning/2026-10-23-research-ux-ui/task_plan.md) · [发现](../.planning/2026-10-23-research-ux-ui/findings.md) · [进度](../.planning/2026-10-23-research-ux-ui/progress.md)。

## 应用样例

[演示编译说明](../samples/演示编译说明.md) 是应用使用的操作样例，保留现有位置；它既不是正式研究成果，也不是待归档的施工计划。
