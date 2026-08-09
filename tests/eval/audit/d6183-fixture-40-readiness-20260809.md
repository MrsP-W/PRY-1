# TASK-20260809-001 fixture 40 条候选门槛 #5 自评(docs-only,2026-08-09 19:18 CST / 11:18 UTC 执行)

> **范围声明(优先于正文)**:本文是 v1.1-A readiness **候选门槛 #5**(30+ 样本 2 轮扩)的自评,**只读核验**当前 main `c7c9037` 已落地的 40 条 `tests/eval/fixtures/` 与 `tests/eval/test_eval_fixtures_schema.py` 行为,**不修改 fixture、schema test、src/、scripts/、ops/、plugins/、.cursor/、ENABLE_*、LaunchAgent**;**不重复 cherry-pick 源候选** `0bb7fba`/`1a7dec1`/`6272eb8`/`f2335d4`/`a1953e5`/`b8af81d`/`72e4091`(这些原始哈希均不是 `c7c9037` 的祖先,成果经对应整合提交落地,见 §1.3);**不发起 push/merge/tag**;**不发起 v1.1-A 解锁**;**不修改 13 项用户未跟踪 WIP**。
> **承接**:`docs/v1.1-a-readiness-2026-08-05.md` 候选门槛 #5 + `docs/eval-fixture-coverage-30-to-40-plan.md` §3 + `tests/eval/audit/p3-7d-window-watch-20260808.md` 收官纠偏的 4 必须门槛规范计数。
> **编号纠偏**:现有报告文件名、任务 YAML 文件名与 worktree 名中的 `d6183` 仅为未提交工作路径标识,不表示本任务阶段编号;既有 **D6.18.3** 属于 v1.0 tag 预审 `57480cb`。
> **实测环境**:独立 worktree `/private/tmp/my-ai-employee-d6183-fixture-readiness-sol-20260809`(基线 `c7c9037`,与本地 `main` 一致;`git rev-list --left-right --count origin/main...HEAD` 实测 left=0、right=0,即 **main = origin/main = `c7c9037`,无 ahead/behind**);pytest/ruff 通过主项目已认证 `.venv`(`/Users/wei/Documents/DesktopOrganizer/我的AI员工/.venv/bin/python`)调用;**未安装、未修改、未联网**;**未改动 `pyproject.toml` 的覆盖率阈值**。
> **基线来源**:`299aa79`「test(eval): SOL 审核落地 30→35 fixture 扩样轮 1」(commit message 标注 SOL 审核)+ `c7c9037`「test(eval): SOL 审核落地 35→40 fixture 扩样轮 2」(commit message 标注 SOL 审核);**两 commit 的 commit message 仅可作为「已声明 SOL 审核」的元数据证据**,fixture 内容本身不在本任务变更范围。
> **最终结论**:候选门槛 #5 = **PASS**(40 条落地 + 169 passed + ruff 对受支持 Python 文件 0 issue + 4 项自动 guard 全过);**但 #5 仅是候选门槛,不修改 4 必须门槛**;v1.1-A 仍 **NOT_UNLOCKED**(规范计数 **2 PASS / 2 FAIL**:#1 P3 7d FAIL,#2 P3 30d FAIL,#3 30-fixture PASS,#4 5 docs-only PASS);P3 #1/#2 仍受 `com.myaiemployee.agent` `needs_human` 与持续 attention 阻断,与本任务无关。
> **SOL 状态**:首轮终审 = **FAIL**(8 个 findings);本次为集中修订,等待 SOL 复审,**不得声称 PASS**。`status=ready_to_merge` 仅表示本地质量门完成后的候选态,仍受 SOL 提交前终审硬门约束(详见 §12);TERRA/LUNA 待命;只有 SOL 复审 PASS 后才允许由 codex 在任务分支提交。

---

## 1. 基线与来源提交(只读核验)

### 1.1 当前 HEAD 与工作树状态实测

* `git rev-parse HEAD` → `c7c9037024ee8b77c3636e1627d3950ed2d42006`
* `git rev-parse main` → `c7c9037`
* `git rev-list --left-right --count origin/main...HEAD` → left=0、right=0(**main = origin/main = c7c9037,无 ahead/behind**;无 ahead origin/main 2 的事实)
* **实施前基线 `git status --short`** → 无改动、无未暂存、无未跟踪(本任务开始前的干净状态)
* **当前最终工作树 `git status --porcelain=v1 -uall`** → 精确 3 文件白名单:` M MODIFICATION-LOG.md`、`?? docs/agent-team/tasks/TASK-20260809-001-d6183-fixture-readiness.yaml`、`?? tests/eval/audit/d6183-fixture-40-readiness-20260809.md`;**本任务最终工作树不干净,仅限制在 3 文件白名单内**。
* `git log --oneline -1` → `c7c9037 test(eval): SOL 审核落地 35→40 fixture 扩样轮 2`

### 1.2 来源提交链(实测)

| commit | 父提交 | commit message | 文件变更(实测 `git show --stat`) |
|--------|--------|----------------|----------------------------------|
| `299aa79` | `edf506c` | test(eval): SOL 审核落地 30→35 fixture 扩样轮 1 | 5 files changed, 91 insertions(+) |
| `c7c9037` | `299aa79` | test(eval): SOL 审核落地 35→40 fixture 扩样轮 2 | 5 files changed, 90 insertions(+) |

* 轮 1(`299aa79`)新增:`email_classify/014_english_invoice_reminder_with_attachment.json`、`email_classify/015_re_fw_three_layer_meeting_reschedule.json`、`email_draft/010_english_vendor_delay_apology.json`、`email_draft/011_re_invoice_query_with_attachment_note.json`、`sap_troubleshoot/009_m8_113_account_error_short_dump.json`(5 条)。
* 轮 2(`c7c9037`)新增:`email_classify/016_urgent_ceo_payment_phishing.json`、`email_classify/017_self_reported_pii.json`、`email_draft/012_polite_reconciliation_reminder.json`、`sap_troubleshoot/010_fb60_fbl5n_transaction_mismatch.json`、`sap_troubleshoot/011_authorization_header_missing.json`(5 条)。
* 两 commit 的 `git show --stat` 与 commit message 标注的「SOL 审核」一致;**本任务不重复验证 SOL 审核行为本身**,仅确认 commit message 元数据。

### 1.3 源候选与 main 整合提交映射(实测祖先关系)

| 源候选(不重复 cherry-pick) | 对应 main 整合提交 | `c7c9037` 祖先关系 |
|--------------------------|------------------|--------------------|
| `0bb7fba` | `a7c376a` | 源候选否;整合提交是 |
| `1a7dec1` | `ea54d60` | 源候选否;整合提交是 |
| `6272eb8` | `cc56e93` | 源候选否;整合提交是 |
| `f2335d4` | `63d49cf` | 源候选否;整合提交是 |
| `a1953e5` | `1901dfe`(另 `e529f96` 冲突收口) | 源候选否;两个整合/收口提交均是 |
| `b8af81d` | `67611cb` | 源候选否;整合提交是 |
| `72e4091` | `0657607` | 源候选否;整合提交是 |

* 祖先关系通过 `git merge-base --is-ancestor <hash> c7c9037` 实测:7 个源候选均 exit=1(不是祖先);7 个对应整合提交及 `e529f96` 均 exit=0(是祖先)。
* 因此准确口径是:**不重复 cherry-pick 源候选;工作成果经上表对应整合提交落地 main**。不得把源候选本身写成已 commit main。

---

## 2. fixture 总数与 suite 分布(实测)

### 2.1 命令实测

* `ls tests/eval/fixtures/email_classify/ | wc -l` → `17`
* `ls tests/eval/fixtures/email_draft/ | wc -l` → `12`
* `ls tests/eval/fixtures/sap_troubleshoot/ | wc -l` → `11`
* 三者求和 → `40`
* **精确断言 A**:`/Users/wei/Documents/DesktopOrganizer/我的AI员工/.venv/bin/python -c "from pathlib import Path; root=Path('tests/eval/fixtures'); expected={'email_classify':17,'email_draft':12,'sap_troubleshoot':11}; actual={suite:len(list((root/suite).glob('*.json'))) for suite in expected}; total=len(list(root.rglob('*.json'))); assert actual==expected and total==40,(actual,total); print(f'fixture_count={total}; suite_distribution={actual}')"` → exit=0,`fixture_count=40; suite_distribution={'email_classify': 17, 'email_draft': 12, 'sap_troubleshoot': 11}`。

### 2.2 suite 分布表

| suite | 数量 | 预期 | 实测 | 偏差 |
|-------|------|------|------|------|
| `email_classify` | 17 | 17 | 17 | 0 |
| `email_draft` | 12 | 12 | 12 | 0 |
| `sap_troubleshoot` | 11 | 11 | 11 | 0 |
| **合计** | **40** | **40** | **40** | **0** |

* 预期 = 任务包描述(17/12/11);实测 = `ls | wc -l` 命令输出;**偏差 0**,完全一致。
* fixture 数量本身已远超原门槛 #3 的 30 条阈值,**也满足候选门槛 #5 的「40 条」描述**;但门槛 #3 已 PASS(30 条),门槛 #5 是「扩样轮次」维度的候选,不替代门槛 #3。

### 2.3 fixture 列表(实测 `ls` 输出,逐条保留以备审计)

* `email_classify/`:001_todo_reconcile、002_system_sender_spam、003_meeting_followup、004_meeting_reschedule_proposal、005_newsletter_promo、006_invoice_payment_request、007_urgent_phishing、008_system_metrics_digest、009_calendar_invite、010_action_approval、011_receipt_record、012_password_reset_phishing、013_status_digest、014_english_invoice_reminder_with_attachment、015_re_fw_three_layer_meeting_reschedule、016_urgent_ceo_payment_phishing、017_self_reported_pii。
* `email_draft/`:001_meeting_confirm、002_apology_late_reply、003_spam_should_be_blocked、004_invoice_query_polite、005_vendor_schedule、006_sensitive_payment_request、007_meeting_reschedule、008_information_request、009_followup_reminder、010_english_vendor_delay_apology、011_re_invoice_query_with_attachment_note、012_polite_reconciliation_reminder。
* `sap_troubleshoot/`:001_fb01_auth、002_fi12_bank_change、003_fb60_posting_block、004_tax_code_missing、005_period_closed、006_cost_center_invalid、007_duplicate_invoice、008_payment_block、009_m8_113_account_error_short_dump、010_fb60_fbl5n_transaction_mismatch、011_authorization_header_missing。

---

## 3. pytest 实测(169 passed;首次 exit=1 因覆盖率阈值,非断言失败)

### 3.1 首次命令(任务包原文,无 `--no-cov`)

* `cd /private/tmp/my-ai-employee-d6183-fixture-readiness-sol-20260809`
* `/Users/wei/Documents/DesktopOrganizer/我的AI员工/.venv/bin/python -m pytest tests/eval/test_eval_fixtures_schema.py -q`
* **实测退出码 = 1**(非 0)
* **原因**:工作区 `pyproject.toml` 的 `[tool.pytest.ini_options]` 含 `addopts = [..., "--cov=my_ai_employee", "--cov-report=term-missing"]`,且 `[tool.coverage.report]` 设 `fail_under=80`;本次只跑单一契约测试,`my_ai_employee` 包未被导入,覆盖率收集为空 → 触发 `Coverage failure: total of 0.0 is less than fail-under=80.0`,最终 pytest 进程退出码 = 1。
* 末段实测输出:
  ```
  WARNING: Failed to generate report: No data to report.
  ERROR: Coverage failure: total of 0.0 is less than fail-under=80.0
  FAIL Required test coverage of 80.0% not reached. Total coverage: 0.00%
  169 passed in 0.12s
  ```
* **重要解读**:**169 passed,0 failed/error**;exit=1 的根因是覆盖率阈值,不是 fixture/schema 断言失败。本节**如实记录 exit=1 与覆盖率原因**,**不掩饰、不改写为「全绿」**;**未修改 `pyproject.toml` 的覆盖率配置**(遵守红线),也未修改 `addopts`。

### 3.2 目标验收命令(本任务实际采用)

为避免覆盖率阈值干扰单一契约测试的可读性,本任务采用 `.venv/bin/python -m pytest tests/eval/test_eval_fixtures_schema.py -q --no-cov` 作为目标验收门(仅屏蔽覆盖率噪声,不屏蔽任何断言)。

* **实测退出码 = 0**
* 末段实测输出:
  ```
  ........................................................................ [ 42%]
  ........................................................................ [ 85%]
  .........................                                                [100%]
  169 passed in 0.07s
  ```
* `passed = 169`、failed = 0、error = 0、skipped = 0;warning 摘要未出现。
* `--no-cov` 是 pytest-cov 的标准参数,等价于「本次运行不收集覆盖率」;**不修改项目长期覆盖率策略**(未动 `pyproject.toml`),仅屏蔽本次单一契约测试的覆盖率检查,符合「先验证行为,再考虑覆盖率」的最小风险路径。

### 3.3 169 passed 拆分(按 schema test 文件定义)

| 测试函数 | 参数化 | 用例数 |
|---------|--------|--------|
| `test_eval_fixture_schema` | `_fixture_paths()`(40 fixture) | 40 |
| `test_eval_fixture_id_matches_suite` | `_fixture_paths()`(40 fixture) | 40 |
| `test_eval_fixture_emails_use_reserved_domains` | `_fixture_paths()`(40 fixture) | 40 |
| `test_eval_fixture_strings_have_no_long_digit_sequences` | `_fixture_paths()`(40 fixture) | 40 |
| `test_reserved_email_domain_guard` | 5 例(`example.com` / `mail.example.org` / `partner.example.net` / `company.example.com.attacker.test` / `company.com`) | 5 |
| `test_long_digit_sequence_guard` | 3 例(`SAP document 19000000001` / `invoice INV-2026-07-1234` / `split number 12345-678901`) | 3 |
| `test_eval_fixture_count_floor` | 无参数化 | 1 |
| **合计** | — | **169** |

* 169 = 40×4 + 5 + 3 + 1 = 160 + 8 + 1 = 169,与实测一致。
* 较之前 8/3 readiness 文档记录的「129 passed」增加 40 例,正好对应 **30→40 新增 10 条 fixture × 4 类参数化测试 = 增加 40 个测试用例**;旧 129 = 30×4 + 5+3+1,新 169 = 40×4 + 5+3+1;**129→169 的增量可解释,无未预期新增**。
* 结论:**169 passed,0 failed/error**,候选门槛 #5 自评的「schema 与 guard 维度」全部 PASS。

---

## 4. ruff 实测(受支持 Python 文件 0 issue,exit=0)

### 4.1 执行命令

* `cd /private/tmp/my-ai-employee-d6183-fixture-readiness-sol-20260809`
* `/Users/wei/Documents/DesktopOrganizer/我的AI员工/.venv/bin/python -m ruff check tests/eval`

### 4.2 实际输出

```
All checks passed!
```

* **实测退出码 = 0**
* 范围:`tests/eval` 下 **ruff 支持的 Python 文件**;本轮实际受检 Python 对象是 `tests/eval/test_eval_fixtures_schema.py`。ruff 不验证 Markdown 或 JSON 内容。
* Markdown 由 `markdownlint-cli2` 验证;fixture JSON 由 pytest schema/guard 测试解析与断言。
* 结论:**受支持 Python 文件 ruff 0 issue,exit=0**,候选门槛 #5 自评的 Python lint 维度 PASS。

---

## 5. 4 项自动 guard 证据与边界(逐条映射)

### 5.1 4 类 guard 与对应测试函数

| guard 类别 | 实现位置 | 测试函数 | 状态 |
|-----------|---------|---------|------|
| **隐私(desensitized=True)** | `test_eval_fixtures_schema.py` `REQUIRED` 集合 + `test_eval_fixture_schema` 内 `assert data["desensitized"] is True` | `test_eval_fixture_schema` | 实测 40 fixture 全过 |
| **保留域(reserved email domains)** | `RESERVED_EMAIL_DOMAINS` 集合 + `EMAIL_PATTERN` 正则 + `test_eval_fixture_emails_use_reserved_domains` + 单元 guard `test_reserved_email_domain_guard` | `test_eval_fixture_emails_use_reserved_domains`(40 参数化)+ `test_reserved_email_domain_guard`(5 参数化) | 实测 40 + 5 全过 |
| **长数字(11+ 位连续数字)** | `LONG_DIGIT_SEQUENCE = re.compile(r"(?<!\d)\d{11,}(?!\d)")` + `test_eval_fixture_strings_have_no_long_digit_sequences` + 单元 guard `test_long_digit_sequence_guard` | `test_eval_fixture_strings_have_no_long_digit_sequences`(40 参数化)+ `test_long_digit_sequence_guard`(3 参数化) | 实测 40 + 3 全过 |
| **ID suite 前缀** | `test_eval_fixture_id_matches_suite` 内 `expected_prefix = f"{data['suite']}_"` + `assert data["id"].startswith(expected_prefix)` | `test_eval_fixture_id_matches_suite`(40 参数化) | 实测 40 fixture 全过 |

### 5.2 单元 guard 的关键边界覆盖

* `test_reserved_email_domain_guard` 5 例覆盖了:`example.com`(精确匹配)/ `mail.example.org`(子域)/ `partner.example.net`(子域)/ `company.example.com.attacker.test`(尾段伪装,应拒)/ `company.com`(非保留域,应拒)。
* `test_long_digit_sequence_guard` 3 例覆盖了:`SAP document 19000000001`(11 位连续,应命中)/ `invoice INV-2026-07-1234`(分散数字,应不命中)/ `split number 12345-678901`(短串组合,应不命中)。
* 这两类单元 guard 在 `b019043`(eval privacy guard commit)+ `056efaa`(eval fixture id guard commit)提交时已确立;`299aa79`/`c7c9037` 引入的新 fixture 继承同一套 guard,**未引入新 guard、未绕过旧 guard**。

### 5.3 4 项自动 guard 总判定与证据边界

* 4 类 guard 在 `test_eval_fixture_schema`(隐私)+ `test_eval_fixture_emails_use_reserved_domains`(保留域)+ `test_eval_fixture_strings_have_no_long_digit_sequences`(长数字)+ `test_eval_fixture_id_matches_suite`(ID suite 前缀)中均通过,**169 passed 中已包含全部 40 fixture × 4 guard = 160 用例全过**。
* 自动证据仅证明:**`desensitized` 标志为 `true`、邮箱使用保留域、字符串无 11+ 位连续数字、fixture ID 具有 suite 前缀**。
* 上述自动证据**不等价于通用 PII、账号、角色或其他敏感类型扫描**;未被这 4 项规则覆盖的敏感类型仍依赖人工审阅。
* 结论:**4 项自动 guard 维度 PASS**;不外推为通用隐私扫描 PASS。

---

## 6. 候选门槛 #5 判定

### 6.1 候选门槛 #5 来源与本轮自评口径

* `docs/v1.1-a-readiness-2026-08-05.md` 的候选 #5 **只定义「30+ 样本 2 轮扩」**,没有给出本报告的 9 项判定矩阵。
* `docs/eval-fixture-coverage-30-to-40-plan.md` §3 将复核阶段定义为「docs-only 跑 readiness #5 候选门槛自评」,状态门槛为「≥40 条全部通过 guards」;同文 §2 给出 30→40、两轮各 5 条及目标分布 17/12/11。
* 本报告在上述 coverage plan §3 基础上附加精确数量/分布断言、pytest、ruff、4 项自动 guard 与来源提交元数据核验,形成下方 **本轮自评 9 项口径**。**9/9 不是 readiness 原文**,仅是本报告的可审计判定矩阵。

### 6.2 本轮自评判定矩阵(附加审计口径)

| 维度 | 期望 | 实测 | 判定 |
|------|------|------|------|
| fixture 总数 = 40 | 40 | 40 | **PASS** |
| suite 分布 = 17/12/11 | 17/12/11 | 17/12/11 | **PASS** |
| `pytest tests/eval/test_eval_fixtures_schema.py -q --no-cov` 全过 | exit=0,0 failed/error | exit=0,169 passed | **PASS** |
| `ruff check tests/eval` 受支持 Python 文件 0 issue | exit=0,0 issue | exit=0,All checks passed! | **PASS** |
| `desensitized` 标志 guard | desensitized=True 全过 | 40/40 fixture × 1 = 40 passed | **PASS** |
| 保留域 guard | example.* 全过 | 40 fixture + 5 单元 guard 全过 | **PASS** |
| 长数字 guard | 无 11+ 位连续数字 | 40 fixture + 3 单元 guard 全过 | **PASS** |
| ID suite 前缀 guard | `id` 以 `{suite}_` 起头 | 40 fixture 全过 | **PASS** |
| 来源 commit 含 SOL 审核声明 | `299aa79`/`c7c9037` 标注 | commit message 实测一致 | **PASS(元数据级)** |

### 6.3 候选门槛 #5 总判定

**PASS**(9/9 维度全过)。

> **口径提醒**:本节 9/9 是 coverage plan §3 + 本轮附加验证形成的自评结果,不是 `docs/v1.1-a-readiness-2026-08-05.md` 的原文计数。

### 6.4 关键边界说明(避免误判)

1. **候选门槛 ≠ 必须门槛**:#5 是 readiness 文档第 2 节「候选门槛(不阻塞 v1.1-A 解锁)」中的候选;**即使 #5 PASS,4 必须门槛(#1/#2/#3/#4)判定不变**。
2. **#5 PASS 不改变 v1.1-A 解锁结论**:**v1.1-A 仍 NOT_UNLOCKED**,因为 #1(P3 7d attention 未消,`com.myaiemployee.agent` `needs_human`)与 #2(30d 未到 + attention 非空)仍 FAIL;**本任务不重判 #1/#2**(已由 `tests/eval/audit/p3-7d-window-watch-20260808.md` 收官纠偏为「2 PASS / 2 FAIL」,与本任务时间锚一致)。
3. **#5 PASS 不撤销 P3 30d 阻断**:#2 P3 30d `elapsed < 30d` 且 attention 非空,预计 `2026-08-29T07:04:45.527698Z` 后(若 Day0 未重置)才可能进入时间窗;**本任务不预判 #2 何时 PASS,仅记录当前状态**。
4. **首次 pytest exit=1 不构成 fixture 失败**:**169 passed** 是断言层面的真实结果;exit=1 完全由 `pyproject.toml` 的 `fail_under=80` + 单一契约测试无 `my_ai_employee` 导入导致;**本任务不改覆盖率配置**,仅用 `--no-cov` 作为本次目标验收门;**长期覆盖率策略维持不变**。
5. **本任务不实施 fixture 修改、不修改 schema test、不动测试套件本身**;**仅新增 docs-only 报告 + 任务包 + MODIFICATION-LOG 追加**。
6. **本任务非 v1.1-A 解锁条件,也不替代 P3 7d/30d 时间窗与 attention 修复**;**候选门槛 #5 PASS 不构成 v1.1-A 启动理由**。

---

## 7. 4 必须门槛重述(沿 `p3-7d-window-watch-20260808.md` 收官纠偏口径)

> 本节**仅复述既有判定**,**不重新实测**(避免重复审计);实测依据见 `tests/eval/audit/p3-7d-window-watch-20260808.md`。
> 本报告时点 `2026-08-09T11:18:00Z` 与 Day0 `2026-07-30T07:04:45.527698Z` 相差 `10d 4h 13m 14.472302s`,即 **elapsed ≈ 10.18d**。

| # | 门槛 | 判定 | 关键依据 |
|---|------|------|---------|
| 1 | P3 7d unattended eligibility | **FAIL** | 本报告时点 elapsed ≈ 10.18d ≥ 7d;最近完整日报 `2026-08-08` 含 `health_sample_gap` / `news_run_gap` / `news_failure`;规则 `eligible = elapsed_days >= 7 and not has_attention` 不满足 |
| 2 | P3 30d P0/P1-free eligibility | **FAIL** | 未到 30d(`2026-08-29T07:04:45.527698Z` 后才可能时间维度 PASS);attention 非空 |
| 3 | 评测样本 ≥ 30 条跨 suite | **PASS** | 30/30 在 8/3 readiness(`a46fe02`)已记录 `129 passed`;本轮未重跑 30 条基线(本轮关注 40 条) |
| 4 | Feature Flag + SLO + Feedback 3 design docs | **PASS** | 5/5 docs-only 已集成(`7b6c0c1` + `41538b6` + `f38b12d` + `c1157cc` + `ce975f5`) |

**总判定**:**2 PASS / 2 FAIL**(规范计数);v1.1-A **NOT_UNLOCKED**。

---

## 8. 风险与红线

### 8.1 红线(本任务不越界)

* **不修改** `tests/eval/fixtures/`(40 条 JSON 原样保留)。
* **不修改** `tests/eval/test_eval_fixtures_schema.py`(131 行原样保留)。
* **不修改** `tests/eval/SCHEMA.md` / `tests/eval/README.md`。
* **不修改** `pyproject.toml` 的 `[tool.pytest.ini_options]` / `[tool.coverage.report]` 覆盖率阈值与 `addopts`。
* **不修改** `src/`、`scripts/`、`ops/`、`plugins/`、`.cursor/`、`ENABLE_*`、`LaunchAgent`、`launchd_plist/`、`flags` 表、SMTP、Notes、IMAP、CalDAV 任何运行时。
* **不重复 cherry-pick 源候选** `0bb7fba`/`1a7dec1`/`6272eb8`/`f2335d4`/`a1953e5`/`b8af81d`/`72e4091`;这些源哈希不是 `c7c9037` 祖先,成果经 §1.3 所列对应整合提交落地 main。
* **不发起** push/merge/tag。
* **不修改** 13 项用户未跟踪 WIP。

### 8.2 已知风险

* **R1**:`299aa79`/`c7c9037` 的「SOL 审核」声明仅依据各自 commit message 元数据;不代表本任务终审通过。本任务 **SOL 首轮终审 = FAIL**,本次集中修订后等待复审。
* **R2**:`--no-cov` 简化了覆盖率噪声,**未验证项目整体覆盖率**;若用户后续要求 `make coverage` 全量覆盖率验证,需在独立任务中跑(本任务不动覆盖率阈值)。
* **R3**:本任务**不重判** #1/#2/#4;仅复述既有判定;若用户希望重新实测,需独立任务发起。
* **R4**:`pytest`/`ruff` 通过主项目 `.venv` 调用(用户授权的只读工具);**未在工作 tree 内创建/修改 venv**;venv 完整性未验证,仅按用户给出的绝对路径直接调用。
* **R5**:首次 pytest exit=1 已在本报告 §3.1 如实记录;若下游消费者误读「169 passed」为「exit=0」,本节提供了修正口径;**不存在任何掩盖或改写**。
* **R6**:**SOL 首轮终审 = FAIL(8 个 findings),当前等待复审**;`status=ready_to_merge` 仅表示本地质量门通过的候选态;**只有 SOL 复审 PASS 才允许 commit**;TERRA/LUNA 待命。

### 8.3 MODIFICATION-LOG.md 既有 markdownlint 25 errors(非阻断基线风险)

* 完整 `MODIFICATION-LOG.md` markdownlint 实测 **exit=1,25 errors**,全部位于行号 **6727–6925**(均为历史 entry 长期积累的 MD022/blanks-around-headings 与 MD012/no-multiple-blanks),**早于本轮追加段(行号 6949+)**。
* 本轮新增日志条目按 `TASK-20260809-001` 标题锚点提取至 EOF,完整覆盖标题与正文,通过 stdin lint:**exit=0,0 errors**。
* **本任务的「完整新增日志条目 lint」维度为 PASS**;**整份文件的 25 errors 属非阻断基线风险**,需在独立任务中专项清理(本任务不动历史段落以避免越权修改既有 WIP)。

---

## 9. 验收(本文档)

* **精确 fixture 断言 A**:总数必须恰为 40,且 suite 分布必须恰为 `email_classify=17` / `email_draft=12` / `sap_troubleshoot=11` → exit=0(实测,见 §2.1 与 §10)。
* **pytest(首次原文命令)**:`.venv/bin/python -m pytest tests/eval/test_eval_fixtures_schema.py -q` → exit=1(覆盖率阈值失败,169 passed;非断言失败)(实测,见 §3.1)。
* **pytest(目标验收门)**:`.venv/bin/python -m pytest tests/eval/test_eval_fixtures_schema.py -q --no-cov` → exit=0,169 passed(实测,见 §3.2)。
* **ruff**:`.venv/bin/python -m ruff check tests/eval` → exit=0,受支持 Python 文件 `All checks passed!`(实测;Markdown/JSON 分别由 markdownlint/pytest guards 验证)。
* **YAML parse + task_id/assertions**:解析任务包并断言 `task_id == TASK-20260809-001-fixture-readiness`,且 acceptance_commands 同时含精确 fixture 断言与精确 whitelist 断言 → exit=0(实测,见 §10)。
* **markdownlint(本报告单文件)**:`markdownlint-cli2 tests/eval/audit/d6183-fixture-40-readiness-20260809.md` → exit=0,0 errors(实测,见 §10)。
* **markdownlint(完整新增日志条目 stdin)**:`sed -n '/^### 2026-08-09 \[执行建议\] TASK-20260809-001 /,$p' MODIFICATION-LOG.md | markdownlint-cli2 -` → exit=0,0 errors(实测,见 §10)。
* **markdownlint(整份 MODIFICATION-LOG.md,非阻断基线)**:`markdownlint-cli2 MODIFICATION-LOG.md` → exit=1,25 errors,行号 6727–6925,早于本轮追加段(实测,见 §8.3 与 §10;**非本任务引入,本任务不清理**)。
* **git diff --check**:`git diff --check` → 无冲突标记(实测,见 §10)。
* **精确 whitelist 断言 B**:`git status --porcelain=v1 -uall` 必须逐字等于 ` M MODIFICATION-LOG.md` + 两个指定 untracked 文件条目 → exit=0(实测,见 §10);不再用仅打印 status 的弱命令。
* **空白/冲突扫描**:对 3 个白名单文件扫描行尾空白与 Git 冲突标记 → 无命中(实测,见 §10)。
* **不触碰** fixture/schema test/`src/`/`scripts/`/`ops/`/`plugins/`/`.cursor/`/`ENABLE_*`/`LaunchAgent`/`pyproject.toml` 覆盖率阈值。
* **不重复 cherry-pick源候选**;成果通过 §1.3 对应整合提交落地;**不 push/merge/tag**。
* **不修改** 13 项用户未跟踪 WIP。
* **SOL 首轮终审 = FAIL,等待复审**(见 §12);`status=ready_to_merge` 仅本地候选态。

---

## 10. 验证命令汇总(逐条实测)

| # | 命令 | 预期 | 实测退出码 | 实测关键输出 |
|---|------|------|----------|--------------|
| 1 | `git rev-parse HEAD` | `c7c9037...` | 0 | `c7c9037024ee8b77c3636e1627d3950ed2d42006` |
| 2 | `git rev-list --left-right --count origin/main...HEAD` | left=0,right=0 | 0 | main = origin/main = `c7c9037` |
| 3 | `git rev-parse main` | `c7c9037...` | 0 | `c7c9037024ee8b77c3636e1627d3950ed2d42006` |
| 4 | 精确 fixture 断言 A(任务包 acceptance_commands 原文) | 总数 40;分布 17/12/11 | **0** | `fixture_count=40; suite_distribution={'email_classify': 17, 'email_draft': 12, 'sap_troubleshoot': 11}` |
| 5 | `pytest tests/eval/test_eval_fixtures_schema.py -q`(首次) | 169 passed;exit 由覆盖率决定 | **1** | `Coverage failure: total of 0.0 is less than fail-under=80.0` + `169 passed in 0.12s` |
| 6 | `pytest tests/eval/test_eval_fixtures_schema.py -q --no-cov`(目标门) | 169 passed;exit=0 | **0** | `169 passed` |
| 7 | `ruff check tests/eval` | 受支持 Python 文件 0 issue | **0** | `All checks passed!` |
| 8 | YAML parse + task_id/assertions | 新 task_id + 两个硬断言命令存在 | **0** | `task_id/assertions OK` |
| 9 | `markdownlint-cli2 tests/eval/audit/d6183-fixture-40-readiness-20260809.md` | exit=0,0 errors | **0** | `Summary: 0 error(s)` |
| 10 | `sed` 按 `TASK-20260809-001` 标题锚点提取至 EOF `\| markdownlint-cli2 -` | exit=0,0 errors | **0** | `Summary: 0 error(s)` |
| 11 | `markdownlint-cli2 MODIFICATION-LOG.md`(非阻断基线) | exit=1,25 errors at 6727–6925 | **1** | 25 errors(行号 6727–6925,本轮前) |
| 12 | `git diff --check` | 无冲突 | **0** | 无输出 |
| 13 | 空白/冲突扫描(3 文件) | 无命中 | **0** | `whitespace/conflict scan clean` |
| 14 | 精确 whitelist 断言 B(任务包 acceptance_commands 原文) | 精确 3 条 | **0** | ` M MODIFICATION-LOG.md` + 两个指定 `??` 条目 |

---

## 11. 下一棒(本任务不实施)

* 用户决定是否利用候选门槛 #5 PASS 作为 readiness 文档更新输入;**本任务不自动更新 readiness 文档**(避免越权改动 `docs/v1.1-a-readiness-2026-08-05.md`)。
* 用户单独处理 `com.myaiemployee.agent` `needs_human` 根因 → 新 epoch 启动后重新累计 7d。
* 等待 `2026-08-29T07:04:45.527698Z` 后 30d 计时满足(若 Day0 未重置);**本任务不预判该时点行为**。
* 持续观察 P3 7d attention 与根因修复进展;**本任务不发起新一轮 attention 观察**(已有 `p3-7d-window-watch-20260808.md` 记录)。
* 若用户希望复审 `#5 PASS` 的覆盖率维度(如调整 `addopts` / `fail_under` / 引入 `--cov-append` 等),需在独立任务中发起;**本任务不擅自调整项目覆盖率配置**。
* MODIFICATION-LOG.md 既有 25 errors 需在独立任务中专项清理;**本任务不清理历史段落以避免越权修改 WIP**。

---

## 12. SOL 提交前终审硬门(首轮 FAIL,等待复审)

* **SOL 首轮终审 = FAIL**,已给出 8 个 findings;本次集中修订完成后等待 SOL 复审。当前不得声称 PASS。
* 本报告与任务包 `status=ready_to_merge` **仅表示本地质量门全部通过的候选态**,**不构成提交许可**;TERRA/LUNA 待命。
* **SOL 终审硬门**:在 `codex` 实际 commit 任务分支之前,**必须由 SOL 复审本任务包与本报告**;**只有 SOL 复审 PASS 才允许 commit**;**SOL 复审 FAIL 则继续回退修订**;**任何状态下均不 merge/push/tag**。
* **执行顺序**(由后续 agent 落实):
  1. **SOL**(只读复审)→ 审阅本报告 + 任务包 + 本轮 MODIFICATION-LOG 追加段。
  2. **SOL 复审 PASS** → `codex`(仅在 PASS 后)→ 在任务分支 `codex/d6183-fixture-readiness-sol-20260809` 提交本任务 3 文件,**不 merge、不 push、不打 tag**。
  3. **SOL 复审 FAIL** → 继续回退修订,本任务保持 worktree 内未提交状态。
* **当前阶段**:SOL 首轮 FAIL,等待复审;本任务在 worktree 内完成 docs-only 集中修订,**未 commit、未 merge、未 push**;**未经 SOL 复审 PASS 不得声称已通过**。
