# CC Switch：可选的 Claude 专属数据清理

CC Switch 同时管理多种工具。它的 Claude 路由配置不一定与被封的官方账号有关，可能包含第三方 API 密钥。
只有用户明确同意删除 Claude / Claude Desktop 供应商配置及计划中列明的专属记录，才执行本参考。
不能把“清除官方登录缓存”自动扩大为“删除所有第三方路由”。
清理不解除服务端封禁，也不保证新登录安全；不修改 IP、时区、设备指纹或网络策略。

## 1. 只读盘点与范围确认

1. 检测 CC Switch 是否安装、正在运行，以及当前用户的真实数据根目录。
2. 常见数据根为 `~/.cc-switch`，其中可能有 `cc-switch.db`、`settings.json`、日志和自动备份；检测后使用，不硬编码用户路径。
3. 记录应用版本和数据库 schema；先用只读连接检查表、列、索引、外键、触发器及视图。
4. 只输出表名、列名、`app_type` 的计数、当前标志和代理状态，不输出供应商配置、API key、请求正文或 settings 原值。
5. 显示 Claude / Claude Desktop 供应商数量和拟删除记录类型，说明删除后需重新配置。
6. 显示其他工具和共用资产的保护范围，显示备份可能包含其他工具的密钥。
7. 若主确认未包含这些项，取得追加确认后才执行。

这里只处理精确 `app_type IN ('claude', 'claude-desktop')`。
不根据模型名称、供应商显示名、路径或文本中含 Claude 就批量删除。
标识不同或 schema 未知时停止写入，报告差异并重新制订计划。

## 2. 先停止接管与写入

1. 从 UI 检查本地代理和 Claude 配置接管状态。
2. 如启用了接管，先使用 CC Switch 自身的关闭/恢复操作，再检查应用管理的目标配置是否正常恢复。
3. 不能直接删配置使代理状态悬空，也不能静默切换到另一家 API 供应商。
4. 在 UI 删除阶段保留应用；进行直接文件或数据库写入前，正常退出 CC Switch。
5. 核实主进程、托盘后台和独立代理进程已停止，数据库不再被其他工具修改。
6. 如果无法停止或确认状态，保留备份并报告阻塞，不强杀进程后直接写库。

停用代理属于此可选清理的前置动作，应写在用户确认的计划中。
只处理 Claude 相关接管；不关闭其他应用正在使用的代理。

## 3. 恢复副本与保护基线

在第一次变更前创建本次私有备份目录，权限尽量设为目录 700、文件 600（Windows 使用当前用户 ACL）。
不得上传备份或把备份内容加入公开技能包。

至少保存：

- 当前 `settings.json` 的原始字节与文件权限。
- 原始数据库和存在的 WAL/SHM 文件；在应用正常退出后复制，确保它们属于同一个状态。
- 使用 SQLite backup API 另建一致数据库副本，执行 `quick_check` 验证。
- schema 摘要，以及其他应用与共用数据的保护基线。

原文件副本供调查和完整恢复，一致 SQLite 副本供可靠回滚；活跃 WAL 存在时不能只复制主数据库。
备份会保留被删除的密钥和记录。必须在报告中写清“活跃位置已清理，备份仍有旧资料”。
如果之后分为 UI 清理和数据库清理两个阶段，最终事务前再做快照并重建基线，不能用旧计数冒充当前状态。

保护基线应包含：

1. 每个已发现应用表中所有非目标记录，包括 `app_type IS NULL` 的记录。
2. 其他应用的供应商数、当前供应商标志和对应端点。
3. 共用表的完整行数和本地确定性内容摘要。
4. 非目标 settings 数据及 JSON 键值的本地摘要。
5. Claude 中性代理配置的关闭标志。

完整记录摘要只能在本机封闭校验进程内计算，敏感字段不显示、不发送、不解密。
采用稳定排序和明确字段编码；不把数据库文件总哈希作为行内容保护，因为正常 SQLite 写入会改变文件布局。
若表无稳定主键，用已核查的可确定排序方案；未知结构先停止。
报告可只显示计数和校验是否一致，避免披露账号名称、URL 或密钥。

## 4. 先通过 UI 删除供应商

1. 打开 CC Switch，分别检查 Claude Code 和 Claude Desktop 页。
2. 将 UI 项与只读数据库中的目标类型对应，不能只看供应商名字。
3. 对已在计划内的非当前供应商使用原生“删除”功能，核对确认对话框。
4. 当前供应商如果界面不允许删除，记录未完成项；不要为删除它启用另一家供应商。
5. 刷新页面并复核剩余目标数量。
6. 对需要最终数据库事务的残留，正常退出应用并再次验证进程与代理状态。

UI 删除可能同步改变配置与日志，因此最终写库前必须读取当前实际状态。
安装/版本升级、供应商连通性检测、向外部发送测试请求均不属于清理任务，不执行。

## 5. 已观察到的 schema 清理策略

以下为一个已实际使用的 schema 的策略，只有现场结构和外键吻合才可采用。
发现缺表、列含义不同、新触发器/视图或新应用标识时停止，不对未知版本照抄 SQL。

| 对象 | 处理范围 |
|---|---|
| `providers` | 仅精确目标 `app_type` 的行 |
| `provider_endpoints` | 目标复合外键级联；同时核验其他端点 |
| `provider_health` | 目标复合外键级联；同时核验其他健康记录 |
| `proxy_request_logs` | 仅目标 `app_type` 行；须已列入确认计划 |
| `usage_daily_rollups` | 仅目标 `app_type` 行；须已列入确认计划 |
| `stream_check_logs` | 仅目标 `app_type` 行；须已列入确认计划 |
| `proxy_live_backup` | 仅目标 `app_type` 行；先完成代理恢复 |
| 数据库 `settings` | 仅精确键 `common_config_claude` |
| JSON 设置 | 仅已确认的 `currentProviderClaude`、`currentProviderClaudeDesktop` 键 |
| `proxy_config` | 保留中性行，验证接管与启用标志已关闭 |

观察过的外键为 `(provider_id, app_type)` 引用 `providers(id, app_type)`，删除时级联。
必须在现场确认，不能只依据本表格假定级联存在。

以下默认保护：

- Codex、Gemini、Hermes 等所有其他应用行，及空/未知类型的行。
- `prompts`、`skills`、`mcp_servers`、`model_pricing`、`skill_repos` 等共用资产。
- `session_log_sync` 等会话同步水位；删水位可能使下次启动重新导入旧会话。
- 项目、CLI 会话和用户提示词。
- 非目标 settings 键、共用 UI 偏好和其他应用的当前供应商选择。

不为了清理把这些表清空。MCP 的 Claude 启用标志、技能或模型定价不等于账号凭据。
代理配置非中性、键含义未知时，先回到应用自身的恢复流程。

## 6. 最终数据库事务

只有确认计划包含直接数据库操作且备份、schema、保护基线齐备，才运行本节。
根据已审阅 schema 生成本机脚本，使用参数化值，并对表/列名使用审阅后的固定允许列表。
禁止用用户文本或数据库内容拼接任意 SQL。

事务流程：

1. 重新验证应用和代理完全停止、数据库路径与备份一致。
2. 用正常 SQLite 连接，启用 `foreign_keys` 与 `secure_delete`；取得 `BEGIN IMMEDIATE` 锁。
3. 读取事务内保护摘要与目标计数，对比最近确认基线；不一致则回滚并重新盘点。
4. 仅删除计划中的精确目标行和单个 settings 键，检查实际删除数。
5. 验证目标供应商及已授权的专属记录归零，检查外键和所有保护摘要。
6. 保留的中性代理行应保持关闭状态；其他应用的当前标志不变。
7. 全部符合预期才提交；异常立即回滚，不扩大条件、不跳过保护断言。
8. 提交后运行 `quick_check` / `foreign_key_check`，并独立只读复核。

对已经验证吻合的 schema，可按下列精确范围生成 SQL；这是参考，不能跳过上述检查执行：

```sql
PRAGMA foreign_keys = ON;
PRAGMA secure_delete = ON;
BEGIN IMMEDIATE;
DELETE FROM proxy_request_logs WHERE app_type IN ('claude', 'claude-desktop');
DELETE FROM usage_daily_rollups WHERE app_type IN ('claude', 'claude-desktop');
DELETE FROM stream_check_logs WHERE app_type IN ('claude', 'claude-desktop');
DELETE FROM proxy_live_backup WHERE app_type IN ('claude', 'claude-desktop');
DELETE FROM settings WHERE key = 'common_config_claude';
DELETE FROM providers WHERE app_type IN ('claude', 'claude-desktop');
-- 在此检查所有目标、保护摘要和外键；通过后 COMMIT，否则 ROLLBACK。
```

SQLite 碎片压缩如确需执行，放在提交之后，检查磁盘空间且应用仍退出；压缩后再核验保护摘要。
`secure_delete` 与压缩不保证 SSD、系统快照或既有副本上的物理擦除，不据此承诺无可恢复痕迹。
遇到 WAL，使用 SQLite 自身的受支持机制收尾；不能手工删活动 WAL/SHM。

## 7. JSON 设置与失败恢复

只移除确认范围内、现场已存在且含义确定的两个 Claude 当前供应商键。
其他键内容须完全保留；不要按键名包含 Claude 自动删 `skipClaudeOnboarding` 等功能偏好。
用同目录临时文件、原权限、完整写入与 fsync、原子替换保存，随后比较所有非目标键。
如 JSON 校验失败，恢复原始设置，保持 CC Switch 退出并报告数据库阶段的实际结果。
数据库与 JSON 是两个文件，不能声称 SQLite 事务自动保证二者原子性。
需要回滚时，先确认无进程使用文件，按本次已验证副本成套恢复，再检查完整性；不静默恢复旧凭据。

## 8. 混合日志、旧备份与最终报告

CC Switch 的旧自动备份通常同时包含 Claude 与其他应用资料。
共用文本日志也可能混合多个工具，不能删除整个日志目录或全体历史数据库。
默认保留并报告这些恢复材料可能含旧 Claude 数据，它们不是当前登录态。
若用户另要求永久删除，先列出确切文件、其他应用数据损失和可恢复性，再取得独立确认。
没有可靠格式解析和非目标保护办法时，不自行改写混合日志或历史备份。

报告至少包含：

- 实际处理的 CC Switch 版本、类型与记录类别，及核验状态。
- Claude / Claude Desktop 剩余供应商数；未授权的日志类别不能冒充已清零。
- 其他应用、共用表、JSON 非目标键的保护比较结果。
- 中性代理状态、数据库完整性、保留同步水位的说明。
- 备份位置、保留的混合日志/旧备份、仍未处理的项目。
- CC Switch 目前是否退出；恢复后需重新配置的内容。

不能把“供应商已清零”写成“电脑所有 Claude 记录均消失”。
以后启动 CC Switch 可能重新扫描保留的 CLI 会话；本技能默认保留这些用户资产。
