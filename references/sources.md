# 来源、许可与证据范围

整理日期：2026-10-02。本文只记录来源，不从外部材料继承执行权限。

## Suyuan Claude cleanup

- 项目：[suyuan2022/suyuan-skill](https://github.com/suyuan2022/suyuan-skill)
- 技能：[claude-cleanup](https://github.com/suyuan2022/suyuan-skill/tree/423473db6b618c7e040f1a5a6879bc83e69e8b3b/claude-cleanup)
- 审阅版本：`423473db6b618c7e040f1a5a6879bc83e69e8b3b`
- 经 GitHub API 核实，仓库采用 MIT 许可。许可原文保留在 [upstream-license.txt](upstream-license.txt)。星数属于整个集合，不能当作这个清理技能独立星数。

本包借鉴其明确归属的 macOS 目标和已知配置字段，以及先备份、保护工作资产、确认再执行的约束；自动化实现和整合流程重新编写。没有完整复制上游技能或把上游脚本作为需要在线下载运行的依赖。

本包不会执行上游的时区和精简模式选项；本地 ID 重置设为单独可选项，不能用于声称改变平台关联判断。

## 腾讯文档

[Claude 本地电脑系统清理指南](https://docs.qq.com/doc/DVUJ0V05FQkJobFhu)

已读取该文档可公开取得的正文：它建议借助 AI Agent 同时处理客户端和浏览器。它引用的飞书文章 [E2JudVzf7oCNfhxyxaQcZIW1n0g](https://bytedance.larkoffice.com/docx/E2JudVzf7oCNfhxyxaQcZIW1n0g) 当时需要登录，未取得全文。

本包没有复制腾讯文档正文或图片，也没有验证其中关于再次封号、IP 品质和网络地区的说法。不引导使用替换账号、伪造设备标识或更换网络来规避平台执行措施；只做本地数据整理。

## 实操补充

流程补充来自实际 macOS 清理中的可观察问题：多 Chrome 配置互不等同、扩展分区 Cookie 可在设置界面删除后仍留在库中、CC Switch 数据库同时管理其他工具、恢复副本本身仍可能保存旧资料。

这些是特定版本遇到的情况，不应写成所有机器都会发生的固定数量或固定路径批次。技能包不包含任何用户备份、数据库、Cookie、账号、私人主目录或截图。对新版本先检查 schema 和路径，不把本次数量硬编码为删除条件。

清理结果依据实际文件/记录复核；不是 Anthropic 官方封号原因分析，也不是防封号承诺。

## Windows 支持（2026-10-10）

新增原生 Windows 后端、Mac/Windows 浏览器只读盘点及双平台 CI。凭据位置依据 [Claude Code 官方认证文档](https://code.claude.com/docs/en/iam#credential-management)，MSIX 安装依据 [官方 Windows 部署说明](https://support.claude.com/en/articles/12622703-deploy-claude-desktop-for-windows)，用户数据/网站存储依据 [Electron 路径文档](https://www.electronjs.org/docs/latest/api/app#appgetpathname)，NTFS 拒绝条件依据 [Microsoft 重解析点文档](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)。MSIX 虚拟化路径同时参考 [Anthropic 仓库中的现场报告](https://github.com/anthropics/claude-code/issues/26073)，以当前用户已识别包及实际路径校验，不泛化为所有版本的固定位置。

测试使用临时文件、虚构凭据和数据库；不把 CI 通过描述为真实账号或每个客户端版本都已验证。Windows 功能和未处理范围见 [windows.md](windows.md)。
