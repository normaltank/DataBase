---
version: 1
slug: "static-record-explore-js"
primary_target: "static/record-explore.js"
related_targets: ["static/record-explore.css", "frontend/network.js"]
---

# 单篇关联探索

局部扩展既有 Read / Operate 阅读页，面向正在核对出处并继续阅读的研究员。当前体验任务 #142 v1，继承 #140／父任务 #134 的关系投影；行为与边界见 docs/specs/直观协作与维护工作台.md 2.0 @788adf5。沿用 #124 单篇关联入口和返回契约，主目标 static/record-explore.js，配套 record-explore.css 与 frontend/network.js 同源模块。

## Direction contract

THESIS：以当前单篇为关系中心，按需沿真实的一跳联系到达档案或原文／成果；阅读首屏保持紧凑。

OWN-WORLD：沿用 DESIGN.md 的灰白底、蓝色目的地、淡金未确认署名、标准控件和明确焦点，原生折叠承载探索。

STORY：读者在正文前发现入口，展开辨认身份、发布、刊载和文章单位，再到达具体对象；原始未确认署名作为文字保留。

FIRST VIEWPORT：阅读工具栏保留单行“关联探索”，打开非模态侧面板，所选对象卡在图旁上方直接给出关系和档案入口；完整文字关系列表按需展开，正文不被长图推移。390／320px侧面板占满可用宽度，可明确关闭；当前条件、日期精度和机器身份继续保留。“查看所选关系”定位当前卡，详细标识与依据按需打开。

FORM：既有世界内的直接局部扩展，Cytoscape 平面与 Three 空间共用同一有权一跳快照；seed: none (既定局部扩展)。节点按对象类型及稳定编号去重，多种角色分别保留；AI正式关联与人工核对分列。原始未归属署名不变成图节点，无来源至期刊的推断主办线。

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## 状态与退出条件

仅用当前账号可见的公开HTTP投影；展开、刷新和窗口返回时重验。普通读取失败保留最后有权内容，明确失权清空，未变表示保留阅读与视角；迟到读取、模块、文章／路由／账号代次隔离。档案返回沿用work契约；关联资料返回恢复原查询、页码与阅读折叠位置。

验证入口 scripts/check_network_browser.py 使用随机独立端口、新临时合成库、真实HTTP及Chrome；AI正式关系由既有有界worker与确定性合成供应商生成，零真实收费。严格策略通过正常外部脚本加载动态meta，并以被拒的内联样式／eval哨兵证明生效。包含真实渲染节点拾取及旋转后拾取、档案往返、手机、原生200%、减少动态、模块失败与无WebGL回退；截图及结果在ignored tests/artifacts/network-<port>/，具体执行与SHA由交接证据提供。

空间默认不自动旋转，仅交互／尺寸变化按需绘制；隐藏时释放当前图实例并保留视角标识，返回时重建。切换、离页销毁Cytoscape、Three资源、监听与观察器。窄屏标签固定可读宽度；初始与显式复位以节点和真实 DOM 标签包围框共同适配画布，空间视图同时保留多行标签间距。用户操作后的相机不因选择或刷新重置。

本记录为实现方向与开发自测约定，不表示统一集成审查、独立finish review或部署已完成。DESIGN.md与既有sidecar保持原状态；本扩展没有新增栅格素材。统一审查由指挥Agent执行，真实未决业务项无新增。

#142 在现有浏览历史中仅记录稳定节点、模式与相机位置；返回档案重新取得当前有权投影后恢复。关闭、隐藏或离页释放图形，普通折叠保留允许恢复的选择和视角。当前开发证据见 work/现代研究工作台142开发验证.md。

第二轮R1仅将空间视图中心篇目全文标注置于节点上方，给两节点和连接留出可见区域；四宽同时核查完整标签和图形像素，用户非默认相机继续保留。作者验证及独立复核边界见既有开发验证记录。
