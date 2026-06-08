"""L2 数据层。

  - db.py       sqlcipher 封装（密码从 Keychain 取，含受控 connection 入口供 alembic）
  - schema.sql  7 张表（emails / attachments / labels / email_labels / sync_state / audit_log / events）
                # D4.3.1 复检修正: events 表(D4.3 新增) 后总数 7
  - models.py   SQLAlchemy 2.0 DeclarativeBase 7 Model（D3.2 引入 6 Model + D4.3.1 增 Event）
  - migrations/ alembic 迁移框架（D3.2 引入 — 与 SQLCipher 集成）
  - indexer.py  FTS5 全文索引 + sqlite-vss 向量索引（D4 智能层引入 — 与 LLM 分类一起做）

D3.1 = db.py + schema.sql（D3 阶段起步，2026-06-07 完成）。
D3.2 = models.py + migrations/（D3.2 启动 — ORM + alembic 迁移框架）。
D4+ = indexer.py（与 LLM 分类同步推进）。
"""
