# PySide6 目标架构

> 状态：迁移前设计。不改变当前 PyQt6 运行版本。

## 目标

让 Qt 只承担窗口、事件循环、定时器和跨线程信号；让翻译、配置、模型、术语和字幕策略继续是独立 Python 领域模块。

```text
┌──────────────────── macOS process ────────────────────┐
│ bootstrap                                               │
│  └─ app_runtime → QApplication → app_identity          │
│                                                         │
│ ui/qt.py                                                │
│  └─ PySide6 only                                        │
│                                                         │
│ Dashboard                                               │
│  ├─ Panels (audio / ASR / translation / home)           │
│  ├─ ShortcutController                                  │
│  ├─ UI workers                                          │
│  └─ SessionController                                   │
│       ├─ Pipeline (ASR / Apple draft / Preview / Final) │
│       ├─ OverlayWindow (glass)                          │
│       └─ NativeNotchOverlay (Swift helper bridge)       │
└────────────────────────────────────────────────────────┘
```

## 1. 单一 Qt 绑定原则

`ui/qt.py` 是唯一允许直接导入 `PySide6` 的生产模块。所有 UI 文件只导入它导出的 Qt namespace 或信号别名。

```python
# ui/qt.py — target shape
from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

Signal = QtCore.Signal
Slot = QtCore.Slot
Property = QtCore.Property
```

禁止：

- 任何 `PyQt6` fallback。
- 同一 Python 进程导入 PyQt6 和 PySide6。
- 将 `QWidget`、`QThread`、`QTimer` 放入翻译、术语、配额等非 UI 领域模块。
- 让 Worker 直接读写 Dashboard 控件。

## 2. 稳定接口

| 边界 | 保持方式 | 不允许发生的事 |
| --- | --- | --- |
| Pipeline → UI | `WorkerSignals` / `SubtitleEvent` | Pipeline 直接引用 `Dashboard` 或 `OverlayWindow` |
| Dashboard → Session | `SessionController` 窄接口 | Panel 自己启动 Pipeline 或关闭 Overlay |
| Worker → Dashboard | Qt signal 只传 primitive / dataclass | Worker 修改 widget、触发模型路由 |
| Glass ↔ Notch | `overlay_factory`、`OverlaySpec`、既有事件协议 | 两个窗口相互持有并直接控制对方 |
| UI → 配置 | snapshot / repository | 控件在多处写 `config.ini` 或 Keychain |

这些边界已经是当前重构中形成的可复用结构。PySide6 迁移只替换 Qt binding，不重新设计这些领域接口。

## 3. 启动与退出所有权

```text
app_runtime
  owns QApplication / single-instance server / crash hook
Dashboard
  owns visual widgets / UI timers / UI workers
SessionController
  owns Pipeline session / Overlay / display scheduler
Pipeline
  owns audio and translation task lifecycle
```

任何新 Qt 计时器必须有明确 parent；任何 `QThread` 必须由 owner 持有强引用，并在 owner 关闭时 `requestInterruption()` / `wait()` 或走现有停止逻辑。

## 4. 迁移 worktree 结构

```text
realtime-ton/                  # master：当前 PyQt6 稳定版
realtime-ton-pyside6/          # codex/pyside6-migration：仅迁移实验
  .venv-pyside/                # 只装 PySide6；不与 master 的 .venv 混用
```

迁移 worktree 必须做到：

1. 单元测试的 Python 进程里只存在 PySide6。
2. 每批只更改 Qt import / Signal 名称和对应测试，不顺便改业务。
3. 最终运行前，静态测试禁止 `PyQt6` 留在活动路径。
4. 最终集成回归通过后，才替换 `requirements.txt`、桌面启动器和生产 `.venv`。

## 5. 完成定义

- 所有 14 个活动 PyQt6 文件切为 PySide6 边界。
- 17 个文件中的旧入口完成删除/归档/迁移的明确决策。
- 全量测试在 PySide6-only 环境通过。
- macOS 实测：System Audio、Mic、Glass、三种 notch、切换、权限、Control+S、重复启动、退出、全屏浏览器、外接显示器。
- 发布前审计不含 PyQt6 runtime、旧启动器、私人配置或未授权视觉素材。
