---
version: 1
slug: "static-material-compare-js"
primary_target: "static/material-compare.js"
related_targets: ["static/material-compare.css"]
---

# 已选资料比较

模式：Operate / Read。目标与业务范围遵循资料发现与关联阅读 1.0 / #125；这是既有资料列表的局部扩展。

## Direction contract

THESIS：把显式选择的2–3篇资料放在同一阅读尺度，帮助研究员逐字段人工比较。

OWN-WORLD：继承 DESIGN.md 的蓝白灰与淡金、紧凑按钮、下划线目的地、细分隔线及金色键盘焦点；系统规则保持原文件。

STORY：#142 v1 在阅读工具栏直接加入／移出比较，沿用既有2–3篇上限，也保留“整理与导出”跨页选取；比较后返回原阅读或清单，分别阅读原始和中文内容；机器译题、机器译文与人工中文贴近内容表达。

FIRST VIEWPORT：标题与关闭按钮在顶端；首组显示各篇原始题名、单篇阅读和原文入口。桌面2或3列严格对齐；手机按同一字段依次列出每篇，内容在页面内自然换行。

FORM：既有表格式对照的局部扩展；明确任务直接施工，concept-seed不适用。加载、失败、撤权和缺项就地呈现；重试与移除有明确动作。关闭恢复原阅读与位置，或原选择、页码和列表焦点；阅读可回比较，账号与路由更新丢弃晚响应。

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

本轮保持 DESIGN.md 的既有系统；不新增发布用光栅资产。独立视觉复核、双轴审查与最终机械检测由父集成任务统一进行。浏览器验证见 scripts/check_material_compare_browser.py。

#142 复用原选择集合、鉴权及比较读取，不新增分析结论或业务状态。桌面比较区域独立滚动，长字段保持可达。开发验证见 work/现代研究工作台142开发验证.md，最终统一审查仍由父任务负责。
