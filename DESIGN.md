---
name: 北外中东欧研究中心内部使用
description: 本期编译桌；协作编译优先，原件与具体版本成为工作主体
colors:
  primary: "#354ac5"
  primary-hover: "#273a9d"
  page-bg: "#f5f6fc"
  surface: "#ffffff"
  surface-muted: "#f0f2fa"
  surface-selected: "#e9edff"
  text: "#242936"
  text-muted: "#596174"
  border: "#dce0ed"
  control-border: "#aab3c9"
  pending-bg: "#fff0c5"
  pending-text: "#795200"
  verified-bg: "#eaf4ee"
  verified-text: "#24634f"
typography:
  page-title:
    fontFamily: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  object-title:
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.5
  period-title:
    fontSize: "26px"
    fontWeight: 650
    lineHeight: 1.4
  phone-page:
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.4
  phone-object:
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.5
  phone-material:
    fontSize: "19px"
    fontWeight: 650
    lineHeight: 1.5
  section:
    fontSize: "18px"
    fontWeight: 650
    lineHeight: 1.6
  compact-section:
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.6
  control-heading:
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  metadata:
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  reading:
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.9
rounded:
  control: "6px"
  group: "8px"
  object: "10px"
  archive: "12px"
spacing:
  small: "8px"
  group: "16px"
  section: "24px"
  desktop-page: "36px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.surface}"
  selected-object:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.object}"
---

# Design System: 北外中东欧研究中心内部使用

## Overview

“本期编译桌”采用现代大学出版工作的清晰层级：浅靛蓝工作底面、白色原件与工作对象、深石墨文字，以及用于动作、选择和焦点的群青色。研究员首先找到一期工作，再进入材料、原件与具体版本的交接。

2026-11-10 用户否决旧常驻左栏与并列清单／详情骨架。本系统替换其研究界面构图，保持 PRODUCT 中的对象、权限、原件与历史含义。来源与资料为协作提供支撑；页面不虚构完成率或研究指标。

## Colors

冷白内容面与浅靛蓝工作底面区分内容和框架。群青用于当前主导航、材料选择、主要动作与键盘焦点；柔黄和绿色仅表达真实待审／退回、通过／核对状态，并伴随文字。元数据使用石墨灰，正文保持深色。

## Typography

界面使用既有中文系统字体栈。正文15px、元数据14px；对象题名22px、页面题名28px。手机题名20–24px。阅读正文16px、行高1.9，目标宽度不超过72ch。Operate 界面沿用熟悉字体和控件，不引入展示字体。

## Layout

公共框架为横向“协作编译／中心成果／资料与档案”主导航，个人工具与维护入口进入具名菜单；研究界面没有常驻左栏。手机主导航独占第二行。

协作索引桌面两列真实工作对象、手机单列；未选中工作时不产生空详情。期次打开全宽编译桌，紧凑工作头提供返回、期次切换、阶段与角色。桌面材料索引位于工作面左侧，原件与本人真实操作并排；手机选择材料后先显示当前写入版本和原生审阅／提交表单，再显示阅读内容。所有写入表单只有一份，File、输入和具体版本身份继续由领域模块保留。

中心成果以刊物／期次对象呈现。来源与人物档案优先介绍和作品，结构字段和依据按需展开。辅助资料探索采用图形上方工作面与底部候选区；阅读居中，隐藏原探索DOM而不销毁它，返回保留画布、镜头、条件和草稿。

## Elevation & Depth

工作对象与正文以白色底面分组，无装饰性阴影。菜单使用浏览器 top layer 与轻阴影；对话框保留既有权限、冲突与恢复操作，位于公共框架之上。

## Shapes

按钮和输入使用6px圆角，内容对象10px，档案阅读面12px。细边界用于版本、字段和语义分组。手机主要控件保持至少44px触控高度。

## Components

公共菜单使用浏览器原生 Popover：同源、top layer、不裁切、Escape关闭与回焦点；菜单项是具名按钮。版本选择是原生 select，当前版与所看历史版分别说明。材料流程图、责任记录、提交说明和刷新工具按需展开。

唯一专门的短转场由锁定 Anime.js 4.5.0 在对象进入工作面时执行，220ms，已有可见终态。新切换、路由重建、隐藏及减少动效变化会撤销 scope；减少动效直接进入终态。既有图形引擎沿用受权限约束的快照与清理协议。

## Do's and Don'ts

- 使用真实题名、负责人、成员、阶段、版本和日期，不把状态推断为完成比例。
- 元数据、依据与低频操作逐步披露；当前原件和可执行操作保持清楚。
- 保留既有深链接、原件下载和恢复语义。新界面不新增在线Word编辑、段落批注或审批门槛。
- 新布局在静态轮廓与工作路径上区别于旧常驻左栏、双空面板；换色不构成重建。
