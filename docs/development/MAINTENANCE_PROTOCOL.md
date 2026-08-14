# 开发维护协议

此文档规定 Anotime 每次开发都要留下的工程记录。它记录事实、决策、验收与未完成风险；不记录 API Key、账号、课堂文本、运行日志或用户本机路径。

## 文档职责

| 文档 | 何时更新 | 内容 |
| --- | --- | --- |
| [`AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) | 改变实时链路、上下文、路由、配置、验收基线时 | 当前运行不变式、所有权、真实设备门槛与下一安全步骤 |
| [`CHANGELOG.md`](./CHANGELOG.md) | 每次完成一个可验证开发批次时 | 日期、改动、影响范围、验证结果与遗留项 |
| [`DECISIONS.md`](./DECISIONS.md) | 作出会约束后续实现的长期取舍时 | 决策、理由、状态；历史不覆盖，只标记替代 |
| 本目录的计划文档 | 开始有风险的结构性改动前 | 目标、非目标、验收项与回滚边界 |

## 每次开发的最小闭环

1. 先读根目录 `AGENTS.md`、`docs/AGENT_HANDOFF.md` 与本次涉及模块的测试。
2. 在改动前写明不变式、受影响模块与验证方式；跨实时链路的改动必须有独立计划。
3. 小批次实现，不把 ASR、Apple 草稿、远程路由和展示层重构混在一起。
4. 为复现过的缺陷先补回归测试，再修复。
5. 运行 `./tools/run_tests.sh`、受影响模块的针对性测试、`git diff --check`；涉及发布边界时运行 `./.venv-pyside/bin/python tools/release_audit.py .`。Issue、PR、Action 与 Release 的对应规则见 [`GITHUB_WORKFLOW.md`](./GITHUB_WORKFLOW.md)。
6. 触及音频、Apple Speech/Translation、字幕展示、原生 helper、快捷键或生命周期时，补做对应 macOS 实机验收。
7. 在同一开发批次末尾追加 `CHANGELOG.md`。若改动影响运行不变式或发布门槛，同时更新 `AGENT_HANDOFF.md`。

## 变更记录模板

```markdown
## YYYY-MM-DD

- `范围/主题`：做了什么；明确没有改什么。
- 验证：列出命令、通过数量，以及需要人工实机确认的项目。
- 遗留：尚未处理的风险、假设或下一步；没有则写“无”。
```

## 当前基线（2026-08-14）

- 活跃运行分支：`codex/pyside6-migration`；PySide6 环境固定为 `.venv-pyside`。
- 当前桌面启动器指向该分支的工程；`AnoTime-macOS` 不属于本项目维护范围。
- 完整测试基线：2026-08-14 本批验证为 485 项通过。只有在变更后重新运行，才能更新该数字。
- Apple ASR 是默认延迟与资源基线；Parakeet 是实验路径，不得自动设为默认。
- 当前待办：进行 Phase 3 的受控 EOU 回放实验与 Phase 4 的 macOS 实机验收；不能只靠调低切段阈值。
