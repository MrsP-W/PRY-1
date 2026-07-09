---
name: pitfall-94-launchd-menubar-db-context-manager
description: T3 L4 撞坑 #93 实战验证暴露 menu_bar.launchd 启动后 SQLAlchemy pool creator 撞 Database 已关闭 RuntimeError
metadata:
  type: pitfall
---

# 撞坑 #94 · launchd menu_bar DB context manager RuntimeError

**Why:**
T3 L4 真实 `launchctl load -w com.myaiemployee.digital-employee.plist`(2026-07-09 20:27)在撞坑 #93 完全修复(uv PATH / APP_SUPPORT / data dir / 9/9 预检)基础上,**菜单栏进程 subprocess 在 SQLAlchemy pool 首次创建连接时抛 `RuntimeError: DB 已关闭，无法访问 connection`(db.py:297)**。

**How to apply:**

## 触发链路(实测栈)

```
nohup ${UV_BIN} run python scripts/run_menu_bar.py > $MENUBAR_LOG 2>&1 &
  ↓
build_menu_bar_services() → 真实 Expense / NoteConfirm / Outbox Impl
  ↓ SQLAlchemy engine pool → creator() 调用
sqlcipher_compat.py:63 creator() → return db.connection
  ↓
db.py:297 RuntimeError("DB 已关闭，无法访问 connection。")
  ↓
数字员工 launcher 检测菜单栏启动失败 → 打印 ❌ → exit 1
```

## 根因(初步推测,**待 #94 决策后展开**)

- `Database.open()` 必须以 `with` 块使用,`__exit__` 后 `_closed=True`
- `make_sqlalchemy_engine(db)` 把 db 实例传给 SQLAlchemy **creator callable**
- launchd 数字员工 launcher 内的 `with Database.open() as db: ... make_engine(db)` 块退出后,nohup'd subprocess **仍在** 共享同一 `db` 实例?OR subprocess 重新 `load_env()` + `Database.open()`?
- 看 `scripts/run_menu_bar.py:55-58` —— `main()` 内 `load_env()` → `build_menu_bar_services()` → subprocess 独立开 DB,**不** 共享 parent 进程 db 实例
- 但报错栈显示调用栈经过 `make_sqlalchemy_creator(db)` → `creator()` → `db.connection`,说明 `db._closed=True` 已被设置
- **最可能**:`Database.open()` 内部 `_open_connection` → reader 线程 / pool 引发异常 → `__exit__` 路径异常退出 → 二次调用 `db.connection` 时已 closed

## 撞坑关联

- 沿 #91(Documents exec OS 拦截)+ #92(业务代码路径 Documents 沙箱)+ #93(launchd uv PATH 缺失)的 launchd 实战第四坑
- 与 #92 区别:#92 是路径(cwd/data/log),#94 是 DB context state
- KeepAlive=false → 数字员工不会重启循环(无资源浪费)

## 修复路径候选与当前落地

- **A · docs-only 接受**:菜单栏 UI 不是 D3.x 必需,数字员工核心(trigger task chains)不依赖菜单栏 → 接受当前状态,把菜单栏从 launchd 启动链移除 → 1h 观察可走
- **B · 代码改动**:`make_sqlalchemy_engine` 改成接受 `db_path` 而非 `db` 实例,subprocess 内独立 open Database → 已落地为代码修复候选,待真实 `launchctl load -w` 复验
- **C · 代码改动**:`make_sqlalchemy_creator` 内 `creator()` 调用前重新 lazy reopen → 1 D-step
- **D · 暂缓**:菜单栏维持现状,只确认 scheduler/imap/agent launchd 全绿,不进入 1h 观察

## 红线维持

- 不动 `db.py` 直到明确决策 → 撞坑 #1 + #50 严判
- 不写 `.env` 凭据 → 撞坑 #1
- 不启用 `ENABLE_NOTES_ENCRYPTION=1` → 撞坑 #65
- 撞坑 #93 完全验证成功:launchctl load + 9/9 预检 + uv 调用链路 实战通过
