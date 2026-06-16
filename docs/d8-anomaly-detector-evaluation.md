# D8 智能财务(LLM 异常交易检测)评估(2026-06-16 晚)

> **状态**:🎯 docs-only 评估(2026-06-16 晚)· **承接**:D6.3 categorizer(142 行,5 大类 + 关键词规则 + 商家表兜底)+ D6.3 merchants(82 行,654 条去重 5 类均匀)+ D6/D7 跨源去重 + D10.2 monthly_report.py 月报真实生成(Spike C 6/16)+ 9 端到端 S8 已实化· **决策**:推荐 **方案 A (基于规则的异常检测)** 作为基础 + **方案 C (商家画像漂移)** 作为增强· **下一棒**:v0.2.1 启动前用户最终决策(本轮 docs-only 不实施代码)
>
> **背景**:B 类延后清单 5 项 + D8 = v0.2 6 子阶段已全部 docs-only 评估闭环(B1/B2/B4 已实化 + B-5/outlook/gmail/D8 docs-only)。D8 是 v0.2 启动规划 6 子阶段第 6 项,P2 6/21,本轮 docs-only 评估 3 候选方案,推荐组合方案 A + C(规则基础 + 商家画像增强)。

---

## 1. 现状摸底(2026-06-16 晚)

### 1.1 D6 已落地基础(可供 D8 复用)

| 文件 | 行数 | 内容 |
|------|------|------|
| `src/my_ai_employee/core/categorizer.py` | 142 | `categorize(counterparty, amount)` — 5 大类(DINING/TRANSPORT/SHOPPING/HOME/OTHER)+ 50 条关键词正则 + 商家表兜底,**不调 LLM** |
| `src/my_ai_employee/core/merchants.py` | 82 | `MERCHANT_TO_CATEGORY` 加载自 `tests/fixtures/merchants_500.json`(654 条去重,5 类均匀分布) |
| `src/my_ai_employee/db/transactions.py:617-692` | 906 (整文件) | `list_by_source(source, since, limit)` + `find_candidates_by_fingerprint(fingerprint, ...)` |
| `src/my_ai_employee/core/transaction_category.py` | - | `TransactionCategory(StrEnum)` 5 类 |

**D6.3 已留 D8 接入点**(`merchants.py:12-13`):
```python
D8 智能分类(LLM) B 类延后:
    - D6.3 走关键词规则 + 商家表兜底
    - D8 LLM 智能分类 v0.2 再实现
```

### 1.2 已有的"异常信号"基础设施

| 信号 | 来源 | 可复用 |
|------|------|--------|
| 单笔金额 | `Transaction.amount` (Decimal) | ✅ 直接 SQL `AVG + STDDEV` 算 σ |
| 交易时间 | `Transaction.transaction_date` (date) + `imported_at_ms` (int) | ✅ 按小时聚合 >5 笔/小时检测频率 |
| 商家 | `Transaction.counterparty` (str) | ✅ 商家画像漂移对比 `MERCHANT_TO_CATEGORY` |
| 分类 | `Transaction.category` (TransactionCategory) | ✅ 跨分类漂移(同商家历史 DINING 突然变 SHOPPING) |
| 跨源候选 | `find_candidates_by_fingerprint` | ✅ 异常:同 fingerprint 多笔 = 重复扣款疑似 |
| 状态机 | `Transaction.status` (categorized/needs_confirm/imported/...) | ✅ `needs_confirm > 30 天未确认` = 异常 |

### 1.3 月报真实生成(Spike C 6/16)

`src/my_ai_employee/agents/monthly_report.py` + `reports/v0.1-real-spike-c-s8-2026-06-16.md`:
- 单月总额 / 笔数 / 大额异常高亮(发薪 3500 + 奢侈品 1500)
- 沿 D10.4 S8.1 e2e 范本,月报文件 1039B / 43 行 / 10 占位符全替换
- **可作为 D8 异常告警的"输出通道"** — D8 检测到异常 → 写月报"异常告警"段

### 1.4 关键约束

| # | 约束 | 范本 |
|---|------|------|
| 1 | **不破坏 D6.3 5 大类分类**(categorize 函数签名不变) | D6 范本:纯函数 + 关键词规则 + 商家表兜底 |
| 2 | **不引入大依赖**(LLM 方案会调 AI,~5MB msal 类同) | D1.1 依赖体积敏感(uv lock 已 80MB+) |
| 3 | **本机优先 / 隐私保护**(LLM 调用必须用户授权) | CLAUDE.md 铁律"数据不出本机" |
| 4 | **真异常 vs 业务异常必区分**(扣款失败 ≠ 异常交易) | D4.7.3 v1.0.1 P1-1 范本:业务阻断 vs 技术失败分离 |
| 5 | **告警不打扰**(异常告警接入菜单栏,不能每笔都弹) | D9 menu_bar/notes_menu_bar_app.py 已落,异常告警可复用 |
| 6 | **3 类测试点**(SAP 范本):功能正例 / 异常边界 / 集成影响 | [[output/2026-06-05/每日技巧.md]] SAP 3 类测试点设计 |

---

## 2. 3 候选方案对比

### 方案 A:基于规则的异常检测(>3σ / >5 笔/小时)

**核心**:纯 SQL + Python 规则,**不调 LLM**,检测 3 类异常:
1. **消费金额异常**:`amount > 3σ + AVG(historical amount)`(单笔消费远超历史均值)
2. **频率异常**:`COUNT(txs WHERE transaction_date >= now() - 1h) > 5`(1 小时内 >5 笔交易,可能盗刷)
3. **重复扣款异常**:`find_candidates_by_fingerprint` 返回 >1 候选 + 状态都是 `categorized`(疑似多次扣款)

**实现要点**:
```python
# core/anomaly_detector.py 新建(估 ~250 行)
class RuleBasedAnomalyDetector:
    def __init__(self, *, transaction_store: TransactionStore, sigma_threshold: float = 3.0,
                 hourly_tx_threshold: int = 5) -> None:
        self._store = transaction_store
        self._sigma = sigma_threshold
        self._hourly = hourly_tx_threshold

    def detect_amount_anomaly(self, tx: Transaction) -> AnomalyResult | None:
        """消费金额异常检测:>3σ + 历史均值."""
        history = self._store.list_by_source(tx.source, limit=100)
        if len(history) < 30:  # 历史样本不足
            return None
        amounts = [h.amount for h in history if h.amount > 0]
        avg = sum(amounts) / len(amounts)
        std = (sum((a - avg) ** 2 for a in amounts) / len(amounts)) ** 0.5
        if tx.amount > avg + self._sigma * std:
            return AnomalyResult(kind="amount_3sigma", tx=tx, avg=avg, std=std)
        return None

    def detect_frequency_anomaly(self, source: str) -> AnomalyResult | None:
        """频率异常检测:1 小时 >5 笔."""
        now = now_ms()
        hour_ago = now - 3600 * 1000
        recent = self._store.list_by_source_since_ms(source, hour_ago, limit=100)
        if len(recent) > self._hourly:
            return AnomalyResult(kind="frequency_5tx_per_hour", count=len(recent))
        return None
```

**优点**:
- **无新依赖**(纯 SQL + Python 标准库)
- **可解释性强**:每条异常都有数学依据(σ / 频率阈值)
- **性能优异**:SQL 聚合 < 50ms(沿 D6.3 范本,InMemory sqlite 索引命中)
- **测试隔离容易**:mock `TransactionStore.list_by_source` 即可

**缺点**:
- **中等**: 阈值靠经验值(σ=3.0 / 5tx/h),用户行为差异大,可能误报
- **中等**: 冷启动问题(< 30 笔历史样本无法算 σ,需 fallback "无异常")
- **低**: 不能检测语义异常(如"星巴克消费 ¥8888" — 数学上 3σ 内,但语义异常)

**评分**:⭐⭐⭐⭐(4/5)— **推荐为基础**

---

### 方案 B:LLM 异常检测(直接调 AI 评估)

**核心**:每笔交易都调 LLM(minimax M3),输入是历史交易 + 本笔交易,输出"正常/异常 + 异常类型 + 置信度"。LLM 评估语义合理性。

**实现要点**:
```python
# ai/anomaly_detector.py 新建(估 ~300 行,沿 ai/categorizer.py 范本)
class LLMAnomalyDetector:
    def __init__(self, *, llm_client: LLMProvider, history_window: int = 30) -> None:
        self._client = llm_client
        self._history = history_window

    async def detect_async(self, tx: Transaction) -> AnomalyResult | None:
        """LLM 异常检测(异步调 AI)。"""
        history = self._store.list_by_source(tx.source, limit=self._history)
        prompt = build_anomaly_prompt(tx=tx, history=history)
        response = await self._client.complete(SYSTEM_PROMPT_ANOMALY, prompt, model=TaskType.ANOMALY)
        verdict = parse_anomaly_response(response)
        if verdict.is_anomaly:
            return AnomalyResult(kind=verdict.kind, tx=tx, reasoning=verdict.reasoning, confidence=verdict.confidence)
        return None
```

**优点**:
- **语义异常检测强**:能识别"星巴克消费 ¥8888"这种数学 σ 内但语义异常
- **可解释性**:LLM 输出 reasoning 字段,用户能看到"为什么异常"
- **复用 D4.7.2 prompts/draft.py 抗注入范本**:UNTRUSTED_DATA_BEGIN/END + json.dumps escape

**缺点**:
- **中等**: 每笔交易都调 LLM,成本高(假设月 100 笔,月 100 次 LLM call,~10 元/月)
- **中等**: 延迟高(LLM 调 ~500ms-2s),不能实时告警
- **中等**: LLM 幻觉风险(可能误报"正常"为"异常"或反之)
- **中等**: 隐私风险(交易数据送给 LLM provider,**违反** CLAUDE.md "数据不出本机" 铁律)

**评分**:⭐⭐(2/5)— 不推荐(违反"本机优先"铁律)

---

### 方案 C:商家画像漂移检测(对比历史商家画像,新商家高分)

**核心**:维护每个商家的"消费画像"(类目分布 / 平均金额 / 频率 / 时段),新交易与历史画像对比,偏离超阈值 = 异常。

**实现要点**:
```python
# core/merchant_profile.py 新建(估 ~200 行)
class MerchantProfileStore:
    """商家画像存储 + 漂移检测."""
    def __init__(self, *, transaction_store: TransactionStore) -> None:
        self._store = transaction_store

    def compute_profile(self, counterparty: str) -> MerchantProfile:
        """从历史交易算商家画像。"""
        history = self._store.find_by_counterparty(counterparty, limit=100)
        return MerchantProfile(
            counterparty=counterparty,
            category_distribution=Counter(h.category for h in history),
            avg_amount=sum(h.amount for h in history) / len(history) if history else 0,
            tx_count=len(history),
            last_seen_ms=max(h.transaction_date for h in history).timestamp() * 1000 if history else 0,
        )

    def detect_drift(self, tx: Transaction) -> AnomalyResult | None:
        """商家画像漂移检测。"""
        profile = self.compute_profile(tx.counterparty)
        if profile.tx_count < 5:
            return AnomalyResult(kind="new_merchant", tx=tx, profile=profile)
        if tx.category != profile.dominant_category():
            return AnomalyResult(kind="category_drift", tx=tx, profile=profile)
        if abs(tx.amount - profile.avg_amount) > profile.amount_std * 3:
            return AnomalyResult(kind="amount_drift", tx=tx, profile=profile)
        return None
```

**优点**:
- **个性化强**:每个商家独立画像,不是全局阈值
- **可解释性**:画像字段直接展示给用户(类目分布 / 平均金额 / 频率)
- **冷启动友好**:新商家(< 5 笔历史)显式标记"new_merchant",不报"异常"
- **纯本地**:不调 LLM,无隐私风险

**缺点**:
- **中等**: 需要新表 `merchant_profile`(alembic migration 0011)+ ORM 模型
- **中等**: 历史样本 < 5 笔时无法判断(冷启动)
- **中等**: 商家画像需要定期更新(每次新交易后异步重算)

**评分**:⭐⭐⭐⭐(4/5)— **推荐为增强**

---

## 3. 推荐方案 + 决策

### 3.1 推荐:**方案 A (规则基础) + 方案 C (商家画像增强)组合**

**推荐理由**:
1. **沿用 D6.3 纯本地 / 无 LLM 范本**:不违反"数据不出本机"铁律
2. **零依赖增量**:沿 D1.1 范本,uv lock 不变
3. **方案 A 提供全局异常**(σ / 频率 / 重复扣款),方案 C 提供个性化异常(画像漂移)
4. **冷启动友好**:方案 A 需要 30 笔历史 → fallback "无异常";方案 C 需要 5 笔历史 → 标记 "new_merchant"
5. **测试隔离容易**:沿 D6.6 P2 修复范本,纯函数 + SQL 聚合,可 mock

**实施规模预估**(v0.2.1+ 启动后):

| 任务 | 文件 | 改动 |
|------|------|------|
| 异常检测主类 | `core/anomaly_detector.py` 新建 | ~250 行(RuleBasedAnomalyDetector 3 方法) |
| 商家画像存储 | `core/merchant_profile.py` 新建 | ~200 行(MerchantProfileStore + MerchantProfile dataclass) |
| 数据库迁移 | `migrations/versions/0011_merchant_profile.py` 新建 | ~80 行(merchant_profile 表 6 列) |
| ORM 模型 | `src/my_ai_employee/db/merchant_profile.py` 新建 | ~120 行(6 列 ORM + 4 方法) |
| 月报异常告警接入 | `agents/monthly_report.py` 改 | ~30 行(append "异常告警" 段) |
| 菜单栏异常通知 | `menu_bar/app.py` 改 | ~20 行(异常时弹 rumps.notification) |
| 异常检测测试 | `tests/core/test_anomaly_detector.py` 新建 | ~300 行(12 cases: 3 类异常 + 边界 + 冷启动) |
| 商家画像测试 | `tests/core/test_merchant_profile.py` 新建 | ~200 行(8 cases:画像算 + 漂移检测 + 冷启动) |
| 端到端 | `tests/e2e/test_v0_2_d8_anomaly_e2e.py` 新建 | ~150 行(S12 异常检测端到端) |
| **预计 commits** | - | **4-6 commits**(2 feat AnomalyDetector + MerchantProfile + 1 月报接入 + 1 menu_bar + 1 spike + 1 docs 收口) |
| 测试数变化 | - | +25-30 tests |
| 依赖增量 | - | 0(纯本地规则 + SQL) |

### 3.2 关键决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | **方案 A + C 组合,不选 B (LLM)** | 违反 CLAUDE.md "数据不出本机"铁律 / 每笔交易送 LLM 成本高 / 隐私风险 |
| 2 | **方案 A σ=3.0 / 5tx/h 阈值硬编码** | 沿 D6.3 关键词表硬编码范本,测试断言简单;后续如需个性化可移到配置文件 |
| 3 | **方案 C 冷启动 < 5 笔 → "new_merchant" 标记** | 不报"异常",避免冷启动误报(沿 D6.6 范本) |
| 4 | **月报异常告警接入**(D10.2 复用) | 沿 [[d10.5.2-tag-anchored]] 范本:已实化能力复用,新增能力附加 |
| 5 | **菜单栏异常通知接入**(rumps.notification) | 沿 D9.6 ClipboardCaptureService 业务层 3 入口范本,只接入"已确认"异常,不弹每笔 |
| 6 | **不引入 LLM / 不引入新依赖** | 沿 D1.1 依赖体积敏感 + 沿 "数据不出本机" 铁律 |
| 7 | **docs-only 不实施代码** | OAuth 类决策链范本:docs-only 锁评估 → 用户决策 → 实施 |

### 3.3 不实施代码(本轮 docs-only 锁定)

**本轮不做**:
- 不新建 `core/anomaly_detector.py`
- 不新建 `core/merchant_profile.py`
- 不建 alembic migration 0011
- 不改 `agents/monthly_report.py`
- 不改 `menu_bar/app.py`
- 不改 `tests/`

**留给 v0.2.1+ 启动前用户决策**:
- 是否采纳方案 A + C 组合
- 何时启动 D8 实施 commits(估 4-6 commits,1-2 工作日)
- 异常告警是否同步接入 mobile / web dashboard(Phase 2,延后)

---

## 4. 复用要点速查表(D8 v0.2.1+ 启动后立即可用)

| 任务 | 复用模块 | 关键签名 | 文件 |
|------|----------|----------|------|
| 商家 → 分类 | `MERCHANT_TO_CATEGORY` | `dict[str, TransactionCategory]` | `src/my_ai_employee/core/merchants.py:76` |
| `categorize` 纯函数 | `categorize(counterparty, amount)` | 返回 5 类选 1 | `src/my_ai_employee/core/categorizer.py:103-137` |
| `Transaction` ORM 16 列 | `Transaction` 数据类 | amount / counterparty / category / transaction_date 等 | `src/my_ai_employee/db/transactions.py` |
| `list_by_source` 查询 | `list_by_source(source, since, limit)` | 按 source + 时间窗 | `src/my_ai_employee/db/transactions.py:617-648` |
| `find_candidates_by_fingerprint` | L2 跨源候选查询 | `find_candidates_by_fingerprint(fingerprint, limit=5)` | `src/my_ai_employee/db/transactions.py:650-692` |
| 月报真实生成 | `monthly_report.py` 模板 | 1039B / 43 行 / 10 占位符 | `src/my_ai_employee/agents/monthly_report.py` |
| 菜单栏通知 | `rumps.notification(title, subtitle, message)` | 沿 D9 范本 | `src/my_ai_employee/menu_bar/app.py` |
| D4.7.3 v1.0.1 业务阻断 vs 技术失败 | 异常检测双入口 | `record_anomaly_and_emit` vs `record_check_failure_and_emit` | 沿 D4.7.3 v1.0.1 P1-1 范本 |
| D6.6 P2 修复事务回滚 | `with self._store.session() as s:` contextmanager | 异常自动 rollback | 沿 D6.6 P2 范本 |
| 3 类测试点设计(功能/异常/集成) | SAP 范本 | 沿 [[output/2026-06-05/每日技巧.md]] | `output/2026-06-05/每日技巧.md` |
| 月报真实 spike 范本 | Spike C 6/16 | tmp DB + alembic + 3 笔 + exit 0 | `reports/v0.1-real-spike-c-s8-2026-06-16.md` |
| S8 端到端范本 | D10.4 S8.1 e2e | tmp DB 隔离 + monthly_report.py generate | `tests/e2e/test_v0_2_s8_monthly_report_e2e.py` |

---

## 5. 关键风险 + 缓解

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | σ=3.0 / 5tx/h 阈值硬编码 → 不同用户行为差异大 | 🟡 中 | 阈值放到 config 文件,提供 `update_threshold(sigma=...)` helper;D6.3 关键词表也是硬编码,可接受 |
| 2 | 冷启动(< 30 笔 / < 5 笔)无法检测 | 🟡 中 | 显式 fallback "样本不足,无异常",日志记录;沿 D6.6 P2 范本 |
| 3 | 商家画像每次新交易后重算性能 | 🟢 低 | 异步任务,本地计算 < 50ms;沿 D9.6 降级路径范本,性能不是阻断 |
| 4 | 月报异常告警段被误读为"系统报警" | 🟡 中 | 异常告警段开头加 "⚠️ 异常告警" emoji + 注释说明非阻塞;沿 D10.2 范本 |
| 5 | 菜单栏异常通知打扰用户 | 🟡 中 | 只在"已确认异常"(金额 > 1000 + σ 命中)弹通知,低金额不弹 |
| 6 | 商家画像 schema 变化破坏旧数据 | 🟢 低 | alembic migration 0011 新建表,不动旧表 |

---

## 6. 6 关键教训

1. **3 候选方案必带评分 + 推荐组合**:本轮推荐方案 A + C 组合(规则基础 + 商家画像增强),不是单方案。教训:B 类 docs-only 评估多方案时,推荐"组合"比"单选"更有价值,各方案互补
2. **"数据不出本机"铁律必显式标注**:方案 B (LLM) 评分 ⭐⭐ 的关键理由是"违反 CLAUDE.md 数据不出本机铁律 + 隐私风险",这是用户决策的最高权重。教训:docs-only 评估必显式标注与"铁律"的冲突,即使技术可行
3. **冷启动问题必显式标注**:方案 A 需 30 笔历史 / 方案 C 需 5 笔历史,docs 必显式标注 fallback 行为(返回 None / "new_merchant")。教训:沿 D6.6 P2 范本,任何"基于历史"的检测都必须有冷启动策略
4. **复用 D10.2 月报 + D9.6 menu_bar 已实化能力**:D8 不新建菜单栏 + 月报模块,直接复用 + 接入异常告警段 + 异常通知。教训:沿 [[d10.5.2-tag-anchored]] 范本,新能力优先复用已实化能力
5. **3 类测试点设计**:本轮预估 25-30 tests,按 SAP 范本分 3 类(功能正例 / 异常边界 / 集成影响)。教训:任何新功能必带 3 类测试点,功能正例覆盖 happy path,异常边界覆盖冷启动 + 阈值,集成影响覆盖月报 + menu_bar 端到端
6. **D8 docs-only 评估收口 = v0.2 6 子阶段评估全闭环**:B1/B2/B4 已实化 + B-5/outlook/gmail/D8 docs-only 评估 = 6 子阶段 docs-only 评估闭环(2 commits `b172dae` + `31f8ed2` + D8 docs-only commit)。教训:B 类延后清单多项目评估可同轮分多 commit 落地,避免"1 大 commit 混多项目"

---

## 7. 完成定义(D8 docs-only 评估 Done)

- [x] 3 候选方案对比(规则基础 / LLM 异常 / 商家画像漂移)
- [x] 推荐方案 A + C 组合(规则基础 + 商家画像增强)
- [x] 关键决策 7 条(选 A+C / 不选 B / 阈值硬编码 / 冷启动 fallback / 月报接入 / 菜单栏接入 / 不引入 LLM)
- [x] 复用要点速查表 12 行
- [x] 风险缓解 Checklist 6 项
- [x] 6 关键教训
- [ ] v0.2.1+ 启动前用户最终决策(留 B 类决策延后范围)

---

## 8. 关联

- **承接**:v0.2-launch-plan.md:74 D8 段 + v0.2-substage-mapping.md:267-293 D8 详细任务分解
- **沿用范本**:[[d6-wechat-bill-launch]] + [[d6.6-fixes-launch]] + [[d10.5.2-tag-anchored]] + [[b-class-deferral-2026-06-09]] + [[b4-closure-2026-06-16]]
- **v0.2 6 子阶段 docs-only 评估全闭环**:
  - B1 ✅ 6/16 落地(b97ae55 + 268e181 + 64a9adb 整条)
  - B2 ✅ 6/16 落地(31cbd05 + 80e087c + 3a26062 整条)
  - B4 ✅ 6/16 晚实化(0c6472f → 2bb77a0 → e54c697 共 11 commits 收口链)
  - B-5 📝 docs-only(`b172dae` 推荐方案 B Quartz,见 [b-5-pynput-evaluation.md](b-5-pynput-evaluation.md))
  - outlook/gmail 📝 docs-only(`31f8ed2` 推荐方案 A 工厂模式,见 [outlook-gmail-evaluation.md](outlook-gmail-evaluation.md))
  - **D8 📝 docs-only(本轮)** — 推荐方案 A + C 组合,v0.2.1+ 启动前用户决策
- **下一棒**:D8 v0.2.1+ 启动前用户决策(无 B 类触发,本轮 docs-only 锁评估)