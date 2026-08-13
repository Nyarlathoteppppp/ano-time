# 面向后续开发的近期变更

这里只记录对后续开发判断有帮助的事实，不复制完整 Git 日志。

## 2026-08-13

- `93233d5`：修复 Pipeline contract 测试夹具兼容性。`_segment_state_store()` 只从实例字典读取启动设置，避免未初始化的 `QObject` 测试对象触发 Qt 父类异常。完整测试恢复为 414/414。
- `6103c76`：产品路线改为 macOS 优先、iPhone/iPad 延期；明确不购买 PyQt6，近期方向是 PySide6。
- `9a163be`：新增受邀体验者指南、产品发布路线和 `tools/release_audit.py`。发布扫描只检查 Git 跟踪文件，永不打印匹配到的密钥。

## 运行不变式

- 用户当前通过项目 `.venv`（Python 3.12）运行；不要用系统 Python 3.9 作为完整测试依据。
- 全量测试命令：`./.venv/bin/python -m unittest discover -s tests -q`。
- 发布前扫描：`python3 tools/release_audit.py .`。
- 界面相关测试会输出 Qt headless 警告，测试通过时不代表真实 macOS 全屏、权限和 Mission Control 已覆盖。

## 2026-08-14

- 新增 [`../ARCHITECTURE_MAP.md`](../ARCHITECTURE_MAP.md)：为后续 agent 标出旧版 Python/PySide6
  原型的 capture、ASR、字幕事件、翻译、渲染、记录、配置与测试边界，并明确它不能与独立的原生
  App Store Swift 工程耦合。
- 未改动任何运行路径、配置文件、课程资料、日志或 API 密钥。该仓库继续作为本地课堂原型与
  迁移参考，不作为 App Store 构建来源。
