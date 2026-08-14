# GitHub 开发管理基线

状态：**已将本地工作流文件纳入仓库；远端 Project、标签和 `master` 保护仍需仓库管理员在 GitHub 设置中启用。**

## 已纳入版本控制的规则

- `.github/workflows/verify.yml`：在 `master`、功能/修复分支 push 与所有 PR 上，运行 Python 全量回归、release Swift 刘海编译、Swift planner contracts 和受跟踪文件的 secret audit。
- `.github/pull_request_template.md`：要求描述行为变化、未改范围、自动测试、实机验收与回滚方案。
- `.github/ISSUE_TEMPLATE/bug.yml`：收集可复现的 ASR、刘海、玻璃、快捷键、权限与翻译缺陷，并在表单内禁止粘贴密钥、课堂文本、`config.ini` 或完整私有日志。

CI 只验证可自动化的合同；它**不能**替代真实 Mac 上的 ScreenCaptureKit 权限、物理刘海、全屏置顶、Control + S 或低音量识别验收。

## 远端一次性设置

仓库管理员应在 GitHub 完成以下设置，顺序固定：

1. 创建 Project：`AnoTime prototype maintenance`，字段为 `Status`（Backlog / Ready / In progress / Verify on Mac / Done）、`Area`、`Risk`、`Branch`、`Real-device required`。
2. 创建标签：`bug`、`asr`、`parakeet`、`notch`、`glass`、`shortcut`、`audio-permission`、`translation`、`release`、`needs-mac-test`、`security`。
3. 将 `master` 设为受保护分支：要求 PR、至少一个已通过的 `Verify AnoTime prototype / Python, Swift and release contracts` 检查；不允许 force push 或删除分支。
4. 保持 `codex/pyside6-migration` 作为当前原型事实分支。功能从它切 `fix/<area>-<short-name>` 或 `feat/<area>-<short-name>`；不直接提交到 `master`。

当前远端没有 Actions workflow、Issue、PR 或分支保护；上述远端设置不会由本地 Git 文件自动创建。

## 每次维护的 GitHub 闭环

1. 为可复现缺陷或独立功能建 Issue，写清复现、范围和验收。
2. 在 Issue 上关联计划文档；涉及实时链路、配置、权限或原生 helper 时，先在 `docs/development/` 写计划。
3. 在短生命周期分支实现，保持一个 PR 只解决一个风险域。
4. PR 按模板填写自动测试和实机结果；没有实机条件时明确标 `needs-mac-test`，不得写“已验证”。
5. 合并后在 `CHANGELOG.md` 记录 Issue/PR、commit、验证命令与仍需测试的事项；更新 `AGENT_HANDOFF.md` 的运行不变式。
6. 发 Release 前，补版本标签和 release notes，并再次运行 `tools/release_audit.py`；绝不上传 `config.ini`、Keychain 导出、音频、文稿或完整 Diagnostics。

## 当前批次映射

- `NOTCH_TRANSPORT_RELIABILITY_PLAN.md`：建议 Issue 标签 `bug`, `notch`, `needs-mac-test`。
- `PARAKEET_RELIABILITY_PLAN.md`：建议 Issue 标签 `asr`, `parakeet`, `needs-mac-test`。
- 本批实现尚未 push 或创建 GitHub Issue/PR；本地验证通过后才适合建 PR。
