---
version: 1
slug: "static-record-explore-js"
primary_target: "static/record-explore.js"
related_targets: ["static/record-explore.css"]
---

# 单篇关联探索

局部扩展既有 Read / Operate 阅读页，面向正在核对出处并继续阅读的研究员。任务 #124；固定行为与边界见 docs/specs/资料发现与关联阅读.md 1.0 @13895ec。主目标 static/record-explore.js，配套 record-explore.css 与模板资源注册。

## Direction contract

THESIS：以当前单篇为关系中心，按需沿真实的一跳联系到达档案或原文／成果；阅读首屏保持紧凑。

OWN-WORLD：沿用 DESIGN.md 的灰白底、蓝色目的地、淡金未确认署名、标准控件和明确焦点，原生折叠承载探索。

STORY：读者在正文前发现入口，展开辨认身份、发布、刊载和文章单位，再到达具体对象；原始未确认署名作为文字保留。

FIRST VIEWPORT：默认1366×900，阅读工具栏后、摘要／正文前放单行“关联探索”。展开后中心题名、带方向的关系行和真实链接连续排列；390／320px按单列阅读，200%等效683 CSS像素保留同一路径。

FORM：既有世界内的直接局部扩展，采用中心篇目与有向关系清单的首选结构；seed: none (unavailable)。关系可同时用文字辨认，姓名不形成身份或任职推断。

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## 状态与退出条件

仅用当前账号可见的公开HTTP投影；展开、刷新和窗口返回时重验，加载、空态、失败重试、文章／路由／账号切换隔离均有真实浏览器检查。档案返回沿用work契约；关联资料返回恢复原查询、页码与阅读折叠位置。验证入口 scripts/check_record_explore_browser.py 只用新临时合成库和8895。图片均为浏览器合成截图，保存在当轮系统Temp，路径由交接证据提供。

本记录为实现方向与开发自测约定，不表示统一集成审查、独立finish review或部署已完成。DESIGN.md与既有sidecar保持原状态；本扩展没有新增栅格素材。统一审查由指挥Agent执行，真实未决业务项无新增。
