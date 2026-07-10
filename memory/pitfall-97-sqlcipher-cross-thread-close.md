---
name: pitfall-97-sqlcipher-cross-thread-close
description: SQLCipher + SQLAlchemy pool 多线程 close 报错 · Dashboard HTTP request 跨 thread 触发 ProgrammingError
metadata:
  type: project
---

# 撞坑 #97 — SQLCipher 跨线程 close 报错

## 现象(2026-07-10 撞坑 #95 修复 1h 验证中暴露)

```text
Exception closing connection <sqlcipher3.dbapi2.Connection object at 0x1069f4b30>
Traceback (most recent call last):
  File "/.../sqlalchemy/pool/base.py", line 375, in _close_connection
    self._dialect.do_close(connection)
  File "/.../sqlalchemy/engine/default.py", line 721, in do_close
    dbapi_connection.close()
sqlcipher3.dbapi2.ProgrammingError: SQLite objects created in a thread can only
be used in that same thread. The object was created in thread id 6232059904
and this is thread id 6248886272.
```

## 根因

- SQLCipher 默认 `check_same_thread=True`(与 sqlite3 一致)
- Dashboard server 每个 HTTP 请求 spawn 新 thread
- connection 在 thread 0 创建,SQLAlchemy pool GC 在 thread 1 close 时触发 thread check
- 报错在 SQLAlchemy pool GC 阶段(close-time),不影响 request-time
- 错误累积:30min→60min +38 行(每请求 +1 close-time traceback)

## 严重度评估

| 维度 | 评估 |
|------|------|
| fatal | ❌ 否(close-time 报错,request-time 正常) |
| 进程退出 | ❌ 否(Dashboard 持续 1h 零重启) |
| HTTP 阻塞 | ❌ 否(404 4ms 仍响应) |
| err log 累积 | ⚠️ 30→60min +38 行(24h 估 ~3000 行) |
| 修复优先级 | ⚠️ P0-4 24h 观察前建议修 |

## 修复路径

### 路径 A(已采用):`NullPool` — 每请求线程独立连接(代码已落地,2026-07-10 P1-1)

```python
# src/my_ai_employee/core/sqlcipher_compat.py
from sqlalchemy.pool import NullPool

def make_sqlalchemy_engine(
    db: Database | None = None,
    *,
    db_path: Path | None = None,
) -> Engine:
    creator = make_sqlalchemy_creator(db, db_path=db_path)
    if db_path is not None:
        # 长生命周期 Dashboard / Menu Bar:每请求线程独立连接
        return create_engine("sqlite:///", creator=creator, poolclass=NullPool)
    # 短生命周期脚本:同进程无并发,默认 pool 即可
    return create_engine("sqlite:///", creator=creator)
```

- ✅ 改动小(单文件,~15 行,只影响 db_path 变体)
- ✅ 零跨线程 close 风险:NullPool 每次 checkout 都让 creator 现建 sqlcipher3 connection,用完即关,close 一定在原 thread
- ✅ 配合回归测试 `tests/core/test_sqlcipher_compat.py::test_concurrent_threads_no_sqlcipher_cross_thread_close`(10 thread × 5 次 checkout,验证 stderr 无 `check_same_thread` ProgrammingError)
- ⚠️ 每次请求新建 sqlcipher3 connection,略增延迟(实测单 query <5ms,HTTP 404 仍 4ms,Dashboard 完全可接受)

### ~~路径 B(放弃):`check_same_thread=False` + StaticPool~~ ⚠️ **不推荐**

```python
# 不要这样做!
engine = create_engine(
    "sqlite:///", creator=creator,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

- ❌ **StaticPool 让多个 HTTP 请求线程共享同一条 SQLCipher connection**
- ❌ SQLCipher 写入并发可能破坏 WAL/finalize 顺序,把 close-time 异常升级为并发读写风险
- ❌ 与 P1-1 修复同样"快速"但安全性差得多,代码审查已警告

### 路径 C:`scoped_session`(thread-local,可选,~30 行)

```python
from sqlalchemy.orm import scoped_session, sessionmaker
Session = scoped_session(sessionmaker(bind=engine))
```

- ✅ 范本最标准(SQLAlchemy 官方推荐)
- ⚠️ 改动中等(~30 行,需重写所有 DB 调用点)
- ⚠️ 需小心 session lifecycle(避免 leak)

### 路径 D:`event.listens_for(engine, "connect")` PRAGMA(不直接修,需配合 A 或 C)

## 关联

- 撞坑 #95(#97 暴露的契机 — 拆 2 独立 LaunchAgent 后 Dashboard 持续跑 1h+ 才暴露)
- 撞坑 #94(menu_bar B 路径 · make_sqlalchemy_engine(db_path=...) · 同根 SQLAlchemy 池子)
- 沿 [[day13-day2-fixture-dryrun-closure-2026-07-03]] 加密 DB 接线范本

## 复现命令

```bash
# 1. 启动 dashboard
launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.dashboard.plist
# 2. 持续 HTTP 探针触发多 thread close
for i in {1..100}; do curl -s http://127.0.0.1:8765/api/notes/pending -o /dev/null; done
# 3. tail err log
tail -10 ~/Library/Logs/MyAIEmployee/dashboard.err.log
# 预期:看到 1+ 次 sqlcipher3.dbapi2.ProgrammingError
```

**Why**:P0-3 caffeinate 1h 观察暴露出 SQLCipher + SQLAlchemy pool 跨 thread close 报错。
**How to apply**:路径 A NullPool 已落地(`commit` 待 push · `sqlcipher_compat.py` 长生命周期 db_path 自动用 NullPool · `test_engine_from_db_path_uses_nullpool` + `test_concurrent_threads_no_sqlcipher_cross_thread_close` 回归测试已加)。后续 Dashboard / Menu Bar 任何长生命周期服务接 SQLAlchemy 都应走 `make_sqlalchemy_engine(db_path=...)` 让其自动 NullPool,**不要直接拼 `create_engine("sqlite:///", creator=...)`**。
