# 面向后续开发的近期变更

这里只记录对后续开发判断有帮助的事实，不复制完整 Git 日志。

## 2026-08-13

- `93233d5`：修复 Pipeline contract 测试夹具兼容性。`_segment_state_store()` 只从实例字典读取启动设置，避免未初始化的 `QObject` 测试对象触发 Qt 父类异常。完整测试恢复为 414/414。
- `6103c76`：产品路线改为 macOS 优先、iPhone/iPad 延期；明确不购买 PyQt6，近期方向是 PySide6。
- `9a163be`：新增受邀体验者指南、产品发布路线和 `tools/release_audit.py`。发布扫描只检查 Git 跟踪文件，永不打印匹配到的密钥。
- `codex/pyside6-migration` M1：新增唯一 Qt 绑定边界 `ui/qt.py`；`api_test_controller`、后台 workers、字幕显示调度器、全局快捷键和应用图标模块改为只经该边界导入 Qt。主分支运行行为未改。
- M1 测试安全网：Dashboard 工作流测试改为显式无密钥配置，不再读取开发者的 `config.ini` / Keychain；新增绑定边界静态测试。完整回归为 416/416，PySide6-only 导入烟测通过。

## 运行不变式

- 用户当前通过项目 `.venv`（Python 3.12）运行；不要用系统 Python 3.9 作为完整测试依据。
- 全量测试命令：`./.venv/bin/python -m unittest discover -s tests -q`。
- 发布前扫描：`python3 tools/release_audit.py .`。
- 界面相关测试会输出 Qt headless 警告，测试通过时不代表真实 macOS 全屏、权限和 Mission Control 已覆盖。
