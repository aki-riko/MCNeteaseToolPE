# MCNeteaseToolPE

> 网易《我的世界》中国版工程打包工具 —— 垃圾清理 / 打包审核 / UUID 重写 / ZIP 输出，一站式过审辅助。

MCNeteaseToolPE 面向网易 MC 中国版的地图与组件开发者,在提交官方打包机审前,
帮你把工程收拾干净、规避常见的过审阻断项,并支持一键自动更新。

四个工程步骤集中在同一个“工程处理”工作区：目录只需选择一次，再点击“一键处理
并审核”，工具就会按垃圾清理 → 打包审核 → UUID 重写 → 自动输出 ZIP 的顺序完成。
审核未通过时会停止，不会重写 UUID 或生成压缩包。

## ✨ 功能

- **🔑 UUID 重写**：为整个工程的资源包 / 行为包批量重写 `manifest.json` 中的 UUID
  并同步依赖引用,避免多包 UUID 冲突导致的导入失败或无法共存。操作在临时副本上
  校验后再落盘,不破坏原始工程。
- **🧹 垃圾清理**：扫描并清理临时文件、缓存与构建产物,减小打包体积。清理前列出
  待删项与预计释放空间；地图含开发工作台编辑信息时，还会清理根目录
  `.mcs`、`studio.json`、`work.mcscfg`，以及无 `manifest.json` 的
  `behavior_dn_*` / `resource_dn_*` Studio 链接注入目录。
- **✅ 打包审核**：本地静态模拟网易打包机审,覆盖常见错误码(1-40),提前发现上架
  阻断问题。审核只读,不修改任何工程文件；界面会持续显示当前检查项、行为包名称
  与总进度，长时间代码审核不再像卡死；审核结束后会用 PrismQML 桌面 Toast 在
  右下角提示通过或拒审及错误、警告数量。
- **📦 自动 ZIP**：审核通过并完成 UUID 重写后，在工程根目录自动生成与工程同名的
  `.zip`。压缩包只包含带 `manifest.json` 的组件包，不会混入 `.git`、测试、工具或旧 ZIP。
- **🔌 本机 MCP 服务器**：通过官方 Model Context Protocol Python SDK 提供
  Streamable HTTP 服务。服务器随程序自动启动，每次工具调用都从 AI 提示词接收目标
  工程路径，可调用工程识别、只读审核、清理预览、垃圾清理、UUID 重写和 ZIP 输出。
- **🔄 自动更新**：从 GitHub 检查新版本,确认后自动下载,右下角显示进度,完成后
  静默安装并重启。
- **🗃️ 世界数据编辑**：“NBT”页面除可编辑 `level.dat` 中的原版与网易 NBT 外，
  还会自动读取
  同级 `db` 的当前有效 `scriptData/ExtraData`，可直接校验和编辑地图、撤离点、拉闸方块、
  闸门控制台等 JSON。保存必须在世界关闭时执行；工具会先完整备份 `db` 目录，校验
  LevelDB sequence 与内容指纹，再追加 WAL 并重读验证，失败时自动回滚。

## 🚀 基于 PrismQML 引擎

本工具通过 **[PrismQML（棱镜映界）](https://github.com/aki-riko/PrismQML)** 的
Python/PySide6 接口驱动界面与自动更新能力：

- 业务逻辑由 Python 后端提供,QML 仅负责界面,前后端清晰分离。
- 自动更新为引擎内置的高层能力:Python 应用只需 `app.enable_auto_update(repo, version)`
  即可获得「检测 → 确认弹窗 → 进度环 → 静默安装重启」的完整流程,无需各自实现。
- 本仓库仅保留 Python/PySide6 实现，不再携带旧 C++ 应用与构建链。

如果你也想用 Python + QML 做现代桌面应用,欢迎了解并使用这套引擎:
👉 **https://github.com/aki-riko/PrismQML**

## 🔌 MCP 服务器

MCP 服务器随桌面程序自动启动和退出。底部“MCP”页面用一行状态和 TAG 显示接入端点数量，并提供一段
动态包含实际端点与安全规则的接入 Prompt；复制给 AI 后即可让它配置并验证连接。服务只允许监听 `localhost`、
`127.0.0.1` 或其他回环 IP，不接受局域网和公网绑定。

服务器提供十三个工具，覆盖桌面程序的工程处理、世界数据编辑和全局缓存清理：

- `process_project`：按垃圾清理 → 打包审核 → UUID 重写 → ZIP 顺序一键处理，必须显式传入 `confirm=true`。
- `get_project_overview`：读取工程类型和组件包概况。
- `audit_project`：执行现有只读打包审核。
- `preview_cleanup`：只读预览垃圾项和预计占用。
- `clean_project`：删除垃圾项，必须显式传入 `confirm=true`。
- `rewrite_project_uuids`：重写组件包 UUID，必须显式传入 `confirm=true`。
- `package_project`：创建或替换工程 ZIP，必须显式传入 `confirm=true`。
- `inspect_world_data`：读取、筛选 `level.dat` 和同世界当前有效的 `scriptData`。
- `get_world_data_value`：当读取结果标记 `value_truncated=true` 时，按最新 token 获取未截断完整值。
- `update_level_dat`：把最新 `summary.fingerprint` 传给 `fingerprint`，生成 `level.dat_old`
  并原子保存 NBT 修改；必须显式传入 `confirm=true`。
- `update_world_database`：把最新 `summary.extraDataSequence` 和 `summary.extraDataFingerprint`
  分别传给 `expected_sequence` 与 `expected_fingerprint`，完整备份 `db` 后保存 `scriptData`；
  必须显式传入 `confirm=true`。
- `scan_global_minecraft_data`：扫描推荐缓存和默认保护的有用数据分类，并返回一次性 `scan_token`
  与“清理全部”使用的 `recommended_category`。
- `clean_global_minecraft_data`：只接受扫描返回的分类与未过期 `scan_token`；保护分类还要求
  `confirm_protected=true`。

工程工具使用 `project_path`，世界数据工具使用 `level_dat_path`。两者必须是用户提示词、已确认的
对话上下文，或客户端明确标注且用户已确认的工作区绝对路径；服务端会拒绝相对路径，避免把它按
服务器工作目录误解析。不再在服务器启动前选择或绑定单一目录。全局清理使用程序配置的网易
Minecraft 数据目录。
执行全局清理前必须先扫描并向用户说明真实分类、大小与文件数，不允许猜测分类。
每次清理还必须原样传回本次扫描的 `scan_token`；扫描后数据发生变化或令牌已使用时必须重新扫描。
只读与修改操作分别携带 MCP `ToolAnnotations`；所有写操作仍要求 `confirm=true`。
默认监听配置可通过 `MCNETEASE_MCP_HOST`、`MCNETEASE_MCP_PORT` 和
`MCNETEASE_MCP_PATH` 环境变量覆盖，其中主机值仍必须是回环地址。

## 🛠️ Python 开发运行

Python 重写运行时使用 PyPI 发布的固定版本 `prismqml==0.3.2.11`，不再通过
`PYTHONPATH` 覆盖成本地引擎源码；MCP 使用固定版本 `mcp==1.28.1`。Windows
PowerShell 示例：

```powershell
$python = ".\.venv\Scripts\python.exe"
python -m venv .venv
& $python -m pip install -r requirements-build.txt
$env:QT_QPA_PLATFORM = "offscreen"  # 无头验证时设置；桌面运行可删除
& $python main.py
```

运行依赖版本见 [`requirements.txt`](requirements.txt)，构建与测试依赖见
[`requirements-build.txt`](requirements-build.txt)。代码审核以 2026-05-31 更新的网易官方
Python 模块白名单为红色 code 18 判据，并豁免行为包内实际存在的开发者自定义模块；
`mod.client.ui.controls` 及其控件子模块在官方白名单内，不会再被误报。

Python 语义审核只运行真实 Python 2.7.18 下的 Pylint 1.9.5，不再运行现代 Python 3
Pylint。主审核进程通过多个 Python 2.7 子进程取得结果，并用 JSON Lines 向界面回传真实
进度。官方 code 18 文档明确包含未开放 API、语法错误和禁止使用的方法；因此真实
Python 2.7 Pylint 输出的未过滤 `E` 类错误均作为红色拒审条件，并决定审核是否通过。
自动更新仓库、版本、资源关键词、安装参数和“关于”区域主页链接可分别由
`MCNETEASE_UPDATE_REPO`、`MCNETEASE_APP_VERSION`、`MCNETEASE_UPDATE_ASSET_KEYWORD`、
`MCNETEASE_INSTALLER_SILENT_ARGS`、`MCNETEASE_PROJECT_HOMEPAGE`、
`MCNETEASE_PRISMQML_HOMEPAGE` 环境变量覆盖。

开发环境的 Python 语义审核使用 Python 2.7.18、
`pylint==1.9.5` 和 `astroid==1.6.6`，通过 `MCNETEASE_PY27_RUNTIME` 指定
`python.exe`，通过 `MCNETEASE_MC_STUBS` 指定网易补全库目录。例如：

```powershell
$env:MCNETEASE_PY27_RUNTIME = "C:\Program Files (x86)\Python27\python.exe"
$env:MCNETEASE_MC_STUBS = "<mc_docs>\netease"
$env:MCNETEASE_PY27_WORKERS = "8"
& $python main.py
```

代码审核默认按全部逻辑处理器数量并发启动独立 Python 2.7 worker，不再设置固定并发
上限或对半折减；可通过 `MCNETEASE_PY27_WORKERS` 调整，设为 `1` 可恢复串行。每个
worker 都使用相同的 Pylint 1.9.5 配置，结果按原文件分片顺序合并。

设置页的“审核性能”卡片提供 PrismQML `SpinBox`，可在 `1` 到本机逻辑处理器数量之间
调整并发数；修改会与“工程处理”和“NBT”页面成功读取过的路径历史一起原子保存到
`%APPDATA%\MCNeteaseToolPE\settings.json`。页面下次打开时会恢复最近路径，两个路径
选择按钮的下拉菜单可直接切换历史项，其中 NBT 页面会自动重新读取最近文件。可用
`MCNETEASE_SETTINGS_FILE` 覆盖配置文件位置；如果进程
启动前已设置
`MCNETEASE_PY27_WORKERS`，该环境变量优先，SpinBox 会显示外部覆盖状态并禁止修改。

完整的旧版依赖锁定在 [`requirements-python27.txt`](requirements-python27.txt)。
Python 2.7.18 官方安装通常没有 pip，可先使用 pip 20.3.4 的 Python 2.7 引导脚本，
再执行 `python.exe -m pip install --user -r requirements-python27.txt`；这些包只装在
Python 2.7 的用户 site-packages，不加入主程序 `.venv`。

旧版 Pylint 不支持现代的 `--py-version` 参数；它直接运行在 Python 2.7 解释器中，
因此得到的是 Python 2 语义。该通道启用全部 `E` 类消息，只过滤 E1601、E0401、
E1101 与 E1102，其他 `E` 号全部保留。中文工程路径会只读复制到临时 ASCII 路径中审核，
结果再恢复为原始文件路径；临时目录会自动清理。所有未过滤 `E` 都显示为红色
CodeReviewError，与模块白名单违规共同阻止审核通过。未配置 Python 2.7 时，审核仍会
继续执行白名单和其他检查，只显示一条“Python 2.7 代码审核不可用”黄色提示。

网易文档没有公开通用贴图尺寸和文件名长度的精确机审阈值，因此默认不猜测。
取得当前平台阈值后，可分别通过 `MCNETEASE_AUDIT_MAX_TEXTURE_DIMENSION` 和
`MCNETEASE_AUDIT_MAX_FILE_NAME_CHARS` 启用相应审核。网易当前最高 `NetworkVersion`
也会随客户端升级变化；取得当前平台值后，通过
`MCNETEASE_AUDIT_MAX_NETWORK_VERSION` 启用地图版本上限审核。

## 📦 Nuitka 打包分发

构建脚本要求一个空输出目录，不会自动删除或覆盖旧产物，并严格使用项目虚拟环境内
与 `requirements.txt` 一致的 PyPI PrismQML；不会回退到本地源码。网易 Python 补全库
是可选项，只有确认来源允许再分发时才通过 `-McStubsPath` 纳入产物：

```powershell
.\build_nuitka.ps1 `
  -Python27Root "C:\Program Files (x86)\Python27" `
  -OutputDir "build\nuitka-release"
```

构建脚本会把 Python 2.7 解释器、`pylint==1.9.5`、`astroid==1.6.6`、
必要传递依赖复制到 `runtime/python27`。未内置补全库时，Python 2.7 语法与 E 类错误
审核仍会运行，网易模块导入继续由内置白名单检查；授权不明确的补全库不得放进发布包。

## 🚀 CI/CD 发布

GitHub Actions 会在 `master`、Pull Request 和版本标签上运行完整测试。只有符合
`vX.Y.Z.W` 的四段版本标签才会在 GitHub Windows runner 中执行 Nuitka 构建、打包产物审核、
Inno Setup 安装包生成及 GitHub Release 发布；本地不需要执行发布构建。标签必须与
`src/config.py` 中的 `APP_VERSION` 完全一致。Release 同时提供安装包、便携 ZIP 与
`SHA256SUMS.txt`。

发布版使用 Nuitka 的 Windows GUI 子系统：从桌面、开始菜单或安装程序启动时不会创建控制台窗口；
从已有终端显式调用 `--audit-json` 时会复用该终端输出验收 JSON。构建脚本会读取最终 EXE 的 PE 头，
若子系统不是 `WINDOWS_GUI (2)` 将直接阻止发布。

standalone 可执行文件支持只读自动验收，不会修改被扫描工程：

```powershell
.\build\nuitka-release\main.dist\MCNeteaseToolPE.exe --audit-json "<工程目录>"
```

构建脚本只会为审核功能打包 Python 2.7.18、Pylint 1.9.5、astroid 1.6.6 及其必要依赖；
主程序的 Python 3 环境不再安装或分发现代 pylint/astroid。

## 📦 安装包

安装包用 [Inno Setup](https://jrsoftware.org/isinfo.php) 生成,脚本见
[`installer/MCNeteaseToolPE.iss`](installer/MCNeteaseToolPE.iss)。先由
`build_nuitka.ps1` 生成 standalone 目录，再把该 `main.dist` 目录交给 Inno Setup：

```bash
iscc /DMyAppVersion=0.1.0.1 /DBuildDir="build\nuitka-release\main.dist" installer/MCNeteaseToolPE.iss
```

输出文件名包含 `Setup` 关键词,供自动更新按 GitHub release 资源匹配。安装包支持
`/VERYSILENT` 等静默参数,自动更新据此静默安装。

## 📄 License

Copyright (C) 2026 aki-riko

本项目采用 [GNU General Public License v3.0 or later](LICENSE)，SPDX 标识为
`GPL-3.0-or-later`。PrismQML 与其他第三方组件继续适用各自的许可证。
