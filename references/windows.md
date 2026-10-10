# Windows 客户端清理

## 环境与入口

原生 Windows 10/11，Python 3.10+，系统 Windows PowerShell 5.1。仅当前系统用户；不要求常态以管理员身份运行，不改注册表、服务、系统 ID、代理或浏览器安全配置。

统一入口 `scripts/local_cleanup.py` 检测 `win32` 后调用 `windows_cleanup.py`。可以在 PowerShell 或 Windows Terminal 中使用 `py -3`；没有 Python Launcher 时使用实际已安装的 `python`。没有 Python 时先报告缺少运行环境，不在线下载并自动执行未知安装器。

```powershell
py -3 "<技能目录>\scripts\local_cleanup.py" audit
py -3 "<技能目录>\scripts\browser_inventory.py"
```

以上不修改源数据。不带 `--plan` 时不创建计划、备份或隔离目录。输出只含路径、数量、进程 PID/角色及校验摘要；不输出 token、Cookie 值、完整配置或带秘密的进程参数。

## 实际目标

| 模块 | 路径与范围 | 选项 |
|---|---|---|
| Claude Code 缓存 | `%USERPROFILE%\.claude` 内的 `cache`、统计缓存、`telemetry`、`usage-data`、用量日志 | 常规审计 |
| 普通 Desktop 数据根 | `%APPDATA%\Claude` 中实际存在的允许项 | 常规缓存 / `--desktop` |
| MSIX 数据根 | 当前用户 `Get-AppxPackage -Name Claude` 的已识别官方包，`%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude` 及 `LocalCache\Local\Claude` | 常规缓存 / `--desktop` |
| Desktop 缓存与日志 | 已识别数据根中的 `Cache`、`Code Cache`、`GPUCache`、`DawnGraphiteCache`、`DawnWebGPUCache`、`logs`、`Crashpad` | 常规审计 |
| Desktop 网站/登录存储 | 同一数据根中的 `Network`、`Cookies`、`Cookies-journal`、`Local Storage`、`Session Storage`、`IndexedDB`、`Service Worker`、`WebStorage` | `--desktop` |
| CLI 账号缓存 | `%USERPROFILE%\.claude.json` 与 `.claude\backups\.claude.json.backup.*` 的已知顶层账号字段 | `--reset-account` |
| CLI OAuth 登录 | `%USERPROFILE%\.claude\.credentials.json`，只移除已识别的顶层 `claudeAiOauth` 对象 | `--credentials` |

不移动整个 `%APPDATA%\Claude`、MSIX 包目录、`%LOCALAPPDATA%\Claude` 或 `%LOCALAPPDATA%\AnthropicClaude` 安装目录。仅有名字相似的包不属于目标；包身份变更或未知发布者时停止。未注册的残留 MSIX 目录不自动清理。

`--desktop` 会退出 Desktop 登录并移除本地网站存储、离线内容和相应存储中的偏好，可能影响依赖这些存储的本地功能。默认保留 `claude_desktop_config.json`、第三方推理配置、MCP、`claude-code-sessions`、`local-agent-mode-sessions`、附件、`vm_bundles` 及未知目录。因此不把网站存储清零写成所有 Cowork / Desktop 记录都已删除。

`.claude` 的项目、会话、历史、文件历史、计划、技能、插件、hooks、MCP、settings 和未知非目标文件均保留。凭据 JSON 的其他字段、`userID`、`machineID` 与未知字段保留。凭据格式不符时停止，不提取或解密值；Windows 凭据管理器、注册表认证项和第三方 API 环境变量不自动处理。

`CLAUDE_CONFIG_DIR` 改到默认路径之外、AppData 重定向到当前用户目录之外、UNC 网络目录、重解析点（包括 junction、符号链接、部分云占位文件）需要独立审阅；此后端不沿链接复制或删除。出现这些布局会停止，而不是猜测其他路径。

## 生成计划并确认

正常退出 Desktop、Claude Code 和原生连接进程后运行：

```powershell
py -3 "<技能目录>\scripts\local_cleanup.py" audit --desktop --reset-account --credentials --plan "<已有任务目录>\claude-cleanup-plan.json"
```

上述组合只是计划示例，不是预先授权。根据用户意图选择选项；仅清缓存时省略三个选项。计划绑定 Windows 平台、用户目录、AppData、MSIX 身份、选项和目标内容哈希，不能把 Mac 计划带到 Windows 执行。文件、环境或目标范围变化后必须重新审计并确认。

脚本用 `Get-CimInstance Win32_Process` 检测进程，不输出命令行。权限不足、无法确认 Node / 原生 helper 命令行、Claude 或 WSL 仍运行时停止；不强杀、不静默关闭 WSL。WSL 自身的 Linux 数据不在此原生 Windows 范围内。

## 执行与恢复

```powershell
py -3 "<技能目录>\scripts\local_cleanup.py" apply --plan "<任务目录>\claude-cleanup-plan.json"
```

真实交互终端要求 `CONFIRM <plan_id>`，与用户已批准清单对应。禁止管道代答、`--yes` 或绕过确认。执行顺序为：重新核验 → 创建受保护批次 → 完整备份 `.claude` / `.claude.json` 并校验内容 → 精确改写获批账号字段 → 移动获批缓存/网站存储 → 检查保留文件与目标 → 写回执。

- 配置备份：`%USERPROFILE%\.claude-cleanup-recovery\<batch_id>`。
- 移动目标：`%USERPROFILE%\.claude-cleanup-quarantine\<batch_id>`。
- 回执：计划同目录的 `<plan文件名>.receipt.json`，记录每项来源、目标及操作完成状态。

**隔离目录不是 Windows 系统回收站。** 通过回执映射恢复原位置即可；恢复前正常退出相关应用，遇到同名新资料先停下，不用旧凭据或旧会话静默覆盖。配置备份保留旧认证字段；备份和隔离批次设置为当前用户及 SYSTEM 可访问的 Windows ACL，复制/移动后的内容做校验。

备份、ACL、文件锁、校验或后续操作失败会停止，并报告部分执行项。源数据在完成备份前不改写；已经移动或改写的项不会被假称自动回滚。保留恢复资料，使用回执处理，不重复执行旧计划。

另行明确要求永久删除恢复副本时，先列出两个精确批次、告知可能含旧凭据且删除后不能从副本恢复，确认后：

```powershell
py -3 "<技能目录>\scripts\local_cleanup.py" purge --receipt "<任务目录>\claude-cleanup-plan.receipt.json"
```

要求 `DELETE <batch_id>`，校验批次 marker，不清整个 Windows 回收站、恢复父目录、其他批次或 CC Switch 混合备份。永久删除不承诺 SSD / 快照的取证级擦除。

## 浏览器

执行 [浏览器参考](browsers.md) 的逐配置原生设置流程。Windows 同样只处理 `claude.ai`、`claude.com`、`anthropic.com` 及真实子域，保护书签、密码、历史和其他网站。

Chrome/Edge/Brave/Chromium 的 `browser_inventory.py` 可列出 Local State 与实际配置目录并读取目标 Cookie 的计数，不读取值。Firefox 只列配置，Safari 只适用于 Mac。Cookie 计数为 0 不证明 Local Storage、IndexedDB、Service Worker 和其他分区全部清空；仍需设置界面核验。

## 工具权限与手动接续

脚本支持 Windows 不等于每个 Agent 会话都有本机权限。若终端启动、文件读取或浏览器设置页被执行环境拒绝：

1. 报告缺少哪项能力及哪些范围未处理，保留原数据。
2. 提供上面的只读命令，让用户在自己的本机 PowerShell / Windows Terminal 运行；根据输出生成具体清单，确认后再提供 `apply`。不要让用户粘贴 token 或完整凭据文件。
3. 浏览器控制受限时，逐个实际配置打开 Chrome `chrome://settings/content/all` 或 Edge `edge://settings/content/all`；入口版本不同则从“设置 → Cookie/网站数据”进入。搜索三个官方域，核对结果后删除；不能把“清除所有浏览数据”当作精确替代。
4. 若组织策略或系统文件权限仍拒绝，停止对应部分，交由用户/管理员按正常机制处理；不关闭安全策略或自动提权。

## 验证范围与来源

隔离测试验证账号字段与其他资料保护、进程/权限拒绝、备份与部分失败、计划/恢复批次校验。GitHub Actions 的 Windows 矩阵另在原生 NTFS 上检查 junction 拒绝和 ACL；测试只访问临时夹具，不连接真实 Claude 账号，也不代表每个 Desktop 版本都已实机覆盖。

- [Claude Code 认证与 Windows 凭据位置](https://code.claude.com/docs/en/iam#credential-management)
- [Claude Desktop Windows MSIX 部署](https://support.claude.com/en/articles/12622703-deploy-claude-desktop-for-windows)
- [Electron 用户数据与网站存储路径](https://www.electronjs.org/docs/latest/api/app#appgetpathname)
- [MSIX 路径虚拟化](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes)
- [Microsoft 重解析点](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)

已知 MSIX 虚拟化路径也有 [Anthropic 仓库中的现场问题报告](https://github.com/anthropics/claude-code/issues/26073)；该报告用于识别候选路径，不当作所有版本的路径保证。现场未知目录始终跳过。
