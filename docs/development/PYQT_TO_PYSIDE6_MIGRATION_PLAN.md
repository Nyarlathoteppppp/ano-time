# PyQt6 → PySide6 迁移准备与实施计划

> 状态：M1 已在独立迁移分支完成；主分支仍保持 PyQt6 稳定运行。
>
> 目标：不购买 PyQt6 商业许可的前提下，保留现有 Python 实时翻译 Pipeline，完成可闭源分发的 macOS Beta 基础。

## 1. 结论与范围

当前实际有 **17 个生产 Python 文件**直接导入 PyQt6，而不是之前估计的 14 个。迁移目标是 PySide6：两者都映射 Qt 6，绝大多数 Widget、signal、layout 和 QThread 代码可以机械替换。

其中有 14 个属于当前主运行依赖闭包，3 个属于旧入口/辅助进程。**不能在当前可运行应用中混用两套 binding。**本机验证已确认：同一进程导入 PyQt6 与 PySide6 会触发 macOS Objective-C 重复类警告，存在不确定的崩溃风险。

所以迁移架构是：

```text
稳定主目录 / master：继续使用 PyQt6，供日常上课
        │
        ├─ 不改其 Qt runtime
        ▼
独立 PySide6 migration worktree：逐批转换、单模块测试、静态审计
        │
        ▼
完整活动依赖闭包都变为 PySide6 后：原子切换 + 完整实机回归
```

绝不做 `try: import PySide6 except: import PyQt6` 的永久兼容层，也不通过环境变量在同一份生产安装中来回切换 binding。它会让测试与真实运行不一致，长期必然变成隐性技术债。

本计划只迁移 Python Qt binding，**不重写 UI**，也不改变：

- Apple ASR、Apple Translation、音频采集。
- `Pipeline` 中 Preview / Final / deadline / latest-wins。
- 远程模型路由、费用与额度。
- Swift notch 程序与其 stdin/stdout 输入协议。
- 字幕展示策略、课程档案、术语和 Smart Hint。

## 2. 生产文件清单

### A. Worker / 非窗口基础层（第一批）

| 文件 | Qt 使用 | 当前测试覆盖 | 迁移风险 |
| --- | --- | --- | --- |
| `api_test_controller.py` | `QThread`、`pyqtSignal` | `tests/unit/translation/test_api_benchmark.py` | 低 |
| `dashboard_support/workers.py` | 4 个 `QThread` Worker、signal | Dashboard workflow 集成测试间接覆盖 | 低 |
| `subtitle_display_scheduler.py` | `QObject`、`QTimer` | `tests/unit/subtitles/test_display_scheduler.py` | 低 |
| `global_shortcut.py` | `QObject`、signal；Carbon 原生热键 | `tests/unit/ui_logic/test_global_shortcut.py` | 低—中 |
| `app_identity.py` | `QIcon` | `tests/unit/config/test_app_identity.py` | 低 |

### B. 普通控制中心页面和运行壳（第二批）

| 文件 | Qt 使用 | 当前测试覆盖 | 迁移风险 |
| --- | --- | --- | --- |
| `dashboard_support/widgets.py` | `QComboBox`、屏幕宽度 | 音频 / ASR panel 测试间接覆盖 | 低 |
| `dashboard_support/panels/asr.py` | `QWidget`、`QFormLayout`、`QMessageBox` | `tests/unit/ui_logic/test_asr_panel.py` | 低 |
| `dashboard_support/panels/audio.py` | `QWidget`、表单控件 | `tests/unit/ui_logic/test_audio_panel.py` | 低 |
| `dashboard_support/app_runtime.py` | `QApplication`、`QTimer`、`QLocalServer/Socket` | Dashboard 生命周期测试间接覆盖 | 中 |
| `shortcut_controller.py` | Dialog、button、checkbox；调用 Carbon 热键 | `tests/unit/ui_logic/test_controllers.py`、global shortcut 测试 | 中 |
| `dashboard.py` | 大型控制中心：Widget、绘制、Timer、图片、窗口关闭语义 | `tests/integration/dashboard/*`、多个 UI 逻辑测试 | 中 |

### C. 运行核心与窗口层（最后一批）

| 文件 | Qt 使用 | 当前测试覆盖 | 迁移风险 |
| --- | --- | --- | --- |
| `main.py` | `QObject`、signals、`QTimer`、`QApplication` 生命周期 | Pipeline contracts、realtime priority、工作流测试 | 中 |
| `native_notch_overlay.py` | Qt ↔ Swift helper bridge、Timer、signals | native notch / transport helper 测试 | 中—高 |
| `overlay_window.py` | 无边框、置顶、透明、Resize、QSettings、富文本、滚动 | overlay layout/factory、transport helper 测试 | 高 |

### D. 旧入口 / 非当前主路径（单独审计，不能盲迁）

| 文件 | 用途 | 当前状态 | 处理 |
| --- | --- | --- | --- |
| `launcher.py` | 旧依赖安装 GUI | 当前桌面启动器不走它 | 先确认是否删除/归档；不应混入主迁移 |
| `settings_window.py` | 旧独立设置窗口 | 当前控制中心不走它 | 先确认是否删除/归档 |
| `hotkey_daemon.py` | 旧 LaunchAgent 热键守护进程 | 当前主路径以 Control+S / 控制中心为准 | 单独评估；不可因迁移重启 LaunchAgent |

## 3. 已知 API 差异

### 3.0 目标 Qt 边界

最终只保留一个很薄的 `ui/qt.py`：它**只**导出 PySide6 的 `QtCore`、`QtGui`、`QtWidgets`、`QtNetwork` 和 `Signal` / `Slot` / `Property` 别名；不含 fallback、动态选择或业务逻辑。

```text
dashboard / panels / workers / overlays / Pipeline
                  ↓
              ui/qt.py
                  ↓
               PySide6
```

用途是让“应用只有一个 Qt binding”成为可审计规则，而不是把大量 `from PySide6...` 随意散落。`ui/qt.py` 不承担设置、线程、窗口或模型逻辑。

### 3.1 机械替换（预期低风险）

```python
# PyQt6
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# PySide6
from PySide6.QtCore import QObject, Signal, Slot
```

| PyQt6 | PySide6 | 影响 |
| --- | --- | --- |
| `pyqtSignal(...)` | `Signal(...)` | 类定义 signal 替换 |
| `pyqtSlot(...)` | `Slot(...)` | 若存在则替换；当前未发现生产代码使用 |
| `pyqtProperty` | `Property` | 当前未发现生产代码使用 |
| `from PyQt6...` | `from PySide6...` | import 路径替换 |
| `app.exec()` | `app.exec()` | 保持不变 |
| `Qt.AlignmentFlag` 等枚举 | 同名 Qt 6 枚举 | 预期保持不变 |

### 3.2 需要逐项回归的差异

| 领域 | 可能差异 | 验收 |
| --- | --- | --- |
| Signal 跨线程交付 | PySide6 对 QObject 所属线程、对象生命周期更敏感 | Worker 结束、暂停、退出时无 `QObject deleted` / `QThread destroyed` |
| `QImage` / `QPixmap` / `QPainter` | Python ownership、渲染时机差异 | 控制中心图片、图标、缩放无空白或模糊 |
| `QSettings` | 组织名/应用名不变才会读取既有几何设置 | 玻璃窗口大小与位置不丢失 |
| Window flags / 透明 | `WA_TranslucentBackground`、Tool、置顶在 macOS 合成表现需实测 | 全屏浏览器、外接屏、Mission Control、鼠标不漂移 |
| `QLocalServer/Socket` | 单实例、激活已有窗口 | 重复启动不产生第二个控制中心 |
| Carbon shortcut bridge | Qt event loop 配合差异 | Control+S 开始 / 暂停 / 恢复稳定 |

## 4. 迁移顺序

### M0：冻结基线（不改运行代码）

- 保存当前 `414/414` 全量测试基线。
- 在真实 Mac 验证：启动、暂停、恢复、停止；系统音频；麦克风；玻璃；三种刘海；Control+S；全屏浏览器；外接显示器（如可用）。
- 固定 UI 截图和延迟基准，记录当前 Python / PyQt / macOS 版本。

**验收**：迁移后任何指标异常都能定位为迁移回归，而不是旧问题。

### M1：第一批 Worker 与基础对象（已完成于迁移分支）

迁移 `api_test_controller.py`、`dashboard_support/workers.py`、`subtitle_display_scheduler.py`、`global_shortcut.py`、`app_identity.py`。

实现方式：上述文件均只通过新增的 `ui/qt.py` 访问 Qt。迁移中该边界暂时映射 PyQt6，让每个小批次继续可被稳定测试；最终依赖闭包完成时，单次切换边界到 PySide6。没有任何运行进程混用 binding。

**已验证**：416/416 完整 PyQt6 回归通过；M1 模块在 PySide6-only 环境导入烟测通过；新增静态回归测试禁止 M1 文件重新直接导入 PyQt6/PySide6。Dashboard 测试改为显式内存配置，不再依赖开发机忽略的 `config.ini`、Keychain 或个人 API 配置。

> M1—M4 的“逐批”指代码与测试的交付粒度，不代表主目录可在半迁移状态运行。只有完整依赖闭包完成后才做集成启动。

### M2：普通 Panel 与小控件（下一批）

迁移 `dashboard_support/widgets.py`、`dashboard_support/panels/asr.py`、`dashboard_support/panels/audio.py`、`shortcut_controller.py`。

**验收**：Audio/ASR 下拉框文字完整；保存、恢复默认、权限提示、快捷键设置不回归。

### M3：控制中心与单实例壳

迁移 `dashboard_support/app_runtime.py`、`dashboard.py`。

**验收**：重复启动仅激活现有窗口；叉掉控制中心、Control+S、停止、保存设置、透明度、动画均正常；不新增 WindowServer 鼠标漂移。

### M4：实时运行核心

迁移 `main.py`，只替换 binding import / signal 名称。

**验收**：现有 Pipeline 测试保持通过；Apple first partial、Apple draft、Preview、Final 基准不下降；停止后不接受迟到远程结果。

### M5：玻璃与 Swift notch bridge

迁移 `native_notch_overlay.py`、`overlay_window.py`。

**验收重点**：

- 玻璃 ↔ 刘海双向切换不崩溃。
- 三种刘海尺寸、自动收缩、右键暂停/退出、短碎片隐藏正常。
- 全屏视频置顶、外接显示器、Mission Control 正常。
- 40 条可见字幕限制、自动保存记录、滚动行为保持。

### M6：旧入口决策

明确 `launcher.py`、`settings_window.py`、`hotkey_daemon.py` 是删除、归档还是迁移。它们不进入可安装 Beta 前，必须有清晰的主入口说明。

## 5. 每批提交规则

```text
一个迁移批次
  = 只替换一个明确边界内的 PyQt6 import/API
  + 对应测试修正
  + 完整测试
  + 一项对应实机验收
  + 单独 Git 提交
```

### 5.1 Worktree 与环境规则

- `master` 始终保留当前可上课的 PyQt6 版本，迁移期间不作为 PySide6 试验场。
- 建立 `codex/pyside6-migration` 分支和独立 worktree；其虚拟环境只安装 PySide6，不与当前 `.venv` 共用。
- 每个迁移提交必须可以静态审计；完全可运行只在“活动依赖闭包全部迁移”后要求。
- 切换前必须执行 `rg 'PyQt6'` 审计：主运行路径、`requirements.txt`、启动脚本和测试不得残留 PyQt6。
- 老旧 `launcher.py`、`settings_window.py`、`hotkey_daemon.py` 不允许悄悄进主路径；先完成 M6 的删除/归档决策。

禁止：

- 迁移时顺手重构 `Pipeline` 或改 Prompt。
- 迁移时调整字幕速度、队列、超时、阈值或布局。
- 混合 UI redesign、素材替换、模型新增与 binding 迁移。
- 把当前角色素材用于 Beta / 商店发布。

## 6. 预先发现的风险

1. **当前 UI 角色素材不可发布。**迁移期间可保留本地开发效果，但 Beta 前必须换成拥有授权的原创/通用视觉资产。
2. **macOS native appearance 与透明窗口**是最高 UI 风险，不在 M1—M4 提前改动。
3. **Swift notch helper 不依赖 PyQt6**，但 Python bridge 依赖 Qt Timer/Signal；它只能在 M5 迁移后实机验收。
4. **当前桌面 AppleScript / `.venv` 启动方式不是 App Store 方案。**PySide6 迁移完成后仍要单独做打包，不要混做。
5. **LGPL 合规并不是“换一个 pip 包就结束”。**需要保留版权与许可证说明，并在真正分发时核对动态链接、用户替换库和 App Store 的兼容要求。

## 7. 开始 M1 前需要确认

- [ ] 对当前版本做一次 10—20 分钟系统音频实机基线。
- [ ] 确认 `PySide6` 可在项目 `.venv` 安装，并记录版本；不卸载 PyQt6。
- [ ] 确认 M1 前工作区干净、全量测试 414/414。
- [ ] 确认现有控制中心视觉资源仅开发用，不被加入公开 Beta 资产。
- [ ] 在发布前另行做 LGPL/上游版权合规复核。
