# 客户端审计与保护范围

## 已验证环境

Python 3.10+ 标准库，macOS 用户自己的主目录。执行者须有文件和终端权限；操作 home/Library 或钥匙串时，按 AI 工具本身的审批机制授权。脚本不安装依赖、不需要读管理员密码。

先读取 `local_cleanup.py --help`，以随附版本实际参数为准。遇到应用新版本改变路径，先核实应用归属，补充精确计划，不能扩展成任意文件匹配删除。

## 目标类别

1. **再生缓存与日志**：`.claude/cache`、统计/用量/遥测缓存，以及明确属于 Claude 的 macOS Caches、Logs、DiagnosticReports 和 CrashReporter 项。删除遥测文件不等于修改遥测开关。
2. **Desktop 持久数据**：明确属于 Claude 的 Application Support、HTTPStorages、WebKit、Preferences、ByHost 和 Saved Application State。可能含 Cowork 本地会话、附件、虚拟机包和运行环境；不是仅仅登录 Cookie。计划要显示路径与该影响。
3. **账号缓存**：`.claude.json` 已知顶层账号元信息/功能缓存键。只删除随附脚本允许的键，不根据字段名模糊搜索删除整个 JSON。同步内部 `.claude.json.backup.*` 的同类键，防止旧配置被恢复。
4. **钥匙串**：只查并删除 service `Claude Code-credentials`。用不带 `-g` 的 `security find-generic-password -s ...` 检测存在性，不提取秘密。删除后 CLI 需要重新认证；该凭据没有自动备份。
5. **可选应用移除**：只涉及明确路径 `/Applications/Claude.app` 或 `~/Applications/Claude.app`；不批量删除 Anthropic 或 Node 的程序。
6. **可选本地 ID**：仅 `.claude.json` 的 `userID`、`machineID` 和相同内部备份；保留其他字段，不修改系统硬件 ID。默认保留 ID。

## 保护范围

不移动整个 `.claude`，不删除 `projects`、`sessions`、`history.jsonl`、`file-history`、`plans`、`debug`、`skills`、`plugins`、`hooks`、`commands`、`agents`、`scripts`、`mcp-servers`、`CLAUDE.md`、项目仓库或其他 AI 工具资料。

保留 `settings.json`、`settings.local.json` 和 shell 配置。只读盘点若发现 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY`、`CLAUDE_CODE_OAUTH_TOKEN`，报告键名和位置、不报告值。它们可能是第三方 API 配置，不要把所有 Claude 环境变量都当作旧账号登录 token。

用户明确要求清除这些具体认证项时，另提交结构化修改计划：保留其他 env、权限、hooks、MCP、插件、模型和遥测键；先备份并只删获批字段。不要删除整个 `.zshrc`、`.bash_profile` 或设置文件。本脚本不自动修改这些文件。

## 备份、移动与部分失败

- 先完整备份原 `.claude`（若存在）与 `.claude.json`，逐文件内容校验；符号链接只备份链接本身，不跟随去复制外部目录。
- 限制恢复目录权限。凭据/会话备份可能包含敏感资料，不写入公开仓库、不作为共享技能内容、不上传云盘。
- Desktop 大文件直接移至专属废纸篓批次；该批次是它们的恢复位置。不要在备份失败时继续删除。
- 拒绝删除目标或父级路径的符号链接；保护路径重叠、计划被更改或新增目标需要重审。
- 任何步骤失败都保存已完成动作的 receipt。恢复时按其映射逐项还原，先关闭相关应用，不能以备份覆盖其他工具的新资料。
- receipt 的 `recoverable` 表示文件恢复批次仍存在，不表示被删除的钥匙串凭据也能恢复。

## Windows / Linux

本包没有验证过这两个平台的写入自动化。`.claude` 和 `.claude.json` 可以作为只读候选，不代表所有版本都一致。用当前应用官方文档、安装清单和当前 OS 用户目录确认归属；不要把 `/Applications`、`Library`、macOS `security` 命令直接翻译为不经验证的删除命令。

可以执行不写盘的审计、使用浏览器原生设置和受支持的卸载/退出登录功能。若用户需要文件层面的清理，明确告知平台限制并列出经过验证的候选目标和恢复机制，取得确认后再实施；未知 Desktop 数据路径应跳过并报告，不能假称全面清理成功。
