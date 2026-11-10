---
name: 北外中东欧研究中心内部使用
description: 紧凑清单与就地交接，保留资料、原件和具体版本
colors:
  primary: "#174e9c"
  primary-hover: "#103d7d"
  shell-navy: "#17395e"
  shell-muted: "#d4e2f2"
  accent-soft: "#fff4d3"
  surface: "#ffffff"
  surface-muted: "#f0f4f9"
  surface-selected: "#eaf1fb"
  text: "#243347"
  text-muted: "#58697b"
  border: "#d6e0eb"
  control-border: "#aebdce"
  pending-bg: "#fff0c5"
  pending-text: "#795200"
  verified-bg: "#eaf4ee"
  verified-text: "#24634f"
  focus: "#b47d00"
typography:
  page-title:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "23px"
    fontWeight: 600
    lineHeight: 1.4
  section-title:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "19px"
    fontWeight: 650
    lineHeight: 1.5
  list-title:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  record-heading:
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.6
  detail-heading:
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.6
  phone-title:
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.4
  phone-detail:
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.5
  login-title:
    fontSize: "25px"
    fontWeight: 600
    lineHeight: 1.7
  phone-login-title:
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.7
  reading:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.9
rounded:
  control: "4px"
  badge: "3px"
  login-frame: "6px"
  retained-editor-group: "8px"
spacing:
  compact: "8px"
  group: "12px"
  row: "16px"
  panel: "20px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
  work-selected:
    backgroundColor: "{colors.surface-selected}"
    textColor: "{colors.text}"
    padding: "12px 16px"
  pending-status:
    backgroundColor: "{colors.pending-bg}"
    textColor: "{colors.pending-text}"
    rounded: "{rounded.badge}"
    padding: "1px 7px"
---

# Design System: 北外中东欧研究中心内部使用

## Overview

采用“并列工作台”：研究员在稳定功能导航下查找工作或资料，并就地查看所选对象的具体内容。设计来源是研究档案的稳定身份、出版物的注释层级与审稿案卷的版本责任；表格、按钮、输入和导航使用熟悉的操作型产品形式。

中心编译产出优先。主题和期刊分别组织；清单、当前工作、稿件版本和审稿动作之间有明确对应。资料检索、来源/人物档案、资料夹和个人功能延续相同的信息层级。密度来自缩减层级、按需展开和完整利用屏幕，正文及元数据至少14px。

本文件记录 `static/workbench.css`、`static/workbench.js` 与实际浏览器渲染的现行规则。业务写入、权限及版本仍由领域模块和后端负责。

## Colors

深蓝顶栏标识研究界面；白色清单与冷色详情底面分出用途。主色用于当前导航、链接和主要动作。柔黄只表达待处理或提醒，绿色只表达有依据的完成；每个状态同时有文字。来源核对、稿件定稿、机器处理分别使用自己的业务标签。

国别数量图使用蓝色色阶 `#cadcf3`、`#6d99d2`、`#174e9c` 表示当前有权范围内的低、中、高数量，配合实际数量图例；色阶不表达研究重要性。

## Typography

界面采用一套无衬线字体。页标题、章节和条目形成紧密的23/19/16/15/14px层级；窄屏页标题21px。长题名和文件名允许换行或就地展开，数字使用等宽数字对齐。正文阅读沿用已有17/19/21px偏好及衬线开关；界面标签不跟随阅读字号放大或缩小。

## Layout

桌面顶栏54px、侧导航180px。工作区清单与交接栏约按45:55分配；交接栏至少540px，1600px以上至少600px，文件与审稿动作有足够空间。清单及详情独立滚动，标题、筛选、所选身份和操作按当前范围组织。首次进入选择首项供桌面预览；手机在明确选择后进入详情。

1200px以下工作清单和交接详情成为连续的完整页面，提供与父页面同名的“返回编译协作／中心成果／协作维护查阅”；1000px以下侧栏改为可关闭的导航层；700px以下顶栏56px、正文两侧16px、触控按钮至少44px。资料阅读在1200px以下使用独立阅读区域。200%浏览器缩放使用相同的响应式结构，保持文字原本尺寸。

来源、人物、资料夹和个人空间采用紧凑行；需要长期阅读的档案保留完整章节。维护界面与研究界面使用相同控件语言，导航根据真实角色分流。维护总览每项入口附实际用途；便携模式若提供脱敏运行状态，中文处理与费用页分别显示本机配置、启用和后台状态，数据库暂停、月额度及费用仍以原实际数据为准。

## Elevation & Depth

清单、记录行和详情通过1px边界与底面区分，不使用装饰阴影。只有导航弹层、下拉动作菜单和受保护的编辑/确认对话框使用柔和阴影。默认没有页面入场动画；短暂悬停反馈不影响任务时序。

## Shapes

标准控件4px圆角，状态标签3px，登录整体边框6px。既有正文/依据编辑区保留8px的分组容器；新清单不使用这些容器。列表没有卡片外框；真实分组以留白、标题和分隔线表达。焦点使用3px金色描边，对象题名和文字目的地保留下划线，悬停与键盘反馈一致。固定标题使用正文色；导航分组使用加粗中性色与分隔线，组内目的地缩进。原生折叠保留三角标记及整行点击区，桌面至少36px、手机44px；主要执行动作使用按钮。受保护对话框覆盖固定顶栏，标题和关闭入口始终可见。

## Components

- 工作行以题名、业务类型、负责人/原刊范围与适用日期表达身份；清单摘要只用列表实际提供的成果数或参与身份，选择及详情加载不更换统计口径；待审数量在已加载的本期详情中表达，未读取的工作不假定为零。点题名在右栏选择，桌面清单保留在视野内。
- 主题详情先显示实际阶段、本人身份与下一动作。选题期直接显示本人报告及单一提交区、会议决定、成员报告；编译期才提供“稿件与审稿 / 选题与决定 / 成果”浏览页签，页签与业务阶段分开。稿件表选择具体分工，下面提供原件、提交说明、该版意见和适用动作；负责人权限不由系统管理员身份代替。完整档案仍可打开。
- 新“期刊成果”从中心成果与主导航直接进入，刊名、年份、成果期次与首批文件一次保存；并列添加与明确更新某份文件使用不同动作，默认显示各份当前版。沿用紧凑清单、标准表单和按需打开的历史，不引入审稿或采用步骤。
- 旧期刊工作右栏继续保存其原有材料、版本和实际采用成品，不套用主题选题会；旧工作的上传成品与明确采用仍是两个动作，入口在历史区保留。
- 资料列表默认中文题名与简短来源/日期，摘要在阅读区。附件搜索命中默认收起，保留真实命中位置入口。机器译文、原摘要、机器概述、中文待处理和无正文分别表达。
- 筛选在所作用的清单上方，来源的关键词与字段共用“查找来源”提交。研究对象国与来源国别分开。新增批次显示未确认总数及实际收录范围；“确认当前结果已浏览”只确认当前筛选，排除的新增保留，打开一篇本身不确认。范围相同时省去重复切换。批量整理和导出按需展开。手机阅读返回恢复条件、位置与焦点。
- 查找后阅读返回保留已应用条件、未应用的工作查找输入、筛选展开、清单位置与焦点。
- 检索、来源与人物作品共用正文优先的阅读顺序：题名、短元数据及紧凑操作之后显示正文或摘要，署名、关系、处理来历和编辑授权按需打开。档案先呈现介绍、任职和作品；补全工作区显式打开，已处理建议进入历史。
- 状态贴近对应文件或内容，用“机器译题”“机器译文”“暂无摘要”“待核对 N 项”等短语。重复空态辩解、包处理自证和常驻免责小字直接删除；当次失败与恢复入口就地显示，保留原件、版本与实际授权。
- 保存失败/冲突保留文件和输入，提供读取最新状态后继续的动作。异步结果以账号与读取代次核对；失败显示可理解恢复入口。

## Do's and Don'ts

- 保留稳定身份、原文依据、提交原件、具体版本和权限边界；来源及人物使用适用字段。
- 用记录行、清晰动作和按需展开取得密度；不要加欢迎大区、指标卡和空模块。
- 未知保持未知；没有统一整期归档状态就不推断“整期完成”。
- 不在平台重新填写Word报告模板，不增加在线Word/PDF写作器，不用颜色替代状态文字。
- 新页面沿用同一导航、控件、最小字号和响应式规则。参考原则来自 [Zotero](https://www.zotero.org/support/quick_start_guide)、[Carbon](https://carbondesignsystem.com/components/data-table/usage/)、[GOV.UK](https://design-system.service.gov.uk/components/task-list/)、[Fluent 2](https://fluent2.microsoft.design/layout)、[PatternFly](https://www.patternfly.org/components/table/design-guidelines/)。

平台名称统一为“北外中东欧研究中心内部使用”。手机顶栏显示完整名称，在“研究中心”后允许换行，保留至少44px的导航与退出操作目标。页面删除重复副标题和口号；权限、版本、核对、机器处理及操作后果继续在相关位置显示。

维护任务与反馈步骤联读沿用此系统：紧凑真实运行状态下直接排列近期任务、实际步骤与固定阅读区，选中步骤用蓝色节点和SVG连接指向内容。白底与细分隔线保持层级，原值用冷灰底、新值用浅绿底并各有文字；长值和材料正文按需展开。节点、证据和前后值来自真实稳定身份，无固定必经流程或虚假进度。组件自身不足600px时转为顺序布局，使研究员的窄阅读栏和手机均可操作；仅在用户选步时允许180ms局部背景反馈，减少动态或能力缺失时直接切换。

关系前后值保留状态、依据、具体署名引用、角色、适用时间及人工核对等实质字段，原始身份与引用可以展开读取；仅版本和更新时间等簿记变化不产生差异条目。明确失去维护资格时清空反馈历史及所选详情，普通读取失败保留内容与输入。

关系字段只有历史编号时，复用本账号已读取的有权档案名称，明确标为“当前名称”，同时保留编号及“历史名称未记录”；未取得名称则保留缺口。窄屏材料沿革在版本选择旁提供随选定版本更新的44px定位按钮，滚动时留在可见范围内；只有显式点击才定位原件与意见阅读区，版本选择及历史阅读不改变输入和写入目标。

材料沿革在每份主题材料内直接显示“成员提交／负责人审阅”双责任列，真实审阅线连接对应版本；选中节点和线沿用蓝色选择，阅读区使用既有浅灰底面，金色仍只用于键盘焦点。具体版本、责任人、日期和状态始终有文字。窄屏与200%布局改为有文字的顺序节点和原生版本选择，目标至少44px；原件、意见和附件共用一个阅读区，当前写入表单位于独立动作区，阅读切换不重建表单。
