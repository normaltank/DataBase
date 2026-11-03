# Windows 便携演示构建与恢复

本说明沿用 [#78 规格 1.0](https://github.com/normaltank/DataBase/issues/78)，由 [#88 范围 1.0](https://github.com/normaltank/DataBase/issues/88)加入公开真实题录及历史机器节选。普通试用入口是包根目录“使用说明.html”；本文件用于复现构建、验收和恢复。产品规则仍以 [PRODUCT](../PRODUCT.md) 为准。不读取真实库或 ThinkTank。

## 构建

建设机需 Python 3.14、Git，以及首次下载官方构件所需的网络；接收方不用这些工具。先提交已审查源码，准备实际项目介绍 HTML（也兼容 PDF），再执行：

```powershell
python scripts/build_portable.py --intro-html 'C:\明确路径\项目介绍.html' --output 'C:\明确路径\dist'
python scripts/verify_portable.py 'C:\明确路径\dist\Zhihui-preview-提交前缀.zip'
python scripts/check_portable_preview.py --package 'C:\明确路径\dist\Zhihui-preview-提交前缀.zip'
```

`--prepare-only --allow-dirty` 只准备源码和运行库用于施工预验收，不生成可分享 ZIP。最终包要求实际项目介绍 HTML 或 PDF 存在，`--intro-html`与`--intro-pdf`二选一；`--allow-dirty` 会明确记录未发布源码，不用于最终交付。已存在的同名 ZIP 不覆盖。构建逐项复制版本控制白名单，不读取任何现有 data、备份、凭据或浏览器目录。构建缓存只保存 hash 锁定的公开官方构件。

仅通过 Git 接手前端或在 Linux/云端复用演示数据时，安装应用 requirements 后运行 `python -m portable.demo_seed --data-dir 明确的新目录`。它使用相同合成 PDF、头像、公开业务接口及受版本控制的公开白名单，不依赖 Windows 内嵌运行时；目标目录已存在即拒绝，避免重置任何旧数据。随后用 `create_app(该目录的绝对路径)` 启动所需的隔离开发服务，是否对外部署另按实际授权决定。

## 校园局域网临时试用

默认 `start.bat` 仍只监听本机。明确执行 `lan-configure.bat` 后用 `lan-start.bat` 开放当前电脑的LAN HTTP试用；`stop.bat` 停止同一实例。首次设置以隐藏输入替换仍用默认口令的管理员，停用其余仍用默认口令的演示成员；已有自设密码、成员、资料及历史保持，重启或模式切换不重置。用维护界面的成员管理创建独立试用账号，或为 researcher／colleague 设置各自新密码并重新启用；原负责人资格保留。停机后 `lan-configure.bat --port 8851` 可指定端口，0为自动，冲突时使用实际可用端口并显示。

LAN采用真实Waitress，绑定所有IPv4接口，Host只接受本机地址及启动时发现的实际IPv4。窗口显示当前可分享URL，网络变化后停止再启动。LAN无快捷登录，拒绝伪造转发头，写入保留Origin／CSRF和已有权限；随机令牌控制端点还要求回环来源。停止不按端口或PID杀进程，多个解压副本各自管理。

同校园网不保证设备互访：校园Wi-Fi客户端隔离、访客网或不同网段规则可能阻断；主机须联网且保持开机不休眠。防火墙只由使用者按程序 `runtime\python.exe`、实际TCP端口和试用网段／具体客户端IP建立受限入站规则，配置文件与校园实际网络一致，结束后禁用／删除。完整中文逐步操作在包根目录[使用说明](../portable/quick-start.html)，软件不修改防火墙、路由器或开放公网。临时LAN HTTP只用于可信网络；正式TLS部署见[服务器发行说明](https://github.com/normaltank/DataBase/blob/main/docs/server-deployment.md)。

实际ZIP检查：`python scripts/check_lan_release.py --package <ZIP>`，验证本机非回环IPv4登录、两成员／私人资料／附件、重启、端口冲突、自身停止和备份新目录恢复；不冒称已在校园两台设备上验证。它和原便携验收都不探测8848。

## 随包内容与历史译文

原三账号、合成主题／期刊协作及其原件继续用于交接体验。另从[固定公开fixture](../portable/samples/cee17-preview.json)播种38核心来源、27辅助机构、56外部资料，均待核对，不关联虚构中心成果。登录后从“我的→资料夹→历史17国公开资料样本”找到全部56篇，或在“资料”搜索“平台工作者”。题录、来源、日期精度及已知冲突保留；不将来源所在地推成文章研究对象。

56个机器题名来自既有DeepSeek批次，23篇保存原摘要不超过20词及机译摘要不超过120字的独立节选，33篇无原摘要只展示译题。不包含完整原摘要、完整译文、全文、真实账号或内部附件。原译节选独立截取，未必逐句或逐段对齐，不能作为完整摘要或专业人工校订结果。历史取得路径及限制见[#86记录](../work/中东欧17国来源与采集翻译演示核查.md)；本包不证明38站持续自动接通。

来源、资料和资料夹通过认证API创建。既有API不接收历史结果，因此[专用新库播种器](../portable/public_batch.py)只在刚完成合成初始化的演示库写入派生机器展示版本与`raw_json`来历，不执行服务商调用。历史完整输入hash、原任务／资料ID及原版本独立保留；本包输入hash按随包题名与节选重算，不能拿节选重新验证未随包全文。该展示版本不写人工中文、不允许人工采用为完整译文；本地attempts/calls/AI费用与自动任务均为0，AI保持暂停。原题名／摘要修改后按普通输入hash判断失效，非输入字段修订不丢掉当前可用译文；正常非导入翻译行为保持。可读内容导出及完整备份恢复保留这两类hash与导入身份。

[构建器](../scripts/build_portable.py)使用 [固定构件锁](../portable/runtime-lock.json)：官方 CPython 3.14.10 embeddable x64、含 Waitress 的五项应用依赖及五项传递依赖，保留整份 wheel 中的 DLL、dist-info 与许可。Python 摘要依据 python.org 的 sigstore 摘要，wheel 摘要依据对应固定版本 PyPI JSON；构建不执行 pip。锁同时记录解压后文件清单，核验器逐字节核查官方构件，只有 `python314._pth` 被显式替换。摘要证明所据构件的一致性，不替代安全更新或研究真实性判断。本轮与正式源码发行共用受控应用依赖版本；后续安全修订须重新锁定、构建及验证。

`._pth` 仅包含包内标准库、包内 site-packages 与应用根目录，不启用 site；附件子进程沿用内嵌 sys.executable。启动器在导入应用前重建环境，只保留命名的 Windows 必需变量，另设置包内 TEMP/TMP 与 Windows System32 PATH。不会继承 Python 路径、研究库路径、AI 凭据、代理或证书定制。`diagnose` CLI 只报告环境变量名及包内模块来源，不打印凭据值。

## 生命周期和恢复

专用入口调用 `create_app(本包data绝对路径, embedded_worker=False)`，不导入开发 app.py，不起采集、中文处理或 AI worker。空库在包内临时目录生成全部演示后才原子移入 data；已有数据库绝不重置。协作样例 PDF、TXT 和头像均为明确合成，其外链使用 example.invalid；真实题录保留正式来源网址。seed 清单保存在新库的 demo-seed.json，分开记录合成对象、原件摘要和真实公开批次映射。

实例生命周期按包目录加文件锁，控制端点需要随机令牌和本包路径身份；停止先完成自身 Waitress 请求调度再关闭自身监听与连接，不按 PID 或端口杀进程。操作序列锁和服务生命周期锁由 Windows 在进程退出后释放。过期控制状态不会成为杀进程依据。端口由服务器实际原子绑定，优先复用上次成功端口，冲突时使用可用动态端口；始终避开8848。各包目录拥有独立且稳定的会话 Cookie 名；浏览器草稿仍依赖实际端口。

完整备份在管理员界面下载。恢复到新解压且尚未启动的副本，在命令提示符运行：

```bat
runtime\python.exe -I -B -m platform_app.maintenance --restore "C:\备份路径\演示备份.zip" --target "C:\新解压路径\data"
```

目标 data 必须是尚不存在的新目录。成功后双击新副本 start.bat；恢复的数据库存在，因此不会重新播种。先停止原副本再移动或复制其 data；正式资料迁移须另按实际授权处理，便携演示不自动迁移真实库。直接转发构建器生成的原始 ZIP，避免把试用后的账号、附件、日志、会话和备份带给别人。

## 验证边界

[发行验收脚本](../scripts/check_portable_preview.py)在全新中文空格目录、受限 PATH 和显式假外部配置哨兵下，通过真实 BAT 启停内嵌解释器与 HTTP。它核查三类职责、来源贡献与核对、继续主题候选／会议／返修／定稿／汇总和期刊版本采用、下载、PDF/DOCX 索引、头像、导出、完整备份恢复、同一 CookieJar 中两份实例的会话隔离及重启保留，并检查采集及 AI 未运行的状态。真实浏览器检查另用 `--browser`，在同一浏览器上下文登录两份实例并核查退出互不影响；需要建设机的 Playwright，它不随包作为运行依赖。核验器拒绝越界、重复、原始 ZIP 名被截断或规范化、符号链接及白名单外文件，并比对完整 manifest 和固定合成 PDF 摘要。

本轮实际执行结果、同步 SHA、独立审查和最终 ZIP 摘要由 Issue 的本次交接记录维护，施工预验收不等于最终分享版。受限 PATH 和包内模块来源能验证本宿主上不依赖开发 Python，不能冒充干净虚拟机或所有 Windows 10/11 系统覆盖。软件测试不证明研究观点、实际资料覆盖或真人跨人接续质量。
