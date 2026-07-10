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

### 路径 A:`check_same_thread=False` + StaticPool(最快,~10 行)

```python
engine = create_engine(
    f"sqlite:///{db_path}?check_same_thread=False",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

### 路径 B:`scoped_session`(thread-local,推荐,~30 行)

```python
from sqlalchemy.orm import scoped_session, sessionmaker
Session = scoped_session(sessionmaker(bind=engine))
```

### 路径 C:`event.listens_for(engine, "connect")` PRAGMA(不直接修,需配合 A 或 B)

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
**How to apply**:P0-4 24h 观察前修复(路径 A 推荐),避免 24h 累积数千行 traceback 影响日志可读性。
