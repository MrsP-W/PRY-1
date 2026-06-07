"""L2 数据层。

  - db.py       sqlcipher 封装（密码从 Keychain 取）
  - schema.sql  5 张表（emails/events/transactions/notes/health_log）
  - models.py   SQLAlchemy ORM + 加密字段
  - migrations/ alembic 迁移
  - indexer.py  FTS5 全文索引 + sqlite-vss 向量索引

D3 实施。
"""
