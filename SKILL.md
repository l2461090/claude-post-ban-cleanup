---
name: claude-post-ban-cleanup
description: 在 macOS 或 Windows 电脑上先审计、经用户确认后清理 Claude 本地登录状态、缓存和浏览器官方域数据。提供两平台客户端脚本、多浏览器配置盘点及可选 CC Switch 清理，保留项目、会话和其他工具资料。
---

# Claude 封号后电脑清理

英文名称：**Claude Post-Ban Computer Cleanup**。

**适用场景：曾在这台电脑上使用的 Claude 账号被封号。本技能针对这类电脑，对与 Claude 有关的系统本地数据和浏览器记录进行清理；先检查并展示清单，用户确认后再由 AI 执行。**

用于用户自己电脑上的登录重置、隐私整理和卸载排障。账号被封后可以清理本地残留，但这不能解除服务端封禁，也没有证据证明可避免再次封号。不要承诺“洗白设备”“绝对干净”或“清完不会封”。

## 能力与边界

- 随附 Python 标准库脚本支持 **macOS 和原生 Windows 客户端**清理，`local_cleanup.py` 自动选择平台后端。Windows 要求 Python 3.10+ 和系统 Windows PowerShell，详细路径与参数见 [Windows 参考](references/windows.md)。
- 浏览器与 CC Switch 由 AI 使用可用的应用界面、受支持接口或经过审阅的本机文件操作执行。`browser_inventory.py` 支持 Mac/Windows 的只读配置和 Cookie 元数据盘点，不执行浏览器删除。
- 浏览器要遍历所有实际用户配置，不能把同一个窗口内切换 Google 网页账号当成清理多个 Chrome 配置。
- 默认保留项目、聊天/编程会话、文件历史、技能、插件、MCP、提示词、书签、密码和其他网站数据。Desktop 持久数据可能包含 Cowork 会话和本地附件，纳入计划前必须说明。
- 不修改 IP、代理、时区、硬件/系统标识、浏览器指纹或遥测设置。可选本地 ID 重置仅针对 Claude 配置字段，不作为规避风控手段。
- Linux/WSL 不执行客户端写入；原生 Windows 不跨入 WSL 数据。未知路径、Windows 重解析点/目录联接、自定义配置目录和重定向到用户目录外的 AppData 须另行审阅，不能套用 macOS 删除命令。

## 授权规则

打开或安装技能只授权解释和只读盘点，**不代表同意清理**。先完成可审阅计划，再请求用户确认；未收到明确答复，停止在只读阶段。

确认清单应包含：操作系统、每个浏览器配置、精确域名/扩展、文件绝对路径、Desktop 资料损失、认证退出、CC Switch 配置损失，以及备份和恢复位置。macOS 使用专属废纸篓批次；Windows 使用专属隔离恢复目录，不是系统回收站。发现新目标或扩大范围后，补充计划并取得对应确认。

用户对已展示清单的明确答复，如“确认清理”“confirm”，可作为该批操作的授权。执行者可把用户已给出的确认传递到脚本的真实终端提示；不能自行生成同意、用管道代答或添加绕过确认的参数。遵守执行环境自身的权限与浏览器确认规则，不能用本技能绕过它们。

默认保留恢复副本。永久删除是独立选项：另列本次恢复批次，说明可能包含旧凭据且删除后不能再从这些副本恢复，取得明确确认后才能删除。不能以“全面清理”为由自行清空整个废纸篓、删除全部 Chrome 数据库或 CC Switch 的混合备份。

## 执行流程

### 1. 只读检查

读取 [客户端参考](references/client.md)，Windows 再读 [Windows 参考](references/windows.md)。在有本机文件和终端权限的 AI 工具里运行；Windows 用 `py -3` 替换 `python3`，没有 Python Launcher 时可使用 `python`：

```bash
python3 <skill目录>/scripts/local_cleanup.py audit
python3 <skill目录>/scripts/browser_inventory.py
```

脚本发现路径和进程状态，不输出 token、Cookie 值、完整账号配置或带秘密的进程参数。另盘点浏览器的实际配置目录和名称，以及 CC Switch 是否存在。使用 [浏览器参考](references/browsers.md)，需要清理 CC Switch 时再读 [CC Switch 参考](references/cc-switch.md)。

如果执行者正是使用这些文件的 Claude Code，仅做审计，转交 Codex、其他独立工具或普通终端执行。不要让 Claude Code 修改自身正在使用的资料。进程检测、PowerShell、文件或浏览器设置页访问受限时，报告具体阻塞，不把“检测失败”当作“已经退出”。按 [工具权限与手动接续](references/windows.md#工具权限与手动接续) 提供本机终端或原生设置步骤，不绕过审批、组织策略或浏览器安全限制。

### 2. 准备具体计划并确认

先正常退出 Claude 客户端和相关原生连接进程；不要强制结束有未保存工作的进程。根据实际存在的目标和用户意图生成计划。下面是 macOS 常见登录重置组合，**不是默认批准**：

```bash
python3 <skill目录>/scripts/local_cleanup.py audit \
  --desktop --reset-account --keychain \
  --plan <任务工作目录>/claude-cleanup-plan.json
```

Windows 的对应命令（PowerShell）：

```powershell
py -3 "<skill目录>\scripts\local_cleanup.py" audit --desktop --reset-account --credentials --plan "<任务工作目录>\claude-cleanup-plan.json"
```

Windows `--desktop` 只选择已知网站/登录存储，不移动整个 Claude 数据根；MCP 配置、Code/Cowork 会话、附件、VM 和未知目录保留。`--credentials` 只移除 `%USERPROFILE%\.claude\.credentials.json` 的已识别 `claudeAiOauth` 对象，保留其他认证字段；不扫描或清空 Windows 凭据管理器。

macOS 仅在用户选择时加入 `--rotate-local-id` 或 `--uninstall`。前者必须同时选择 `--reset-account`；后者会移除 Claude.app。Windows 不支持这两个选项：需要卸载时使用系统原生卸载流程并另列计划。不要默认修改应用 ID。

将脚本的具体清单与浏览器/可选 CC Switch 清单一起展示，说明备份会保存旧资料。先取得这份计划的用户确认。

### 3. 经确认执行客户端

```bash
python3 <skill目录>/scripts/local_cleanup.py apply \
  --plan <任务工作目录>/claude-cleanup-plan.json
```

Windows 同样用 `py -3` 和 Windows 路径运行 `apply --plan`。在真实 TTY 中运行，核对展示内容与获批计划一致，再传递用户确认所对应的 `CONFIRM <plan_id>`。脚本重新检查路径、计划和进程，先备份 `.claude` 和 `.claude.json` 并做内容校验，再将白名单项移入专属恢复批次，按平台处理获批的账号缓存和认证字段。Windows 恢复批次设置为当前用户和 SYSTEM 可访问的 ACL；不把 Unix `chmod` 当作 Windows 访问控制。

备份失败、源数据变化、进程未退出或权限不足时停止依赖操作，保留已有恢复资料。中途失败要报告已执行和未执行项，不能称为全部完成。

### 4. 清理所有实际浏览器配置

按 [浏览器参考](references/browsers.md) 使用正常浏览器设置清理选定官方域名及其子域名：`claude.ai`、`claude.com`、`anthropic.com`。逐配置打开并核验，精确区分 `upclaude.com` 等第三方站点。只有用户列入计划的相关扩展才移除。

先用浏览器界面，常规核验只查域名、Cookie 名、分区与计数。孤立扩展分区 Cookie 若界面无法移除，不能清整个 Cookie 库；需要按参考里的离线修复流程重新列出精确目标、备份与确认。

没有浏览器控制能力就报告这一具体限制，并提供当前用户配置的操作位置；可以继续已获授权的客户端部分，但不能假装浏览器已清理。不要自动登录新账号或接受注册条款。

### 5. 可选清理 CC Switch

仅当用户确认同时忘掉 Claude 供应商/路由配置时执行 [CC Switch 参考](references/cc-switch.md)。它可能保存第三方 API 密钥；这一步不是清理官方 Claude 登录所必需的操作。

不要删除整个 `~/.cc-switch`。对混合数据库按精确 `app_type` 划定范围，保护其他应用内容。数据库结构或代理状态不符合已审阅条件时停止，不能猜测表结构执行删除。

### 6. 核验并报告

输出每个配置/模块的完成、跳过或受阻状态，实际处理路径与记录数量，以及保留项目、恢复目录和未处理范围。数据库修改需完整性校验和非目标数据比较；客户端核验使用脚本 receipt。界面操作后使用可用截图展示结果，截图中不显示凭据。

“目标官方域 Cookie 为 0”“钥匙串条目未找到”是具体结论，不能由此推断所有本地痕迹永久消失。空扩展注册项、书签、日志、项目会话、备份等保留内容要如实说明。

## 用户另要求删除恢复副本

先定位本次脚本 receipt，列出其对应的恢复目录和专属废纸篓/隔离恢复批次。确认后运行（Windows 用 `py -3` 和 Windows 路径）：

```bash
python3 <skill目录>/scripts/local_cleanup.py purge \
  --receipt <本次receipt绝对路径>
```

真实 TTY 中要求 `DELETE <batch_id>`；只允许删除本脚本生成并通过 marker 校验的两个批次。浏览器和 CC Switch 额外创建的副本也需要列出精确位置、确认并核验；不要拿他人示例路径代入本机。删除后更新报告，删除副本不等于 SSD 的取证级覆写。

## 来源

参考腾讯文档可读取的正文、Suyuan 的 `claude-cleanup` 和实际 macOS 清理中遇到的多配置/孤立 Cookie/混合数据库问题，重写为统一确认流程。来源版本、许可和无法核实的内容见 [sources.md](references/sources.md)。不把腾讯文档中的网络建议或防封号说法作为操作依据。
