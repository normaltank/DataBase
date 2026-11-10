---
version: 1
slug: "static-maintenance-agent-js"
primary_target: "static/maintenance-agent.js"
related_targets: ["static/maintenance-agent.css", "static/maintenance-trace.js", "static/maintenance-trace.css", "static/maintenance-feedback.js", "frontend/flow.js", "frontend/diff.js"]
---

# 维护任务与反馈处理轨迹

模式：Operate / Read。当前体验范围为 #142 v1，继承固定规格2.0的协作与维护流程及 #141，保留 #137 的真实轨迹语义，沿用最新 PRODUCT 的 AI 正式写入与一句话反馈规则。

## Direction contract

THESIS：从有权近期任务进入真实步骤，再把该步材料与修改前后值同时放到固定阅读区。

OWN-WORLD：精准扩展 DESIGN.md 的蓝白灰、淡金焦点、14px与原生控件；code-led，无新世界或品牌。用户已授权既定交互和方向，子代理按明确brief直接实施，无额外访谈。

FIRST VIEWPORT：紧凑真实后台状态，紧接清单—步骤—详情；指定单篇任务和近期修改为次要可达区域。无指标卡、欢迎区、虚假百分比或固定必经阶段。

FORM：桌面实际节点与SVG连接指向详情，选中任务和步骤均保留稳定身份。详情联动真实证据ID、中文字段与历史原新值，当前对象入口单独标识。手机按清单、步骤、详情顺序，44px目标，键盘及200%保持完整动作。

React Flow 图节点取实际步骤与材料ID；连线仅表示已记录步骤顺序、实际取得的材料或显式引用，ELK同源Worker只排列记录。文字步骤与图选择共用固定阅读区，维护长图默认1倍阅读节点，显式全图可缩小总览，定位所选节点恢复阅读尺度；只给所选节点邻接边显示“顺序／材料”短词，完整关系由步骤与详情表达，不常驻自说明。长字符串实际前后值按需调用 jsdiff 与 diff2html 的预编译模板，HTML样内容保持文字；完整原新值仍可展开，短字段与结构关系沿用语义化对照。

关系前后值保留全部实质字段及原始引用；仅有历史编号时另列当前已鉴权读取的名称，清楚标注当前名称与历史名称缺口，不补造历史快照。

STATE：零步骤、pending、失败、无变更完成及未知费用忠实呈现。摘要局部更新，选中详情重新鉴权但不变不重建；证据展开、滚动、焦点、输入与选择跨刷新稳定，新增步不抢选。失权优先清理，断网保留最后有权内容并可重试。

摘要、详情与反馈历史条件读取先核权再计算actor/角色/表示ETag；仅当前账号、页面、URL且仍在显示的基体可复用304。no-store不变，无持久缓存。隐藏停止轮询并销毁图实例，回来重新鉴权后恢复视口；换任务／账号或失权丢弃旧读取与布局。模块或Worker失败时文字仍可操作，重试可恢复图。

MOTION：仅选步后的局部短状态提示，feature detect与reduced-motion直接切换，禁止全页动画。研究员复用只读轨迹，无管理费用配置，无反馈时间猜因果。

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

无发布用光栅资产。父任务统一机械检测、独立视觉与双轴审查；本路径执行公开HTTP及真实合成Chrome验证，截图保留原图，不替代研究能力验收。

检查入口为 `tests/test_maintenance_etag.py`、`tests/test_maintenance_summary.py`、`scripts/check_maintenance_trace_browser.py --evidence <隔离输出目录>` 及 `scripts/check_live_flow_failures_browser.py --evidence <新隔离输出目录>`。真实浏览器严格动态CSP与哨兵分别保留预期拒绝，非哨兵策略违规另行断言；各脚本随机端口、合成库与finally回收，不发生真实AI收费。

#142 默认以清单—步骤—业务差异阅读，流程图从“步骤与材料关系图”打开；折叠释放图实例并保留视口。全部／有改动／执行问题仅基于实际changes、错误及状态，不改执行或费用。窄屏显式“查看修改与依据”定位当前详情。

关系默认显示名称、归属、角色、人工状态及依据，编号、版本和原始引用进入完整记录；同名对象的稳定身份变更仍可辨识。署名单位的items未变、仅其依赖bylines投影变化时省略空对照，真实关系条目及业务顺序不省略。开发与最终审查边界见 work/现代研究工作台142开发验证.md。
