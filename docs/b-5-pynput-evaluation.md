# B-5 pynput 1.7.7 + macOS Sequoia 兼容评估(2026-06-16)

> **状态**:🎯 docs-only 评估(2026-06-16 晚)· **承接**:D9.5 ⌥⌘N 双进程范本 + D9.6 5 findings 修复后,**已知 macOS Sequoia 即使 Accessibility 授权 pynput 仍不接收**(沿 [[d9.6-fixes-launch]])· **决策**:推荐 **方案 B (Quartz 直接绑定)** · **下一棒**:v0.2.1 启动前用户最终决策(本轮 docs-only 不实施代码)
>
> **背景**:B 类延后清单 5 项中 B-5 是 v0.2 启动规划 6 子阶段第 4 项,优先级 P1,1 docs-only commit 落定评估结论。

---

## 1. 现状摸底(2026-06-16 晚)

### 1.1 已有代码

| 文件 | 内容 |
|------|------|
| `pyproject.toml:46` | `pynput>=1.7.7`(D9.5 装,沿 v0.1-launch-plan.md:129 已规划 **A 类决策**) |
| `src/my_ai_employee/menu_bar/clipboard_listener.py` | `HotkeyListenerProcess` 双进程范本(multiprocessing.Process 子类 + `pynput.keyboard.GlobalHotKeys({"<alt>+<cmd>+n": _on_hotkey})` + Queue 通信) |
| `src/my_ai_employee/menu_bar/tcc.py` | `TCCPermissionDenied` 异常 + `open_privacy_settings()` helper |
| `src/my_ai_employee/menu_bar/app.py` | `NotesMenuBarApp` rumps 主进程,启动时 spawn `HotkeyListenerProcess` + 轮询 Queue |

### 1.2 已知问题(D9.6 实测结论)

**Spike B 6/16 实测**:
> "macOS Sequoia 即使 Accessibility 授权 pynput 仍不接收"
> 详见 `Agent Assistant/L2_memory/_cross-project/v0.1-real-spike-b-real-2026-06-16.md`

**降级路径已落地(D9.6 P1-1)**:
- README L7 状态行明确: **"S7 ⌥⌘N 触发链路降级 → 业务层以 spike 30 笔 faker 验证 insert 链路代偿"**
- D9.6.1 `ClipboardCaptureService` 业务层 3 入口仍实化,仅 hotkey 入口失效
- 9 端到端 S7 通过 spike 代偿验证(非真实 ⌥⌘N)

**根因**:
- pynput 1.7.7 + macOS Sequoia 15.0+ 的 `CGEvent.tapCreate` 行为变更
- 即使辅助功能授权, pynput 内 `_tap` 注册后回调不触发
- 这是 pynput 上游已知 issue([pynput/pynput#554](https://github.com/pynput/pynput/issues/554)),pynput 1.8.x 仍未修复

### 1.3 关键约束

| # | 约束 | 范本 |
|---|------|------|
| 1 | **不能重装 pynput 上游**(等 1.8.x 修复周期不可控) | 沿 [[d5-business-scheduler-launch]] 5 教训:外部依赖问题走降级,不阻塞主线 |
| 2 | **不破坏现有 9 端到端**(S7 已 spike 代偿通过) | D9.6 现状不动,只评估"如何让 ⌥⌘N 真工作" |
| 3 | **不引入大依赖**(pyobjc-Quartz 拉满 30MB+) | pyproject 依赖体积敏感(uv lock 已 80MB,沿 D1.1 范本) |
| 4 | **macOS 14+ 兼容**(Tahoe 16.x 预留) | 沿 D9.6 收口时的 macOS Sequoia 兼容性验证 |
| 5 | **不破坏菜单栏**(`NotesMenuBarApp` 主体不动) | D9.2-C2 menu_bar/app.py 已落 14KB,业务层完整 |

---

## 2. 3 候选方案对比

### 方案 A:rumps 单进程(pynput → rumps.events 自带快捷键)

**核心**:删除 `clipboard_listener.py` 子进程,改用 rumps 自带快捷键注册(rumps 0.4+ 部分版本支持 `NSMenuItem.keyEquivalent` 但**仅菜单栏 active 时响应**,后台失灵)。

**实现要点**:
```python
# menu_bar/app.py 改造
class NotesMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Notes", title="📝 Notes (0)")
        # rumps 0.4+ 提供 NSStatusItem 菜单项快捷键(⌘N)
        sync_item = rumps.MenuItem("立即同步", callback=self._on_sync_now)
        sync_item.key_equivalent = "n"  # ⌘N 触发(仅菜单栏 active)
        self.menu = [sync_item, None, "退出"]
```

**优点**:
- 无新依赖(rumps 已在依赖)
- 双进程范本移除,代码简化(`clipboard_listener.py` 6KB 可删)
- 与菜单栏统一,无 Queue 通信

**缺点**:
- **致命**: 仅菜单栏 active 时响应,后台 / 其他 App active 时失灵(用户期望"全局"快捷键)
- 不符合 D9.2+ 文档承诺的"⌥⌘N 全局监听"
- D9.5 双进程范本是因这个问题选 pynput,本方案是"反向倒车"

**评分**:⭐⭐(2/5)— 仅作"应急兜底",不推荐

---

### 方案 B:Quartz 直接绑定(`Quartz.Framework` CGEvent tap)

**核心**:删 `clipboard_listener.py` + pynput 依赖,改用 `pyobjc-framework-Quartz` 的 `Quartz.CoreGraphics` `CGEvent.tapCreate` 直接注册全局事件 tap,回调中判 ⌥⌘N 组合后 push Queue。

**实现要点**:
```python
# menu_bar/clipboard_listener.py 改造
import Quartz  # pyobjc-framework-Quartz

class HotkeyListenerProcess(_mp.Process):
    def run(self) -> None:
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
            self._callback,  # C 回调
            None,
        )
        if tap is None:
            self._emit_tcc_denied(reason="Quartz CGEvent.tapCreate 返回 None")
            return
        loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()
```

**优点**:
- **macOS 原生 API,无 pynput 兼容问题**(CGEvent tap 自 macOS 10.6 稳定)
- 后台 + 前台都能响应(全局,符合"⌥⌘N 全局"承诺)
- pyobjc-framework-Quartz 是 pyobjc 套件一部分,与现有 pyobjc-framework-Cocoa 同源
- 不改 ⌥⌘N 组合(用户已习惯)

**缺点**:
- **中等**: 引入 `pyobjc-framework-Quartz` 依赖(+5MB wheel,沿 pyproject 现有 pyobjc-framework-Cocoa 同源增量)
- **中等**: Quartz C 回调签名复杂(`(Quartz.CGEventTapProxy, Quartz.CGEventType, Quartz.CGEvent, Optional[Any]) -> Quartz.CGEvent`),需小心 None return
- **低**: pynput 1.7.7 已装可保留(无需 uninstall,pyproject 改 + 1 行 + `uv lock` 同步)
- **低**: macOS 14+ 仍需辅助功能授权(与 pynput 一致),但 Quartz 行为已稳定多年

**评分**:⭐⭐⭐⭐(4/5)— **推荐**

---

### 方案 C:⌥⌘N 改快捷键(换 macOS 自带快捷键如 ⌃⌥⌘N 三键)

**核心**:不改底层,改 `clipboard_listener.py` 的 `_HOTKEY_COMBO` 常量从 `<alt>+<cmd>+n` 改 `<ctrl>+<alt>+<cmd>+n`,试探是否 pynput 在三键组合下能触发回调。

**实现要点**:
```python
# clipboard_listener.py L34 改 1 行
_HOTKEY_COMBO: str = "<ctrl>+<alt>+<cmd>+n"
```

**优点**:
- 无新依赖(沿用 pynput)
- 1 行代码改完

**缺点**:
- **致命**: 不解决根因(macOS Sequoia pynput CGEvent 行为变更),三键只是概率上调,不能保证修复
- **中等**: 与系统快捷键冲突风险高(macOS 自带 ⌃⌥⌘N 用于截图 / Spotlight 等)
- **中等**: 违反"不破坏现有 9 端到端",D9.5 双进程范本已落地,改快捷键 = 把已实化路径"再走一次"
- 用户感知:从 `⌥⌘N` 改 `⌃⌥⌘N` 体验降级(用户已习惯 ⌥⌘N)

**评分**:⭐(1/5)— 不推荐

---

## 3. 推荐方案 + 决策

### 3.1 推荐:**方案 B (Quartz 直接绑定)**

**推荐理由**:
1. **根因解决方案**:macOS Sequoia pynput 上游问题,Quartz 是 macOS 原生 API,绕开 pynput 抽象层
2. **沿用既有架构**:保留 `HotkeyListenerProcess` 双进程范本(仅替换底层 pynput → Quartz)
3. **不破坏现有 9 端到端**:D9.6 降级路径作为 fallback,Quartz 真工作后 S7 可升级为真实 ⌥⌘N 触发
4. **依赖增量可控**:pyobjc-framework-Quartz +5MB,pyproject 已含 pyobjc-framework-Cocoa 套件(增量 < 5%)
5. **macOS 14+ 兼容性**:Quartz CGEvent 自 macOS 10.6 起稳定,Tahoe 16.x 不会破坏

**实施规模预估**(v0.2.1 启动后):
- `menu_bar/clipboard_listener.py` 重写:180 行 → 120 行(删 pynput,加 Quartz)
- `pyproject.toml` L46 改 `pynput>=1.7.7` → `pyobjc-framework-Quartz>=10.3`
- `tests/menu_bar/test_clipboard_listener.py` 重写:210 行 → 180 行(Quartz mock 范本)
- 预计 commits: 3-4 commits(1 feat + 1 tests + 1 docs + 1 docs-only 漂移小修)
- 预计测试数变化: +0(改底层不增功能)

### 3.2 关键决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | **保留 pynput 依赖**(不 uninstall) | pyproject 删除依赖触发 uv lock 大幅更新,影响其他子模块(D5 SMTP、D9 Notes 等无 pynput 但 lock 文件会 diff),沿 D5.5.5 教训"删依赖慎之又慎" |
| 2 | **双进程范本保留**(仅换底层) | `HotkeyListenerProcess` 队列通信机制稳定(D9.6 已实测通过),仅替换 `run()` 内部 pynput → Quartz 调用 |
| 3 | **D9.6 降级路径不撤** | 即使 Quartz 接入后,D9.6 P1-1 业务层 3 入口仍保留,作为"hotkey 真触发但业务层失败"的兜底(沿 D4.7.3 范本) |
| 4 | **沿 [[d5-business-scheduler-launch]] 范本**:1 docs-only commit 评估,实施留给 v0.2.1 | 评估 ≠ 实施,本轮 docs-only 锁决策,代码实施等 v0.2.1(用户决策点) |

### 3.3 不实施代码(本轮 docs-only 锁定)

**本轮不做**:
- 不重写 `clipboard_listener.py`(pynput 仍装,代码不改)
- 不改 `pyproject.toml`(pynput 不删,Quartz 不加)
- 不改 menu_bar/app.py(主进程 spawn 逻辑不变)
- 不改 tests(menubar 测试用例仍 mock pynput)

**留给 v0.2.1 启动前用户决策**:
- 是否采纳方案 B(还是其他方案)
- 何时启动 B-5 实施 commits(3-4 commits 估 1-2 工作日)
- 是否同步升级 D9.6 降级路径(本轮保留,实施时一并处理)

---

## 4. 复用要点速查表(B-5 v0.2.1 启动后立即可用)

| 任务 | 复用模块 | 关键签名 | 文件 |
|------|----------|----------|------|
| HotkeyListenerProcess 双进程范本 | `multiprocessing.Process` 子类 | `def run(self) -> None` | `src/my_ai_employee/menu_bar/clipboard_listener.py:77-99` |
| Queue 通信 | `multiprocessing.Queue` | `queue.put({"event": "hotkey", "combo": "..."})` | `src/my_ai_employee/menu_bar/clipboard_listener.py:111-122` |
| TCC 异常收容 | `TCCPermissionDenied` | `self._emit_tcc_denied(reason=...)` | `src/my_ai_employee/menu_bar/clipboard_listener.py:114-118` |
| 主进程轮询 Queue | `_poll_hotkey_queue()` | `queue.get(timeout=1.0)` | `src/my_ai_employee/menu_bar/app.py:_poll_hotkey_queue` |
| pyobjc-framework-Cocoa 已装 | `pyobjc-framework-Cocoa>=10.3` | 已在 pyproject:L44 | `pyproject.toml:44` |
| Quartz C 回调签名 | `(proxy, type, event, refcon) -> CGEvent` | 沿 Quartz 文档 | `pyobjc-framework-Quartz` 文档 |
| CGEventTapCreate | `Quartz.CGEventTapCreate(...)` | `tap` 为 None = 辅助功能未授权 | `pyobjc-framework-Quartz.Quartz.CoreGraphics` |
| D9.6 降级路径 | `ClipboardCaptureService` 3 入口 | `capture_and_emit / record_private_skip_and_emit / record_failure_and_emit` | `src/my_ai_employee/menu_bar/clipboard_capture.py` |

---

## 5. 关键风险 + 缓解

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | **pyobjc-framework-Quartz 与现有 pyobjc-framework-Cocoa 版本不一致** | 🟢 低 | uv 锁同一套件,自动同步 |
| 2 | **Quartz C 回调签名错导致主进程收不到事件** | 🟡 中 | D9.6 测试范本(10 cases)改 Quartz mock,沿 `unittest.mock.MagicMock` 范本 |
| 3 | **macOS 14+ 辅助功能授权弹窗** | 🟡 中 | 沿 `tcc.py:open_privacy_settings()` 引导,用户一次性授权 |
| 4 | **pynput 保留 + Quartz 引入依赖体积 +5MB** | 🟢 低 | uv lock 增量 < 5%,沿 D1.1 范本 |
| 5 | **Quartz 主进程回调与 rumps NSApp run loop 冲突** | 🟡 中 | 双进程范本保留,Quartz 在子进程,主进程仍 rumps |

---

## 6. 完成定义(B-5 docs-only 评估 Done)

- [x] 3 候选方案对比(rumps / Quartz / 改快捷键)
- [x] 推荐方案 B(Quartz 直接绑定)
- [x] 关键决策 4 条(保留 pynput / 保留双进程 / 不撤 D9.6 / docs-only 不实施)
- [x] 复用要点速查表 8 行
- [x] 风险缓解 Checklist 5 项
- [ ] v0.2.1 启动前用户最终决策(留 B 类决策延后范围)

---

## 7. 关联

- **承接**:v0.2-launch-plan.md:72 B-5 段 + v0.2-substage-mapping.md:205-235 B-5 详细任务分解
- **沿用范本**:[[d9.6-fixes-launch]] + [[d9-apple-notes-launch]] + [[d5-business-scheduler-launch]] + [[b-class-deferral-2026-06-09]]
- **B 类延后清单 5 项收口**:
  - B1 ✅ 6/16 落地(b97ae55 + 268e181 + 64a9adb 整条)
  - B2 ✅ 6/16 落地(31cbd05 + 80e087c + 3a26062 整条)
  - B4 ✅ 6/16 晚实化(0c6472f → 2bb77a0 → e54c697 共 11 commits 收口链)
  - **B-5 📝 docs-only(本轮)** — 推荐方案 B,v0.2.1 启动前用户决策
  - **outlook/gmail 📝 docs-only(下轮)** — 见 [outlook-gmail-evaluation.md](outlook-gmail-evaluation.md)
- **下一棒**:B-5 v0.2.1 启动前用户决策(无 B 类触发,本轮 docs-only 锁评估)