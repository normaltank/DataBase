# 项目文档目录

整理日期：2026-10-23。本页按用途导航，不另建任务台账；待办与依赖以 [GitHub Issues](https://github.com/normaltank/DataBase/issues) 为准。文档职责与归档方法见 [写作约定](agents/documentation.md)。

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

## 已确认、尚待施工的规格

截至本页整理时，[人物 Wiki 与研究对象关联](specs/作者档案与研究对象关联.md) 已形成规格并发布为 [父任务 #1](https://github.com/normaltank/DataBase/issues/1)，尚未拆分子任务或实施应用。下一建设阶段由 `to-tickets` 形成完整流程任务，经确认后进入 `implement-spec`。

## 历史档案

以下按原路径保留，记录对应日期的工作与证据。“运行中”“待验收”“暂停”和旧对话派工均按当时语境阅读；当前工作流见上方入口。部分截图、测试产物和绝对路径证据仅原本地环境可查，公开克隆不包含这些材料。

### 资料修订与历史（2026-10-23，已合并并完成本地切换）

- [执行与审查记录](../work/资料修订与历史执行记录.md)：恢复测试修正、完整修改动作、受控失败验证及备份后的本地切换。任务和合并记录见 [Issue #2](https://github.com/normaltank/DataBase/issues/2)／[PR #3](https://github.com/normaltank/DataBase/pull/3)。

### 产品讨论与方案

- [早期业务讨论](../work/domain_discussion.md)：原始意图及后续确认前的提议。
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
