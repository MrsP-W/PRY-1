# L4 Agent 层 — 角色协作架构

> 我的AI员工的"灵魂层" — 7 个角色按"Agent Assistant 复制 + 本项目专属"双轨组织。
>
> **D5.5.3 演进(2026-06-12)**:5 个软链改为**实际文件复制**(原软链导致 `uv build` FileNotFoundError),保证发布包自包含。

## 角色清单（7 个）

### 🔴 复制自 Agent Assistant（5 个核心 — D5.5.3 由软链改为文件复制）

| 角色 | 文件来源 | 用途 |
|------|---------|------|
| `教练员.md` | 复制自 Agent Assistant | D-step 收官沉淀技巧 |
| `检查员.md` | 复制自 Agent Assistant | D-step 收官跑质量门 |
| `调试专家.md` | 复制自 Agent Assistant | D-step 阻塞排查 |
| `回顾员.md` | 复制自 Agent Assistant | D-step 锁定复盘 |
| `内容编辑员.md` | 复制自 Agent Assistant | 草稿模板 + 文档沉淀 |

### 🟡 本项目专属（2 个）

| 角色 | 文件 | 用途 |
|------|------|------|
| `管家.md` | 本目录 | 全天候数字员工视角 |
| `审计员.md` | 本目录 | 权限 + LLM + 数据流审计 |

### ⚪ 暂不接入

| 角色 | 原因 |
|------|------|
| @信息员 / @日报员 / @舆情监测员 | 我的AI员工不产新闻 / D5 调度器管日程 / 暂未涉及舆情 |
| @SAP顾问 / @安全审计员 | D5+ 财务集成时接入（D5.7+）|

## D-step 收官标准动作

每个 D-step 收官（如 D5.6 真实发送 spike 锁定）按此流程：

```
Step 1: @检查员 跑 8/8 质量门
  ↓ 通过
Step 2: @教练员 沉淀 1 条 Claude Code 技巧到 memory/
  ↓
Step 3: @回顾员 写复盘（v1.0.x 收口 + 下一版本预判）
  ↓
Step 4: 锁定 v1.0.x，commit + push
```

## 文件维护(原"软链维护"段修订)

- **D5.5.3 起**:5 个 Agent Assistant 复用角色改为**实际文件复制**(不是软链)。
  - 原因:外部软链 → `uv build` sdist 解析失败 → FileNotFoundError(P0 缺陷)
  - 优势:发布包自包含,跨项目独立
- **同步源文件**(`@教练员.md` 等在 Agent Assistant 有更新)→ 需**手动复制**到本目录
  - 短期方案:每月 1 号 `make sync-agents`(待建)对比两边并合并
  - 中期方案:Agent Assistant 改用 git submodule(待评估)
- **冲突解决**:本项目需要"我的AI员工专属"行为时,**先复制**源文件再改(不要直接改源,源文件会变)
- **新增角色**:先在 Agent Assistant 立项 → 复制到本目录(不再用软链)
