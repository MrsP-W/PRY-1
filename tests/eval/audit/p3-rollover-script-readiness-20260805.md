# P3 epoch rollover 脚本只读审计(D6.18.2 docs-only,2026-08-05)

> **范围声明(优先于正文)**:本文是 `scripts/p3_rollover_epoch.py` + `tests/scripts/test_p3_rollover_epoch.py` 的**只读审计**,**不修改脚本、不集成、不启用**;WIP 中的两个文件原样保留,仅为 v1.1-A readiness 候选门槛 #8 提供 docs-only 评估。
> **承接**:`docs/v1.1-a-launch-plan-2026-08-05.md` 阶段 A2 + `docs/v1.1-a-readiness-2026-08-05.md` 候选门槛 #8。
> **审计对象**(WIP,未集成):
> * `scripts/p3_rollover_epoch.py`(93 行)
> * `tests/scripts/test_p3_rollover_epoch.py`(63 行,3 个测试)

---

## 1. 脚本设计概述(只读观察)

### 1.1 主要入口与契约

* `rollover_once(*, app_support_dir=None)`:核心入口,返回结构化执行摘要
* `main()`:CLI 入口(line 86,具体内容未审计到尾部)
* 内部依赖:`scripts.p3_burn_in_report`(burn_in)+ `scripts.verify_p3_first_daily` + `scripts.watch_p3_ops.watch_once`

### 1.2 安全门控(关键设计)

* **不覆盖归档**:归档目标若已存在则停止(`archive_target_exists`),绝不覆盖
* **不强制**:模块顶部 docstring 明确「不接受 CLI 强制开关」
* **入口前置校验**:先调 `verify_first_daily`,仅当 `result` 处于可推进态时进入归档
* **三态归档结果**:`archive_target_exists` / `source_missing` / `rolled_over`
* **失败回滚保护**:`start_burn_in` 异常时归档仍保留(注释明确「retained archive is safer than overwrite」)

### 1.3 脱敏与目录权限

* 归档目录权限 `mode=0o700`(仅所有者可读写执行)
* 使用 `os.replace`(原子替换,非复制+删除)
* 返回 dict 中包含 `archive_path` / `error` 等结构化字段(便于日志审计,不直接打印敏感内容)

---

## 2. 测试覆盖评估(只读)

| 测试函数 | 覆盖场景 | 状态 |
|---------|---------|------|
| `test_rollover_stops_when_archive_target_exists` | 归档目标已存在,拒绝覆盖 | covered |
| `test_rollover_moves_epoch_and_starts_new_day0` | 正常归档 + 新 Day0 启动 | covered |
| `test_rollover_does_not_start_before_gate` | 入口前置校验拦截 | covered |

### 2.1 覆盖维度分析

* **正向路径**:归档 + 启动新 Day0(由 line 32 测试覆盖)
* **拒绝路径**:归档目标已存在(line 16)+ gate 未到(line 54)
* **失败路径**:`start_burn_in` 异常(注释明确标注「not covered - retained archive is safer than overwrite」);有意设计为不覆盖,测试跳过

### 2.2 缺口与建议

* **缺口 1**:`watch_once` 返回值未被断言(line 49 测试只 mock 不验证);若 `watch_once` 异常是否进入归档流未覆盖
* **缺口 2**:`burn-in-archive` 父目录创建失败(line 65 `mkdir`)未测试
* **缺口 3**:`verify_first_daily` 返回 `invalid_epoch` 分支(line 41)未单独测试(隐含在主流程)
* **缺口 4**:文件权限 `0o700` 实际生效未测试

---

## 3. 与 v1.1-A readiness 的接口关系

### 3.1 7d/30d 时间窗与 epoch rollover 的绑定

* v1.1-A 7d 入口:`2026-08-06T07:04:45Z`(基于当前 P3 Day0=`2026-07-30T07:04:45Z`)
* v1.1-A 30d 入口:`2026-08-29T05:34:24Z`(若 Day0 未重置)
* 若本脚本被触发并完成 epoch rollover,**Day0 重置**,7d/30d 窗口随之重置
* 当前 v1.1-A readiness 报告(`1a7dec1` ready_to_merge)假设 Day0 未重置;若发生 rollover,需重新核验 4 必须门槛

### 3.2 与 readiness 候选门槛 #8 的关系

* 候选门槛 #8 要求:P3 epoch rollover 脚本 docs-only 只读审计 + 与 v1.1-A 7d/30d 时间窗绑定关系文档化
* 本审计完成 docs-only 端设计概述、测试覆盖评估、接口绑定说明
* 集成条件:仍需用户在独立 worktree 完成实施后单独批准 cherry-pick

---

## 4. 隐私边界评估

### 4.1 现有保护

* **目录权限**:`mode=0o700`(仅所有者)
* **不覆盖语义**:`archive_target_exists` 拒绝重写
* **结构化返回**:dict 字段而非裸字符串日志
* **路径相对化**:返回 `archive_path` 用 `str(archive)` 而非绝对展开

### 4.2 风险点

* **R1**:`error` 字段直接暴露异常类型名(`type(exc).__name__`),可能泄露内部库结构(撞坑 #104+ 风险)
* **R2**:`watch_once` 返回值(可能含 attention 详情)直接进 payload,需审计是否会泄露客户名/凭证号
* **R3**:`epoch_started_at` 解析失败回 `invalid_epoch`,但不区分原因(解析异常 vs 字段缺失 vs 非字符串)

### 4.3 建议(非本轮实施)

* 后续 P2 实施时:`error` 字段白名单映射(已知异常类型映射为简短标识)
* `watch_once` payload 接入前脱敏断言
* `invalid_epoch` 区分 `parse_error` / `missing_field` / `wrong_type`

---

## 5. 与 Feature Flag 接口解冻的协同(阶段 D)

### 5.1 边界

* 本脚本不读写 `flags` 表、不读 `ENABLE_*` 环境变量、不修改 v1.1-Feature-Flag 接口契约
* 在 v1.1-A 解冻前,本脚本仍可被手动触发(若归档目录权限保护足够)
* 解冻后,本脚本可能成为「Feature Flag 触发 epoch rollover」的可选调用点(候选,未决策)

### 5.2 协同接口(尚未启用)

* 当前:零调用点
* 解冻后候选:`p3_rollover_epoch` 作为 Feature Flag 解冻条件 #5(健康度阈值)的可选消费方
* 决策:在阶段 D 用户拍板后另行评估,不在本审计范围

---

## 6. 集成前的前置清单(待用户批准)

1. **测试覆盖补全**(用户决定):R1/R2/R3 缺口是否在集成前补 test
2. **隐私边界补强**:R1 异常类型白名单;R2 watch payload 脱敏
3. **CLI 入口审计**:`main()` 函数完整审计(本审计未触及 line 86 之后)
4. **集成顺序**:与候选链 `0bb7fba → 1a7dec1 → 6272eb8` 无依赖,但与 `scripts/` 现有运行时同目录,需评估合并冲突
5. **回归保护**:集成后 `tests/scripts/test_p3_rollover_epoch.py` 与现有 pytest 基线 `129 passed` 是否相互独立
6. **用户单独批准**:cherry-pick + push 均需用户单独授权

---

## 7. 审计结论

* **设计成熟度**:中等(11 个核心契约点全部覆盖,安全门控到位)
* **测试覆盖**:正向 + 拒绝路径已覆盖;失败路径有意未覆盖(注释明确)
* **集成阻断**:
  * R1 异常类型白名单(可选补强)
  * R2 watch payload 脱敏(可选补强)
  * R3 invalid_epoch 细分(可选补强)
* **集成就绪**:docs-only 层面 ready_to_merge;实施层面仍需用户单独批准
* **集成后影响**:`tests/scripts/` 范围扩展;与 `tests/eval/test_eval_fixtures_schema.py`(`129 passed` 基线)相互独立;不引入跨模块依赖

---

## 8. 验收(本文档)

* `markdownlint tests/eval/audit/p3-rollover-script-readiness-20260805.md`:0 issues
* `python -c "import yaml; yaml.safe_load(open('docs/agent-team/tasks/TASK-20260805-005-d6182-p3-rollover-script-audit.yaml'))"`:解析通过
* `git diff --check`:通过
* 文件白名单:3 文件全部为 docs-only(审计报告 + 任务包 + `MODIFICATION-LOG.md`)
* 不修改 `scripts/p3_rollover_epoch.py`、`tests/scripts/test_p3_rollover_epoch.py`、13 项用户未跟踪 WIP
* 不集成到 main;不 push;不启用脚本

---

## 9. 下一棒

* 用户决定是否集成本审计报告
* 用户决定是否启动 R1/R2/R3 补强任务(可选)
* 用户决定是否集成 `scripts/p3_rollover_epoch.py` 到 main(独立 cherry-pick,不在 docs-only 范围)
* 持续观察 P3 7d 时间窗(8/6 07:04 UTC)与 attention 状态
* 等待 GPT 额度恢复(预计 8/8)以启用 SOL 阶段 C 审核
