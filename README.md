# Claude 封号后电脑清理

**Claude Post-Ban Computer Cleanup** · Skill ID: `claude-post-ban-cleanup`

专用于**曾在本机使用的 Claude 账号被封号的电脑**，清理与 Claude 有关的系统本地数据和浏览器记录。AI 先只读检查并展示具体清单，**用户明确确认后才执行清理**。

本机清理不能解除服务端封禁，也不能保证避免再次封号。本项目不修改 IP、代理、时区、硬件标识或浏览器指纹。

[下载技能 ZIP](https://github.com/l2461090/claude-post-ban-cleanup/raw/refs/heads/main/dist/claude-post-ban-cleanup.zip) · [完整使用说明](使用说明.md) · [AI 执行入口](SKILL.md) · [来源与上游许可](references/sources.md)

## 能做什么

- macOS / Windows：经确认清理 Claude Code / Desktop 的选定登录状态、缓存和相关数据。统一脚本自动识别平台，先备份并校验；Mac 移至专属废纸篓批次，Windows 移至专属隔离恢复目录。
- Windows：识别普通安装和已知 MSIX 安装的数据位置，只移除允许清单中的缓存/网站存储；保留 Desktop MCP 配置、Code/Cowork 会话和虚拟机资料。
- 浏览器：逐个实际用户配置处理 Claude 官方域的网站数据及已确认的相关扩展，需要 AI 工具具备浏览器或原生界面控制能力。
- CC Switch：可选清理 Claude 专属配置和记录，保护 Codex 等其他工具；现场结构须先核实。
- 恢复副本：默认保留；永久删除本次副本需要另列具体批次并取得确认，不清空整个废纸篓。

默认保留用户项目、CLI 会话、文件历史、技能、插件、MCP、书签、密码和其他网站数据。macOS 的整块 Desktop 持久数据可能含 Cowork 会话和本地附件，清理前会说明影响；Windows 不默认移动这些目录。

## Claude 会员开通指南

> [!TIP]
> **Claude充值指南 2026：国内怎么开通 Claude会员（支付宝/微信可用）**
>
> 正规充值平台 **[ai66.org](https://ai66.org)**
>
> ✅ **支付宝/微信可用**　｜　✅ **无需账号登录**　｜　✅ **安全可靠**
>
> ### 👉 [前往 ai66.org 开通 Claude 会员](https://ai66.org)

## 使用

需要能访问本机文件、终端和浏览器界面的 AI Agent。普通聊天页面仅接收文档时，不具备自动操作电脑的能力。

Codex 可将 ZIP 解压后的完整技能文件夹放入当前技能目录：Mac 通常为 `~/.codex/skills/claude-post-ban-cleanup/`，Windows 通常为 `%USERPROFILE%\.codex\skills\claude-post-ban-cleanup\`；自定义 `CODEX_HOME` 时使用其 `skills` 目录。

也可以让其他有本机权限的 AI 工具打开 [SKILL.md](SKILL.md)，遵循完整流程。不要让正在使用这些配置的 Claude Code 清理自身资料，应转交独立工具或普通终端执行。

发送：

> 我曾在这台电脑上使用的 Claude 账号被封号。请使用 $claude-post-ban-cleanup，检查相关系统本地数据和全部浏览器用户配置，先列出清理路径、影响和恢复位置，等我确认后再执行。保留项目、会话和其他工具数据。

流程：**只读检查 → 展示计划 → 用户确认 → AI 执行 → 核验报告**。

安装或打开技能不代表同意清理。Mac 和 Windows 脚本均要求真实终端确认，确认编号与完整计划内容绑定；范围变化后旧确认失效。不得自行生成同意或使用跳过确认的参数。

也可先在本机终端做只读检查：

```bash
# macOS
python3 scripts/local_cleanup.py audit
python3 scripts/browser_inventory.py
```

```powershell
# Windows（已安装 Python 3.10+）
py -3 .\scripts\local_cleanup.py audit
py -3 .\scripts\browser_inventory.py
```

需要重置登录时先生成计划，不能把 `audit` 当作已经清理。Windows 参数与执行步骤见 [Windows 使用参考](references/windows.md)。

## 平台与验证

客户端脚本需要 Python 3.10+，仅使用标准库；macOS 和原生 Windows 有独立清理后端。Windows 使用系统 Windows PowerShell 进行进程、MSIX 和 ACL 检查；Linux/WSL 暂不执行客户端写入。Windows 不自动卸载应用、不修改注册表或清空凭据管理器；自定义/未知布局停止并报告。

隔离测试覆盖两平台的确认拒绝、计划绑定、精确路径、保护资料、备份、部分失败与恢复批次删除，以及浏览器域名边界和只读盘点。GitHub Actions 在 macOS / Windows、Python 3.10 / 3.13 上运行；Windows 另检查 NTFS junction 和真实 ACL。测试不操作真实 home、浏览器登录或钥匙串，不表示验证过所有 Claude 版本。

```bash
python3 -m unittest discover -s tests -v
```

**工具权限仍然必要。** 如果 Agent 的终端、文件访问或浏览器设置页被策略拒绝，脚本不能绕过限制；可按 [手动接续步骤](references/windows.md#工具权限与手动接续) 在本机终端执行审计、逐配置使用浏览器原生设置，并保留未完成项说明。

## 来源

整合基于Claudecode源文件的封号机制逆向探查、海内外大神的防封号经验 以及 macOS 多浏览器配置清理经验，重新编写统一流程与脚本。

上游 MIT 许可原文保留于 [upstream-license.txt](references/upstream-license.txt)。本仓库不包含真实用户的账号、Cookie、数据库、恢复备份或私人路径。
