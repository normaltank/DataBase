# 正式服务器部署与维护

适用 [#96](https://github.com/normaltank/DataBase/issues/96) 的原生源码发行。便携校园网 HTTP 试用另见[便携说明](portable-preview.md)。本说明提供运维操作路径；不表示目标服务器、证书、系统服务重启、校园设备互访、并发或 SLA 已经验收。

## 1. 校验与安装

取得同一发布提交的 `Zhihui-server-提交前缀.zip`、`.zip.sha256` 与独立公布的摘要。Windows 用 `Get-FileHash -Algorithm SHA256 包路径`；Linux 用 `sha256sum 包路径`，先核对外部摘要，再解压到新的代码目录。manifest 的逐文件摘要证明包内一致性，不能代替从可信交付渠道核对总摘要。

安装受维护的完整 **CPython 3.14.10 标准 GIL、x64**，随后在解压目录创建隔离环境。Windows 10/11／服务器 x64 和 glibc Linux x86_64 是此锁的目标；Linux Pillow wheel 要求 glibc 2.27/2.28 兼容平台。ARM、musl 和 free-threaded 不在当前发行锁内。不要使用便携解释器承担正式部署。

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --no-index --find-links wheels/windows --require-hashes -r server/requirements-windows-cp314.lock
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe scripts/verify_server.py 'C:\交付\Zhihui-server-提交前缀.zip'
```

Linux：

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheels/linux --require-hashes -r server/requirements-linux-cp314.lock
.venv/bin/python -m pip check
.venv/bin/python scripts/verify_server.py /delivery/Zhihui-server-提交前缀.zip
```

锁包括直接与传递依赖的版本、官方发行 SHA256 和两平台 wheel；许可证在 `server/licenses`，索引见[第三方说明](../server/THIRD-PARTY-NOTICES.md)。本次受控更新 Flask 3.1.3、Werkzeug 3.1.9、Pillow 13.0.0、pypdf 6.21.4，加入 Waitress 3.0.2。官方版本及摘要核查不等于承诺软件无漏洞。解释器安全更新和后续依赖更新须重新锁定、回归及发行，不能在目标机随意升级部分包。

## 2. 持久目录与首位管理员

以专用非管理员运行账号持有代码读取权及独立数据／日志目录写入权。代码、配置、数据和备份分开；限制其他系统用户读取数据中的账号摘要及 `.session-key`。从[配置示例](../server/config.example.json)复制到代码目录外，填写绝对 `data_dir`、`log_dir`、精确域名列表和本机后端端口；避开8848。生产后端只监听 `127.0.0.1`，`trusted_proxy` 填 `127.0.0.1`，只接受这一跳本机 TLS 反代的 scheme。没有 TLS 反代时 Web 拒绝 HTTP。

Windows 路径在 JSON 中写成 `C:/Research/data`；`data_dir` 必须尚不存在。域名和证书由运维决定，不把示例域名照抄上线。

```sh
<venv-python> -m platform_app.deployment init --config <绝对配置路径>
```

按提示填写账号、姓名，并两次隐藏输入新的12—200字符密码。自动化验收／本机秘密管理器也可显式用 `--password-stdin` 从私有管道输入两行（导入授权只输入一行）；不要把口令写在命令参数、公开脚本或配置示例中。默认演示口令不可用。完成后只有这位管理员，没有演示成员、来源或虚构成果；重复初始化拒绝操作。用既有“维护→成员”分配独立成员账号和负责人资格，管理员身份不会扩大个人成果正文权限。

可选公开样本只在**空内容库、Web与worker均停止**时导入；保留现有成员，由有效管理员隐藏输入密码授权：

```sh
<venv-python> -m platform_app.deployment import-public --config <配置路径>
```

导入65来源／56题录及历史机器节选，重复执行返回同一映射，不生成虚构中心成果或调用AI。已有内容的库拒绝首次样本导入，避免混入真实业务；节选、未核对、非完整译文及历史hash限制沿[公开材料说明](portable-preview.md#随包内容与历史译文)。不要将演示数据库当正式空库。

## 3. TLS 反代与 Web

按[nginx示例](../server/nginx.conf.example)配置真实域名、证书和请求大小，先执行 nginx 配置检查。只对外开放 HTTPS443；后端不开放到校园网或公网。反代覆盖 Host 和 X-Forwarded-Proto，并清除其他来客转发头；不要把客户端任意 Host 或 scheme 原样作为信任依据。多级代理、远程反代与路径前缀不在本轮配置范围。

```sh
<venv-python> -m platform_app.deployment web --config <配置路径>
```

Web 使用 Waitress，内嵌档案线程在创建前关闭。登录页没有演示快捷登录，HTTPS cookie、Host名单、Origin与CSRF同时检查。Web `/health` 只表示Web及数据库可读，不能证明worker存活。日志在指定目录 `service.log`，按5MiB、3份轮换；检查系统服务日志及独立进程退出状态，不开启请求正文、Cookie、环境或AI凭据的调试日志。

## 4. 独立后台与启停

```sh
<venv-python> -m platform_app.deployment worker --config <配置路径>
<venv-python> -m platform_app.deployment worker-status --config <配置路径>
<venv-python> -m platform_app.deployment worker-stop --config <配置路径>
```

worker沿用既有 ingestion CLI 的采集→中文处理→档案／作者建议队列，每个数据目录只允许一个本入口worker。停止文件按随机实例身份请求协作退出，当前有界任务结束后停止；不要按端口或过期PID杀进程。`worker-status` 区分状态和心跳时间；旧心跳不能证明存活，须同时核对系统任务／服务状态。中断后的持久任务按既有租约、退避、幂等及未知费用保护续作，费用未知不会自动重发。不要再并行运行旧裸 ingestion CLI 或内嵌后台。

全新正式库AI暂停、无凭据，所有来源默认未启用；Web不会自动启动worker。运维实际授权持续采集或AI后，才按现有管理入口逐项启用、配置凭据／价格／预算并复核未知费用。显式单篇翻译权限不构成后台发送许可。源码包、配置示例和manifest均不携带真实凭据。

Linux 可从[systemd Web](../server/research-web.service.example)及[worker](../server/research-worker.service.example)模板填写绝对路径、专用账号后安装；`systemctl daemon-reload`，逐个启用并检查 `systemctl status`、`journalctl` 和实际HTTPS登录。停止worker使用 `systemctl stop`（SIGTERM），待当前任务结束；Web停止后才能升级。模板仅供目标机运维演练，当前本机未验证开机自恢复。

Windows 使用[原生计划任务脚本](../server/windows-tasks.ps1)，由运维在专用运行账号下填写绝对路径并注册两个“启动时”任务；它运行真实Python进程，不把普通Python注册成 `sc.exe` 服务。先手工前台验证，再注册并核对 `Get-ScheduledTaskInfo` 的状态、最近结果和独立worker心跳。脚本的 Stop 先请求worker协作停止并等待退出，再仅结束命名Web任务；禁用／删除任务不会删除数据。开机触发、运行账号及证书读取权须在目标机实际演练。

## 5. 备份、恢复、升级与回退

管理员从“维护→完整备份”下载包含账号、资料、历史与原件的ZIP，保存到受限的另一个目录／介质，按实际资料权限管理。备份不含AI凭据、部署配置或会话密钥，运维另行安全保管它们。按数据变化制定排程；本轮不代替运维配置备份排程。

```sh
<venv-python> -m platform_app.maintenance --restore <备份ZIP> --target <尚不存在的新数据目录>
```

恢复工具校验manifest、schema、对象关系和原件，成功后切换配置到新目录，以相同版本代码实际登录并核对关键记录、原件和权限，再放行使用。新会话密钥会使旧会话失效，需要重新登录。每次升级前停止Web／worker，做最终完整备份，记录旧代码SHA、配置及备份hash；恢复到新数据目录，用新代码启动完成迁移与验证，保留原代码／原数据目录。旧代码遇到更高schema会拒绝，不允许强行改schema数字。

上线切换有明确维护窗口；验证后才恢复投稿及后台。若尚无新写入，可切回旧代码与其**旧数据目录**。升级后已有新投稿时，先停写并备份新库，保存新增原件和记录，人工核对迁移／重放方案再切回；不能直接丢弃新库或让旧代码读取新库。完整回退和系统重启恢复由目标机运维演练并留证。

## 构建与隔离验收

在已提交、已审查的源树运行，两个发行包使用同一最终SHA：

```sh
python scripts/build_server.py --output <新输出目录> --cache <官方wheel缓存>
python scripts/verify_server.py <实际服务器ZIP>
python scripts/check_server_release.py --package <实际服务器ZIP>
```

CI在Ubuntu与Windows使用3.14、匹配hash锁、实际源码ZIP解包和Waitress，检查初始化、公开样本、会话／CSRF、附件、独立后台及备份新目录恢复。`--allow-dirty` 只用于施工预验收，manifest标记未发布，不用于交付。最终提交、必要CI、双轴审查、实际包hash与平台结果由Issue／PR交接记录绑定；包检查不宣称正式服务器已经部署。
