"""scripts/ — 命令行工具与 spike 脚本包。

D3.3 引入 `scripts/__init__.py` 让 mypy 把 scripts/ 视为包（避免双重模块名
`spike_sync` vs `scripts.spike_sync` 冲突）。每个 .py 脚本通过
`python scripts/xxx.py` 直接运行（仍走文件路径，不走包导入）。
"""
