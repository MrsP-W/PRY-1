# SESSION-STATE — v0.2.68 P3 launch prep + pytest outcome 快照修复(2026-07-08) + `v0.2.1` 正式 tag 维持期

> **最后更新**:2026-07-08 14:00+ · **本轮 P0-P3 prep + pytest outcome 2904/1 快照校准已推送 + P1 质量门 3 门全绿 + P2 launchd 真 install 完整 install(撞坑 #81 实测命中 → bootout 数字员工)+ P3 launch prep docs-only**· outbox 2 条撞坑 #85 幻觉草稿已 `cancelled` · **项目**:我的AI员工 · **HEAD** 以 `git rev-parse --short HEAD` 为准 · **工作区**以 `git status --short` 为准
> **状态**:🟢 **Day 13 阶段 2.3 + 撞坑 #86 + 撞坑 #81 实测命中 + P0-P3 prep 全环 已收口** — HEAD / origin/main 以 `git status --short --branch` 为准;`bash scripts/launchd_install.sh install` 部署 3 wrapper + 3 plist + launchctl load × 3;数字员工 RunAtLoad=true 启动撞坑 #81(TCC Python.framework 3.12 鉴权拦截 → exit 126)→ `launchctl bootout` 立即恢复;agent + imap-sync 2/3 job 仍注册;SMTP 真发仍暂停;immutable 顺序:撞坑 #81 待用户手动 TCC 授权后再 `launchctl load -w`。**质量门**:**2904 passed / 1 skipped** / 89.12% / lint **263** / mypy **256 files**。**下一棒**:P3 真实业务最小闭环(任务 A/B/C 3 选 · 独立授权 → Notes 1-5 真同步 + SMTP 单封真发逐封命名收件人)→ P4 24h dry-run → P5 v1.0 tag 评估。
>
> **Phase A 沿用**:`reports/v0.2.55.2-path4-spike-L0L1L2-2026-07-01.md` 8 节(L0 2/2 + L1 10/10 + L2 4/4 = 12/12 全绿 · 撞坑 #71 回归)· commit `9770e38`。
>
> **Phase B 沿用**:`reports/v0.2.7.2-xoauth2-smtp-inmemory-spike-2026-07-01.md` 10 节(B1 18/18 脱敏 + B2 49/49 OAuth + B3 5/5 XOAUTH2 InMemory 1 封)· 沙箱不真发 + dummy 凭据 + 不读 Keychain。
>
> **Phase C 收口**:`docs/v0.2.62-v0.2.1-tag-readiness-recap-2026-07-01.md` 9 节(8/8 readiness 实质满足 · 决议不打 `v0.2.1` tag · 沿撞坑 #60)。

---

## 🎯 端午不休息(6/19-22)策略 — 继续推进

**决策**:端午不休息(沿 6/17 用户指令)。B 选项「端午连休保持」已废弃,6/19-22 链路不再暂停,继续推进 v0.2.2+ 启动候选。

**当前启动候选**:**`v0.2.1` tag 已落地(`71b4602`)** + **Day 13 阶段 2.3 process_inbox 真执行 ✅ + P0 审批修复 ✅ + 撞坑 #86 router 降级修复 ✅ + v0.2.65 preflight Hour 1-7 docs-only 收口 ✅ + v0.2.66 P2 launchd preflight 收口 ✅ + v0.2.67 P2 launchd 真 install + 撞坑 #81 bootout ✅ + v0.2.68 P3 launch prep docs-only ✅**(业务代码锚 `ae071f0` 已在远端;outbox 2 条已 `cancelled` · 未 SMTP 外发;launchd 2/3 job 仍注册;数字员工 1/3 已 bootout ⏸️ TCC 授权后手动 `launchctl load -w`) — **2904 passed / 1 skipped** / 89.12% / MD lint **263** / mypy **256 files**。**下一棒**:P3 真实业务最小闭环(任务 A/B/C 3 选 · 每任务前置 checklist + 独立授权)→ P4 24h dry-run → P5 v1.0 tag 评估;SMTP 真发需用户逐封命名收件人;v1.0 tag 默认不打。

**v0.2.2 #5 OAuth 2.0 Phase 2 5 commits 收口完成**(沿用):docs-only 启动 `b7b9ea7` + commit 2-4 主代码 + commit 5 依赖加锁 `6a0549e`。

**沿用范本**:[[~/.claude/CLAUDE.md]] §7 会话生命周期管理 + 4 阈值切分 + 4 步旧大历史处理

## 📂 项目状态(2026-06-18 20:50 锚定)

| 维度 | 实际值 |
|------|--------|
| v0.2.2 #5 commit 5 收口锚 | `6a0549e feat(deps): v0.2.2 #5 OAuth 2.0 Phase 2 commit 5/5 pyproject 加 msal+google-auth+google-auth-oauthlib` |
| 当前 HEAD | 以 `git rev-parse --short HEAD` 为准(不写精确 hash,避免自引用漂移) |
| 分支 | `main` |
| 工作区 | 以 `git status --short` 为准 |
| Tag | `v0.1.0 = 2af775f`(anchor 永不动)+ `v0.2.1-rc1 = b0e7f94`(维持期历史快照)+ **`v0.2.1 = 71b4602` annotated(撞坑 #60 反转 · 2026-07-01 已落地)** |
| 核心质量门 | **2904 passed / 1 skipped** · **89.12%** coverage · mypy --strict 0 errors(**256 files**) · MD lint **263 files** 0 errors(以 `make test` / `make coverage` / `make lint` 实测为准 · `make check-snapshot` 防漂移 · v0.2.68 P3 launch prep doc 落 262→263) |
| v0.2.1 release tag | ✅ **已落地(`71b4602` annotated · 撞坑 #60 反转 · 2026-07-01)** |
| 真账单 spike | ✅ **W3 真账单全量 49 笔 spike 跑通**(2026-06-24 · `parsed=49 inserted=24 categorized=24 duplicates=25 needs_confirm=0 failed=0 candidate_count=0 version=2027` · 5 重防误发全过 · 选项 B 路径 · 阶梯 5 阶段范本 1→5→10→25→49 全部收口 · 撞坑 #53 v2.0 累计公式 + #54 选项 B 范本)|
| outlook/gmail SMTP provider | ⏭️ **用户决策不配置**(2026-06-29) — 不使用 Outlook/Gmail · 不写入 Keychain · 不跑真实 spike · 代码 factory/OAuth 保留供未来,非本项目发布阻塞 |
| **NoteStructurerService.structure_and_emit 接入** | ✅ **关闭**(commit `4862fb3` · 4 文件 / +204 -7 / 3 new tests) |
| **NoteConfirmService 1-click 确认 UI** | ✅ **关闭**(commit `1c2331a` · 5 文件 / +1104 -1 / 32 new tests) |
| **L3 模糊匹配 ±1 day** | ✅ **关闭**(feat `5de016a` + docs `de3d1f7` · 24 new tests) |
| **菜单栏 badge 实时刷新 polling** | ✅ **关闭**(feat `d4ed573` + docs `e994c9a` · 17 new tests) |
| **tests/db/ FK 循环依赖 57 errors 修复** | ✅ **关闭**(feat `d87b08a` + docs `68d8f18` · 0 new tests · 纯测试基础设施) |
| **v0.2.1 #4 NoteStore 状态机化** | ✅ **关闭**(feat `0a1386c` · 1 file / ~80 / 13 new tests · 5 状态 NEW/STRUCTURED/PRIVATE_SKIP/FAILED/ARCHIVED + 状态机守卫) |
| **v0.2.1 #5 NoteStore L2/L3 跨源去重** | ✅ **关闭**(feat `75f87cc` · normalized_fingerprint SHA-256 + 11 new tests · 沿 D6 transactions 范本) |
| **v0.2.1+ NoteStore L2 跨源写入** | ✅ **关闭**(feat `b751820` · needs_confirm + candidate_match_id + 9 new tests) |
| **v0.2.1 #3 ExpenseServiceStub 实化** | ✅ **关闭**(feat `de5de10` · `core/expense_service.py` ~270 行 / 12 new tests · 7 方法 + 5 分钟异常缓存) |
| **v0.2.1 #6 OAuth 2.0 抽象层 Phase 1** | ✅ **关闭**(docs-only 评估 + OAuth2Provider Protocol + Keychain token 存取 + 14 tests) |
| **OAuth 2.0 Phase 2 docs-only 启动** | ✅ **关闭**(docs `b7b9ea7` · 1 file / +203 / 0 new tests · 5 commits 分解) |
| **MicrosoftOAuth2 实现** | ✅ **关闭**(feat `c0f83d4` · 2 files / +804 / 12 new tests · 沿 v0.2.2 范本单日单 commit 8 门全绿) |
| **GoogleOAuth2 实现** | ✅ **关闭**(feat `564b8db` · 2 files / +814 / 11 new tests · 沿 commit 2 范本提前 2 天完成) |
| **XOAUTH2 SMTP 鉴权集成实现** | ✅ **关闭**(feat `9966ad0` · 2 files / +1269 / 12 new tests · 顶层 placement 避免 14+ import 重构,沿 D5.6.5 4 重防误发,提前 3 天完成) |
| **OAuth 2.0 Phase 2 commit 5 依赖加锁** | ✅ **关闭**(feat `6a0549e` · 2 files / +146 / 0 new tests · `dependencies` 而非 `optional-dependencies.oauth`,沿 launch plan §2.1 commit 5 范本,提前 4 天完成) |
| **v0.2.25 P0 二修** | ✅ **关闭**(feat `cc22000` · 真账单 `--max-rows` 真透传 adapter + launchd seal bash bad substitution 修复) |
| **v0.2.26-v0.2.27** | ✅ **关闭**(W3 虚拟 spike 2345 行 + W3 真实格式 spike 2345 行 docs-only 收口) |
| **v0.2.28 L2 fingerprint sign-lock** | ✅ **关闭**(feat `36d07ce` · `normalize_fingerprint` 加可选 `sign` 参数 · 6 tests · 业务侧 `raw.type→+1/-1` 派生 · 撞坑 #42/#43/#44 三类沉淀) |
| **v0.2.29 候选 review/export 机制** | ✅ **关闭**(feat `dc40b7c` · `TransactionStore.list_by_needs_confirm` 只读 + `scripts/export_transaction_candidates.py` JSONL/CSV 导出 · 38 tests) |
| **v0.2.30 候选导出硬化** | ✅ **关闭**(fix `5167163` · `.gitignore` 保护 + CLI 错误硬化 + 沿 v0.2.18 §3 范本) |
| **v0.2.31 候选 review 汇总闭环** | ✅ **关闭**(feat `1e932c7` · 6 维度聚合脚本 + `review_decision` 三分类白名单 + 14 tests · 撞坑 #46/#47/#48 三类沉淀) |
| **v0.2.32 W3 真账单 spike + 撞坑 #49** | ✅ **关闭**(feat `5e25983` · 真实支付宝 62 笔 → `--max-rows 1` `parsed=1 inserted=1 categorized=1 version=2027` · detect_version 扫前 30 行 + `AlipayCSV2027RealParser` + 4 tests · 撞坑 #49 faker≠真实格式收口) |
| **v0.2.33 状态口径二次纠偏** | ✅ **关闭**(docs `aa2a937` · 3 文件顶部统一 · 撞坑 #50 第二层范本起点) |
| **v0.2.34 W3 真账单 `--max-rows 10` 阶梯验证** | ✅ **关闭**(docs `bbb76a7` · spike-10 `parsed=10 inserted=5 categorized=5 duplicates=5` · 阶梯 3 阶段范本 + 撞坑 #52) |
| **v0.2.35 W3 真账单 `--max-rows 25` 阶梯验证** | ✅ **关闭**(docs `a6e2409` · spike-25 `parsed=25 inserted=15 categorized=15 duplicates=10` · 阶梯 4 阶段范本 + 撞坑 #53 跨 spike 累计公式校验) |
| **v0.2.35 漂移小修** | ✅ **关闭**(docs `d8e04e2` · 2 处精确 HEAD hash → `git rev-parse` 范本 · 撞坑 #50 第三层) |
| **v0.2.36 W3 真账单 `--max-rows 49` 全量入库** | ✅ **关闭**(docs-only · spike-49 `parsed=49 inserted=24 categorized=24 duplicates=25` · 选项 B 路径 · 阶梯 5 阶段范本 1→5→10→25→49 + 撞坑 #53 v2.0 累计公式 + #54 选项 B 优于 A 范本) |

## 📅 端午不休息时间线(2026)

| 日期 | 星期 | 行动 | 状态 |
|------|------|------|------|
| 6/17 17:45 | 周三 | NoteStructurerService.structure_and_emit 接入开工 | ✅ |
| 6/17 18:00 | 周三 | **v0.2.2 P0 收口 commit `4862fb3`**(4 文件 / +204 -7 / 3 new tests) | ✅ |
| 6/17 18:00 | 周三 | **v0.2.2 P0 收口 docs commit `07a9f26`**(2 文件 / +124 -11) | ✅ |
| 6/17 19:00 | 周三 | NoteConfirmService 1-click 确认 UI 接入开工 | ✅ |
| 6/17 19:30 | 周三 | **v0.2.2 #2 feat commit `1c2331a`**(5 文件 / +1104 -1 / 32 new tests) | ✅ |
| 6/17 19:30 | 周三 | **v0.2.2 #2 收口 docs commit `90cd131`**(reports + SESSION-STATE) | ✅ |
| 6/18 | 周四 | L3 模糊匹配 ±1 day 开工 | ✅ |
| 6/17 20:00 | 周三 | **v0.2.2 #3 feat commit `5de016a`**(4 文件 / +358 -3 / 24 new tests) | ✅ |
| 6/17 20:30 | 周三 | **v0.2.2 #3 收口 docs commit `de3d1f7`**(reports + SESSION-STATE) | ✅ |
| 6/17 20:45 | 周三 | badge 实时刷新 polling 开工 | ✅ |
| 6/17 21:00 | 周三 | **v0.2.2 #6 feat commit `d4ed573`**(3 文件 / +538 -6 / 17 new tests) | ✅ |
| 6/17 21:00 | 周三 | **v0.2.2 #6 收口 docs commit `e994c9a`**(reports + SESSION-STATE) | ✅ |
| 6/17 21:30 | 周三 | **v0.2.2 #6 docs commit `7377c27`**(README 同步 + 项目状态校准) | ✅ |
| 6/18 09:00 | 周四 | **v0.2.2 #7 启动**(环境诊断 + 误报 SIGKILL 137 + 复现 57 errors) | ✅ |
| 6/18 09:30 | 周四 | **v0.2.2 #7 feat commit `d87b08a`**(1 文件 / +76 / 0 new tests) | ✅ |
| 6/18 09:30 | 周四 | **v0.2.2 #7 收口 docs commit `68d8f18`**(reports + SESSION-STATE) | ✅ |
| 6/18 09:30 | 周四 | **v0.2.2 #7 docs commit `7fd162c`**(SESSION-STATE 同步 #7 关闭) | ✅ |
| 6/18 09:30-10:30 | 周四 | **v0.2.2 #5 启动**(Phase 1 摸底 + 5 commits 分解 + 13 行复用要点) | ✅ |
| 6/18 10:00 | 周四 | **v0.2.2 #5 docs-only 启动 commit `b7b9ea7`**(1 file / +203 / 0 new tests) | ✅ |
| 6/18 10:30 | 周四 | **Agent Assistant 跨项目沉淀 commit `d879847`**(L2_memory 2 files / +140) | ✅ |
| 6/18 19:00+ | 周四 | **v0.2.2 #5 commit 2/5 提前 1 天开工**(用户授权"今天 18:00+ 启动 MicrosoftOAuth2") | ✅ |
| 6/18 19:30 | 周四 | **v0.2.2 #5 feat commit `c0f83d4`**(2 files / +804 / 12 new tests · MicrosoftOAuth2 8/8 门全绿) | ✅ |
| 6/18 19:30 | 周四 | **v0.2.2 #5 收口 docs commit `18d1610`**(reports + SESSION-STATE · 沿 v0.2.2 范本) | ✅ |
| 6/18 19:30+ | 周四 | **v0.2.2 #5 docs-only 校准 commit `115fc8e`**(修 3 漂移 + MODIFICATION-LOG 规则入库 · 4 files / +236 -6 · 8/8 门全绿) | ✅ |
| 6/18 20:00 | 周四 | **v0.2.2 #5 commit 3/5 feat commit `564b8db`**(2 files / +814 / 11 new tests · GoogleOAuth2 9/9 门全绿 · 提前 2 天完成) | ✅ |
| 6/18 20:00 | 周四 | **v0.2.2 #5 commit 3/5 收口 docs commit `51675fc`**(reports + SESSION-STATE · 沿 v0.2.2 范本) | ✅ |
| 6/18 20:30 | 周四 | **v0.2.2 #5 commit 4/5 feat commit `9966ad0`**(2 files / +1269 / 12 new tests · XOAUTH2 9/9 门全绿 · 顶层 placement 避免重构 + 4 重防误发) | ✅ |
| 6/18 20:30 | 周四 | **v0.2.2 #5 commit 4/5 收口 docs commit `057d937`**(reports + MODIFICATION-LOG + SESSION-STATE · 9 段 5 决策 6 教训 · 提前 3 天完成) | ✅ |
| 6/18 20:50 | 周四 | **v0.2.2 #5 commit 5/5 feat commit `6a0549e`**(2 files / +146 / 0 new tests · pyproject + uv.lock 加 msal+google-auth+google-auth-oauthlib · 8/8 门全绿 · 提前 4 天完成) | ✅ |
| 6/17 13:07 | 周三 | **v0.2.1 #4 NoteStore 状态机化 feat commit `0a1386c`**(1 file / ~80 / 13 new tests · 5 状态 NEW/STRUCTURED/PRIVATE_SKIP/FAILED/ARCHIVED) | ✅ |
| 6/17 13:34 | 周三 | **v0.2.1 #5 NoteStore L2/L3 跨源去重 feat commit `75f87cc`**(normalized_fingerprint SHA-256 + 11 new tests) | ✅ |
| 6/17 16:57 | 周三 | **v0.2.1+ NoteStore L2 跨源写入 feat commit `b751820`**(needs_confirm + candidate_match_id + 9 new tests) | ✅ |
| 6/17 14:00 | 周三 | **v0.2.1 #3 ExpenseServiceStub 实化 feat commit `de5de10`**(`core/expense_service.py` ~270 行 / 12 new tests · 7 方法 + 5 分钟异常缓存) | ✅ |
| 6/18 21:30 | 周四 | **v0.2.1 #3/#4/#5 docs-only 校准(状态漂移修复)** — SESSION-STATE 5 处同步 + MODIFICATION-LOG 累计 + README 同步 + reports/v0.2.1-candidates-closure-2026-06-18.md | 🟢 |
| 6/18 22:00 | 周四 | **v0.2.2 #8 SMTPProviderFactory 撞坑恢复 commit `b2cf3c5`**(并发进程实施 + 用户授权代 commit · 6 files / +232 -69 / 10 new tests · QQ/Outlook/Gmail connector + provider-aware Keychain · 8/8 质量门全绿) | ✅ |
| 6/18 22:00 | 周四 | **v0.2.2 #8 docs closure commit `51da8fd`**(reports/v0.2.2-p8-smtp-provider-factory-2026-06-18.md 新建 · 收口报告) | ✅ |
| 6/18 22:00 | 周四 | **v0.2 launch plan 整体收口 docs(本轮 docs-only)** — reports/v0.2-closure-2026-06-18.md 新建 · 13 子阶段双链锚定 · 57 主项目 commits · SESSION-STATE/MODIFICATION-LOG/README 同步 | 🟢 |
| 6/18 22:30 | 周四 | **v0.2.4 状态漂移审查机制入库 docs(本轮 docs-only)** — docs/v0.2.4-drift-review-mechanism-2026-06-18.md 新建 · 4 机制 + 7/1 月度复盘 checklist + 撞坑恢复 3 步范本 + SESSION-STATE/MODIFICATION-LOG/README 同步 | 🟢 |
| 6/18 22:45 | 周四 | **v0.2.5 SMTP 真实发送 spike preflight docs-only** — docs/v0.2.5-smtp-real-send-preflight-2026-06-18.md 新建 · 4 模块链路核对 + 5 重防误发门控就绪 + InMemory 5 封跑通(不真发)+ 撞坑恢复 3 步实战演练 1 | 🟢 |
| 6/19-22 | 端午 4 天 | **继续推进**(链路不停) | 🟢 |
| 6/20 | 周六 | **v0.2.6 D4.7.4 v1.0.3 改进项延后** — `f0d8bd3` feat(reviewer) 2 files / +111 -1 / 5 new tests · sensitive 词表 21→27 词 + factual 触发 4→7 正则 + B 类自动解封 + 8/8 质量门全绿(2225 passed / 1 skipped / 88.85% coverage) | 🟢 |
| 6/21 | 周日 | **v0.2.7 outlook/gmail SMTP 真实发送 spike 准备 docs-only** — docs/v0.2.7-...md 新建 · 6 项启动条件 checklist + 5 重风险门控 + 3 个启动命令范本 + 5 阶段启动流程 · 撞坑恢复 3 步实战演练 2(沿 [[v0.2.4]] §3 机制 3) · 不真发邮件 · 8/8 质量门 baseline 验证 | 🟢 |
| 6/22 | 周一 | **v0.2.8 release notes 收口 + v0.2.1 release tag 锚定策略同步 docs-only** — docs/v0.2-release-notes-2026-06-22.md 新建 · 285 commits / 80 feat / 126 new tests / 2225 passed baseline / 8 大特性用户视角 + 8 项 tag 锚定前置条件 + B 类延后清单 5 项 7/1 评估方向 · 沿 D5.7.2 范本 8/1 锚定 · 不真发邮件 · 不打 v0.2.0/v0.2.1 tag | 🟢 |
| 6/22 | 周一 | **v0.2.9 W3 真账单 spike docs-only 准备 + 撞坑恢复 3 步实战演练 3** — docs/v0.2.9-w3-real-bill-spike-prep-2026-06-22.md 新建 · 6 项启动条件 checklist + 4 重风险门控 + 3 个启动命令范本 + 5 阶段启动流程 · 撞坑恢复 3 步实战演练 3(沿 [[v0.2.4]] §3 机制 3) · 不真跑 spike · 等用户真实微信/支付宝 CSV | 🟢 |
| 6/22 | 周一 | **v0.2.10 全链路重启 checklist docs-only + 撞坑恢复 3 步实战演练 4** — docs/v0.2.10-full-restart-checklist-2026-06-22.md 新建 · 6 模块链路核验(launchd/kickstart + DB 路径 + 菜单栏 + Notes + 账单导入脚本 + SMTP 门控 全部 ✅ 就绪) + 7 阶段启动 checklist(环境准备 + 8/8 质量门 + launchd + 菜单栏 + Notes + W3 + outlook/gmail)+ 3 真实 spike 启动路径 · 撞坑恢复 3 步实战演练 4(沿 [[v0.2.4]] §3 机制 3) · 不真发邮件 · 不真导入账单 · 不移动 v0.1.0 tag | 🟢 |
| 6/20 | 周六 | **v0.2.11 全链路重启 7 阶段 dry-run 预演 + 撞坑恢复 3 步实战演练 5** — docs/v0.2.11-7-stage-dry-run-2026-06-20.md 新建 · 4 个 dry-run 验证点(mkdir data/ ✅ + 8/8 质量门 baseline 全绿 2225 passed + launchd kickstart 5 源 5/5 全部存在 + 菜单栏 import 验证 ✅ rumps 0.4.0 + Quartz OK) · 阶段 5/6/7 占位说明 · 撞坑恢复 3 步实战演练 5(沿 [[v0.2.4]] §3 机制 3) · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/20 | 周六 | **v0.2.12 6/23 全链路重启实战前置 docs-only + dry-run 深化 + 撞坑恢复 3 步实战演练 6** — docs/v0.2.12-6-23-restart-prep-2026-06-20.md 新建 · 5 step 实战预演(.env cp ✅ + mkdir data/ ✅ + 8/8 质量门 baseline 沿用 ✅ ruff check + format + mypy/pytest SIGKILL 137 误报沿用 baseline + launchd 5 源 5/5 + bash 语法 OK + 201 行 + 4 退出码 + 菜单栏 5 子模块 import 全部成功 + TCC 双层防御 + Notes 4 子模块 import 全部成功 + 5 状态机化 + sync_notes CLI 4 退出码 + NOTES_REAL_NETWORK=1 env 门控) · 撞坑恢复 3 步实战演练 6(沿 [[v0.2.4]] §3 机制 3) · SIGKILL 137 误报沿 [[2026-06-18-venv-sigkill-137-false-alarm]] 范本处理 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/20 | 周六 | **v0.2.13 6/23 全链路重启实战手册 docs-only + 撞坑恢复 3 步实战演练 7(本轮)** — docs/v0.2.13-6-23-restart-playbook-2026-06-20.md 新建 · 7 阶段实战手册(每阶段精确命令 + 预期输出 + 撞坑处理 + 下一阶段门槛) + 16 类撞坑汇总(覆盖环境 + uv + SIGKILL 137 + pytest + launchd + TCC + AppleScript + W3 + SMTP + OAuth + 发件拒绝) · 撞坑恢复 3 步实战演练 7(沿 [[v0.2.4]] §3 机制 3) · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/20 | 周六 | **v0.2.14 E+A 实操就绪验证首次落地 docs-only + 撞坑恢复 3 步实战演练 8(本轮)** | 🟢 |
| 6/20 | 周六 | **v0.2.15 A 候选 6/23 实操就绪最后冲刺 docs-only + 撞坑恢复 3 步实战演练 9(本轮)** | 🟢 |
| 6/20 | 周六 | **v0.2.16 7/1 月度复盘准备 docs-only(本轮)** — docs/v0.2.16-7-1-monthly-review-prep-2026-06-20.md 新建 · 5 复盘项全部预先 docs 化(复盘项 1 B 类延后清单 5 项 + 复盘项 2 撞坑恢复范本 9 个 + 复盘项 3 SIGKILL 137 误报 67% + 复盘项 4 v0.2.1 release tag 8 项前置条件 6/8 ✅ + 复盘项 5 状态漂移审查机制实战 5/5 修复)+ 7/1 12:00 启动 → 17:00 收官执行计划 · 沿 [[v0.2.4-drift-review-mechanism-2026-06-18]] §3 + §4 + [[b-class-deferral-2026-06-09]] 范本 · 提前 11 天 docs-only 准备避免当天突击 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 | — docs/v0.2.15-A-sprint-restart-readiness-2026-06-20.md 新建 · A 冲刺 6/20 当天完成不等 6/21 · 5 步骤全部完成(launchd plist com.myaiemployee.agent.plist 存在 + plutil -lint OK + launchctl 已加载 + 菜单栏 5 子模块源码完整 + Notes 4 子模块源码完整 + alembic --sql 0014 复跑 + pytest 2225 passed / 1 skipped / 88.85% coverage 30.86s)· 撞坑 #19 classifier 误判 plutil -p(只读被拒)+ #20 classifier 双重混淆(只读被拒 + 自身说匹配边界)+ #21 pwd 漂移 .venv/bin 消失(伪撞坑)+ #22 grep 连写模式错误漏掉 plist(myaiemployee 不匹配 my-ai|myai|ai-employee 三分支)四类新撞坑真触发 + 真恢复 · 8/8 质量门 baseline 6/8 ✅ 实测(从 v0.2.14 5/8 推到 6/8)+ 阶段 1-5 实测就绪(阶段 6-7 等用户授权)+ 撞坑恢复 3 步实战演练 9(沿 [[v0.2.4]] §3 机制 3 · 范本累计 8 → 9 个 · 范本类型累计 4 → 5 类)+ 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 | — docs/v0.2.14-pitfall-recovery-drill-8-2026-06-20.md 新建 · E+A 用户决策落地(暂停 docs-only + 实操就绪验证)+ 撞坑 #1 SQLCIPHER_KEY 缺失(alpha-2 openssl 新密钥 64 字符 hex · KEY env var 方式 · 密钥不打印到聊天)+ 撞坑 #16.5 ruff format 漂移(beta 用 .venv/bin/ruff format 修复 spike_set_smtp_password.py)+ 撞坑 #18 ruff PATH 误报(uv run ruff 报 No such file or directory · 改用 .venv/bin/ruff 绝对路径)+ 8/8 质量门 baseline 5/8 ✅ 实测(ruff check + format + mypy src 0 errors + alembic --sql exit 0 + make lint 0 errors)+ 2/8 ⏸️ 沿 v0.2.13 baseline(pytest + uv build)+ 1/8 🟢 collect 漂移(pytest 2226 vs README 2225)+ 撞坑恢复 3 步实战演练 8(沿 [[v0.2.4]] §3 机制 3 · 范本累计 7 → 8 个 · 从"规划态"升级到"实测态")+ 撤销 E 边界补 docs(组合 4)+ 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/22 | 周一(上午)| **v0.2.17 6/23 实操就绪最后冲刺 docs-only + 撞坑恢复 3 步实战演练 10** — docs/v0.2.17-6-23-readiness-final-sprint-2026-06-22.md 新建 · 5 阶段重验证实测就绪(阶段 1 agent.plist OK / 阶段 2 menu_bar/ 5 文件 976 行 / 阶段 3 跨 4 目录 5 文件 2315 行 / 阶段 4 uv run alembic --sql 0014 DDL 完整 / 阶段 5 pytest 2225 passed / 88.85% / 33.51s · 30.86s → 33.51s 正常波动)+ 6 类新撞坑真触发 + 真恢复(撞坑 #21 复发 pwd 漂移 + #24 plist 假设数量错误只有 1 个而非 3 个 + #25 SIGKILL 137 类 .venv/bin/alembic framework 签名失效 + #26 连写错误复发 myaiemployee→my_ai_employee + #27 菜单栏 5 子模块路径假设错误实际在 menu_bar/ + #28 Notes 4 子模块路径假设错误实际跨 4 目录 5 文件)+ 撞坑史 5 类 → 6 类(新增 docs 假设错误类)+ 撞坑恢复 3 步实战演练 9 → 10(范本累计 9 → 10)+ 8/8 质量门 baseline 6/8 ✅ 实测沿 v0.2.15(从 5/8 推到 6/8 + 沿用)+ 1/8 ⏸️(uv build)+ 1/8 🟢(pytest 2225 沿 v0.2.15 baseline · 30.86s → 33.51s 正常波动)+ 6/23 启动前最后窗口 docs-only 收口 · 阶段 6-7 等用户授权 + 真实 CSV + Outlook/Gmail 凭据 + B 类白名单扩展 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/22 | 周一(晚间)| **v0.2.19 6/23 全链路重启执行包 docs-only(本轮)** — docs/v0.2.19-6-23-restart-execution-package-2026-06-22.md 新建 · 5 段紧凑(不沿用 v0.2.18 12 段范本)· 阶段 1-5 复核 5 校验命令(plist 数量 + 菜单栏 5 子模块 + Notes 5 子模块 + alembic DDL + pytest)+ 阶段 6 启动条件 W3 真账单 spike(等真 CSV)+ 阶段 7 启动条件 outlook/gmail SMTP 真实 spike(等授权 + 凭据 + B 类白名单)+ 6/23 周二待用户触发清单 7 项 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/22 | 周一(深夜)| **v0.2.20 6/23 全链路重启实操前复核结果(本轮 docs-only,A0-A4 5 步实操) — docs/v0.2.20-restart-preflight-result-2026-06-22.md 新建 · 不扩展新范本只记录结果** — A0 状态冻结:HEAD `04c97d4` / 起点 HEAD `dcbd6fe` / v0.1.0 tag `2af775f`(未动)/ git status clean / branch main / 修复撞坑 #21 pwd 漂移(显式 cd 我的AI员工)/ A1 阶段 1-5 5 校验命令实测:A1-1 plist 数量 = **2**(`com.user.proxy-watch.plist` 752 bytes 6/9 部署 + `com.myaiemployee.agent.plist` 3483 bytes 6/16 09:57 已部署 — ⚠️ **v0.2.20 §2 报告"plist 数量 = 1"为错误,撞坑 #24 真实根因是命令匹配模式 `com.user.*` 不匹配 `com.myaiemployee.*`**,见 §7 修正补丁)/ A1-2 菜单栏 = 7 文件 1684 行(撞坑 #27 修正 5→7)/ A1-3 Notes = 11 文件跨 6 目录 3371 行(撞坑 #28 修正 5→11)/ A1-4 alembic DDL 完整(撞坑 #30 修正 `--sql` 子命令格式)/ A1-5 pytest 2225 passed, 1 skipped / 30.72s / 88.85%(撞坑 #31 mypy tests 13 errors 不阻塞 baseline)/ A2 结果判定 = **5/5 通过 → GO**(进入授权候选)/ A4 最小收口 docs/v0.2.20(只记录结果不扩展新范本)/ docs 假设撞坑实际命中 3 例(#24+#27+#28)+ 命令格式撞坑 1 例(#30)+ baseline 撞坑 1 例(#31 mypy tests 13 errors 沿 baseline)/ 阶段 6-7 等用户授权 + 真实 CSV + Outlook/Gmail 凭据 + B 类白名单扩展 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/22 | 周一(深夜)| **v0.2.21 撞坑 #24 二次命中修正 + 选项 C launchd 验证(本轮诚实修正) — docs/v0.2.20 §7 追加修正补丁 · 不堆新 docs-only** — 撞坑 #24 真实根因 = 主 Agent 命令匹配模式错误(`ls ~/Library/LaunchAgents/com.user.*.plist` 不匹配 `com.myaiemployee.*`,应广匹配 `com.{user,myaiemployee}.*.plist`)/ 选项 C launchctl print 10 维度验证 launchd agent 8 节点完全就绪(1 plist 部署 3483 bytes 6/16 09:57 + 2 plutil -lint OK + 3 一致性 + 4 launchctl load `- 0` PID=0 已注册 + 5 ~/bin/my-ai-employee-monthly-report 197 bytes + 6 scripts/monthly_report.py 434 行 + 7 日志目录 + 8 calendarinterval 2027/1/1 9:00 待触发)/ **A3-1 launchctl install 授权项取消**(已部署 5 天)/ 撞坑 #21 pwd 漂移第四次复发(7 文件夹重构后顶层路径相似)/ 沿用范本 [[v0.2.18-docs-assumption-pitfall-2026-06-22]] §3 撞坑史 6 类 + [[b-class-deferral-2026-06-09]] + [[d10.5.3-launchd-fixes]]/ 撞坑史新增子类型"主 Agent 命令匹配模式错误"(沿 docs 假设错误类下细分)/ 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd · 不移动 v0.1.0 tag(2af775f) | 🟢 |
| 6/22 | 周一(深夜)| **v0.2.22 W3 真账单 faker dry-run(本轮无副作用实操 · 不堆 docs-only · 不造真账单结论) — 用户推荐 W3 授权口 / 用 faker 样本跑 D6.1+D6.2+D6.3 5 维度 dry-run** — D-1 微信 2022-2025 faker 4/5 通过(10 笔/版本,parse 链路全 OK)+ D-1.6 微信 2026 faker 撞坑 = NotImplementedError(2026 解析器未实化,D6.1 InMemory 模拟先推,真实样本待用户补充)/ D-2 支付宝 2022-2025 faker 4/5 通过 + D-2.2 支付宝 2026 faker 同撞坑/ D-3 fingerprint L2 跨源候选 3 对验证(wechat + alipay 同日同金额同商家 → 同 fp 全部命中:星巴克 + 美团外卖 + 工资发放)/ D-4 categorizer 9 商家全部归类(dining/transport/home/other 5 选 1)+ merchants 654 条 5 分类均匀分布(transport 122 + home 121 + other 151 + dining 128 + shopping 132)/ 撞坑 #21 pwd 漂移第五次复发(本次实测跨项目 Bash 3 次显式 cd)/ 撞坑识别 = 2026 解析器待用户真实样本补充(D6.1 InMemory 已覆盖,真实样本决策 B 类延后)/ 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd · 不移动 v0.1.0 tag(2af775f) | 🟢 |
| 6/22 | 周一(深夜)| **撞坑 #30+#31 dry-run 沉淀(不堆 docs)** — 5 校验命令 dry-run + 整体 8/8 质量门 deep-dry-run 撞坑史 6 类实际命中 5 例:#24 agent.plist 源存在但目标位置未部署(源 `launchd_plist/com.myaiemployee.agent.plist` 3495 bytes · 目标 `~/Library/LaunchAgents/com.myaiemployee.agent.plist` 缺失)/ #27 菜单栏 5 → 7 文件(漏算 `__init__.py` + `app.py`)/ #28 Notes 5 → 11 文件(跨 6 目录含 prompt + 3 migration)/ #30 alembic 命令格式 `--sql` 应是子命令参数(应为 `uv run alembic upgrade 0014 --sql`)/ #31 mypy tests 13 errors baseline 撞坑(scheduler/test_outbox_dispatcher* 10 + policy/test_send_adapter 1 + test_outbox_adapter 1 + db/test_outbox_approval_provenance 1 · 全是 [no-any-return] · v0.2.17 docs 假设 mypy tests 0 errors 实际 13 errors)/ 5 校验 4 失败 1 通过(阶段 5 pytest 2225 passed / 88.85% / 31.35s · 与 v0.2.17 88.85% baseline 一致)/ 整体 8/8 质量门 deep-dry-run:pytest ✅ / ruff check ✅ / ruff format ✅ / mypy src ✅ / alembic upgrade head --sql ✅ DDL 完整 / markdownlint ✅ 116 files 0 error / mypy tests ❌ 13 errors(撞坑 #31 实际命中)/ 撞坑 #24 任务 2 launchctl install 被自动分类器拦截(尊重"不真 kickstart launchd"边界)/ 任务 3 deep-dry-run 全部通过(alembic 修正命令 DDL 完整 + 菜单栏 7 文件 import 通过 + Notes 7 文件 import 通过)/ 任务 1 docs 收口撞坑 #30+#31 决策 = 仅沉淀到 SESSION-STATE(不开 v0.2.20+ docs,沿用户纠偏) | 🟢 |
| 6/22 | 周一(下午)| **v0.2.18 docs 假设错误类撞坑专项清单 + 撞坑恢复 3 步实战演练 11** — docs/v0.2.18-docs-assumption-pitfall-2026-06-22.md 新建 · 撞坑史 6 类首次专项固化(撞坑 #24-#28 5 例 + #29 撞坑史类数凭印象错误新增 · docs 假设错误类 6 例专项清单)+ 撞坑恢复 3 步实战演练 10 → 11(范本累计 10 → 11 · docs 假设错误类专项 3 步实战范本 Step 1 docs → 实测差距识别 / Step 2 降级应对 + 实测数据回填 / Step 3 docs 更新 + 范本沉淀)+ 检查员 Plan-Execute 范式 P3 升级建议(docs 假设校验环节)B 类延后声明 + 6/23 实操启动 docs 假设校验预演清单 5 项 · 不真发邮件 · 不真导入账单 · 不真启动菜单栏 · 不真 kickstart launchd | 🟢 |
| 6/23+ | 周二 | W3 真账单 spike 启动(沿 v0.2.9 §"启动流程 5 阶段"· 等真 CSV)+ outlook/gmail SMTP 真实发送 spike(沿 v0.2.7 §"启动流程 5 阶段")+ 全链路重启(沿 v0.2.10 + v0.2.11 + v0.2.12 + v0.2.13 §"7 阶段实战手册"+ v0.2.14 §"8/8 质量门 baseline 5/8 ✅ 实测就绪")| ⏸️ |
| 6/23 | 周二 | **v0.2.25 P0 二修 + v0.2.26 虚拟 spike + v0.2.27 真实 spike + v0.2.28 L2 sign-lock + v0.2.29 候选 review/export + v0.2.30 导出硬化 6 commit 链**(沿 v0.2.18 §3 撞坑范本 + 撞坑 #42/#43/#44)· **2261 passed / 1 skipped / 0 mypy / 0 ruff** | ✅ |
| 6/24 | 周三 | **v0.2.31 候选 review 汇总闭环 + v0.2.32 W3 真账单 spike + 撞坑 #49 收口**(用户提供真实支付宝 62 笔流水 5/24-6/24 16827.01 元)· `--max-rows 1` 跑通 `parsed=1 inserted=1 categorized=1 version=2027` · 撞坑 #49 faker≠真实格式(22 行前缀/`交易时间`/`不计入收支`)· 新增 2027 real parser + 4 tests · **2265 passed / 1 skipped / 0 mypy / 0 ruff / 0 MD lint** · HEAD `5e25983` | ✅ |
| 6/24 | 周三 | **v0.2.33 状态口径二次纠偏 + v0.2.34 spike-10 + v0.2.35 spike-25 + v0.2.35 漂移小修**(阶梯 1→5→10→25 四阶段范本 + 撞坑 #50 第二层 + #52 阶梯 + #53 累计公式 v1.0)· 14 commit 链 · docs-only 4 commits | ✅ |
| 6/24 | 周三(上午)| **v0.2.36 W3 真账单 `--max-rows 49` 全量入库收口(选项 B 路径 · docs-only)** — spike-49 跑通 `parsed=49 inserted=24 categorized=24 duplicates=25 needs_confirm=0 failed=0 candidate_count=0 version=2027` · 阶梯 1→5→10→25→49 五阶段范本 + 撞坑 #53 v2.0 累计公式(Σ(inserted) + Σ(duplicates) = Σ(max-rows) = 90 = 49 + 41 = 1+5+10+25+49 ✅)+ 撞坑 #54 选项 B 优于选项 A 范本 · 9/9 质量门全绿(2265 passed / 1 skipped / 88.77% coverage · ruff format 1 修复 export 脚本)· docs-only 收口 3 文件顶部 + 新增 docs/v0.2.36-w3-spike-49-2026-06-24.md · 不真发邮件 · 不真导入新账单(沿用 `--max-rows` 严守 · 选项 B 守护范本)· 不 kickstart launchd · 不移动 v0.1.0 tag · 不打 v0.2.x tag | ✅ |
| 6/25 | 周四 | **v0.2.42-v0.2.51 mypy --strict / W3 spike docs 链路 10 commit** — 撞坑 #55 v4.0 四重锁死范本(命令 + 配置 + Makefile + 严格模式)/ 撞坑 #56 AST 注入顺序陷阱 / 撞坑 #57 ast.unparse 注释丢失 / 撞坑 #58 MD022 33 文件批量修复 / 撞坑 #50 风险门控 | ✅ |
| 6/25 | 周四 | **v0.2.52 SMTPProviderFactory 协议不匹配修复(撞坑 #61)+ Makefile alembic 退出码修复(撞坑 #62)+ 状态三入口同步**(`91cbe96` · 7 files / 353+/-)· 9/9 质量门全绿(2270 passed / 1 skipped / 88.81% / mypy --strict 0 errors / 209 files / ruff 全绿 / alembic exit 0 / uv build OK / make lint 141 files 0 errors)| ✅ |
| 6/25 | 周四 | **v0.2.52.1 OutboxDispatcher 自动路由(provider 默认值同步 + 冲突严判,撞坑 #63)收口**(`dd2e93f` · 6 files / 309+/-)· 5 路径严判(路径 1 provider + 默认值可用 / 路径 2 缺失 fallback / 路径 3 显式 / 路径 4 完全没传 / 路径 5 冲突严判)· 3 新测试覆盖(同步默认值 + 冲突严判 + 向后兼容)· 9/9 质量门全绿(2273 passed / 1 skipped / 88.82% / mypy --strict 0 errors / 209 files / ruff 全绿 / alembic exit 0 / uv build OK / make lint 141 files 0 errors)· 撞坑累计 63 类(本轮新增 #63)· 状态三入口同步(R1/README + S/SESSION-STATE + M/MODIFICATION-LOG 顶部 v0.2.52 → v0.2.52.1)· 沿 v0.2.52 撞坑 #50 三层范本 + 撞坑 #51 漂移审查机制 | ✅ |
| 6/25 | 周四 | **v0.2.52.2 状态口径同步 + provider 封装硬化收口**(`0955f2e` feat + `a278ccc` docs)· `ProviderDefaults` dataclass + `smtp_provider`/`provider_defaults` 只读属性 · OutboxDispatcher 改读公共 API · `test_smpt_*` 拼写修正 · 9/9 质量门全绿(2273 passed / 1 skipped / 88.82% coverage / mypy --strict 0 errors / 209 files / MD lint 143 files 0 errors)| ✅ |
| 6/25 | 周四 | **v0.2.52.3 测试侧公共 API 一致性收口** · OutboxDispatcher 暴露公共 `active_provider` + `provider_defaults` 属性(沿 v0.2.52.2 ProviderDefaults 范本)· 5 处私有属性断言迁移到公共 API(`test_outbox_dispatcher.py` 3 处 + `test_send_adapter.py` 2 处)· 不再读 `_active_provider` / `_provider_default_*` 私有字段 · 与 EmailSendAdapter.provider_defaults 双端对称封装 · 9/9 质量门全绿(**2273 passed / 1 skipped / 88.84%** 微涨 0.02pp / mypy --strict 0 errors / 209 files / ruff 全绿 / alembic exit 0 / uv build OK / make lint **144 files** 0 errors)· 撞坑累计 **64 类**(本轮新增 #64 公共 API 迁移范本)· 状态三入口同步(R1/README + S/SESSION-STATE + M/MODIFICATION-LOG 顶部 v0.2.52.2 → v0.2.52.3)· 沿 v0.2.52.2 撞坑 #63 范本 | ✅ |
| 6/26 | 周五 | **v0.2.53.15 BusinessWriter Protocol + Stub + AuditContext + WriteResult/Decision 落地**(`approval_gate_passed` / `would_allow` 字段契约 · actor ≤ 80 / reason ≤ 240 严判 + 边界值测试 · 4 类动作 NotImplementedError 占位 · `896025e` · 3 files / +558 -1 · 9 质量门全绿 **2428 passed / 88.58%** / mypy --strict 0 / 110 files / MD lint 162 files / 撞坑 #65 沿用) | ✅ |
| 6/26 | 周五 | **v0.2.53.16 AnomalyDismissalService Protocol + Stub + 0015 alembic migration + AnomalyDismissal ORM**(`anomaly_dismissals` 表 + UNIQUE anomaly_id + idx_dismissed_at DESC + Stub 严判类型/长度 + head 推 0015 + 13 张表 baseline + 8 migration 测试修复 · `dc1544b` · 8 files / +551 -9 · 9 质量门全绿 **2446 passed / 88.50%** / mypy --strict 0 / 113 files / MD lint 162 files / 撞坑 #65 沿用) | ✅ |
| 6/26 | 周五 | **v0.2.53.17 BusinessWriterImpl 接入骨架**(默认 raise NotImplementedError · dry_run would_allow=False · 4 类动作方法占位 + 异常收容 · `cdd619e` · 2 files / +379 -0 · 9 质量门全绿 **2466 passed / 88.50%** / mypy --strict 0 / 114 files / MD lint 162 files / 撞坑 #65 + v0.2.53.8 单项降级沿用) | ✅ |
| 6/26 | 周五 | **v0.2.53.18 DashboardContext.with_business_writer() + resolve_business_writer() 集成**(默认 None → Stub · 不可变更新(沿 #64 范本)+ pass None 还原 Stub · `4463796` · 2 files / +146 -0 · 9 质量门全绿 **2475 passed / 88.50%** / mypy --strict 0 / 114 files / MD lint 162 files / 撞坑 #65 + #64 沿用) | ✅ |
| 6/26 | 周五 | **v0.2.53.19 ApprovalGate handler 路径 4 启用设计稿**(`4ee2a7f` · 1 file / +248 -0 · docs-only · 4 道门 + 4 类动作实际写入流程 + 7 错误码扩展 + 审计字段 + 实际写入留 8/1 后) | ✅ |
| 6/26 | 周五 | **v0.2.53.20 HTML 实写 audit log 落档设计稿**(`91a8f45` · 1 file / +250 -0 · docs-only · 3 类实写流程 + approval_gate_audits 表 + HTML inspector 升级 + 离线兜底 + 实际启用留 8/1 后 · 6 阶段路线收口) | ✅ |
| 6/29 | 周日 | **v0.2.53.51 audit 落档骨架**(`bcf7706` · feat dashboard · approval_gate_audits 表 + ApprovalGateAuditStore Protocol/Stub/InMemory + BusinessWriterImpl 4 动作成功/失败 audit 真实落档 + audit_id 字符串 `"audit:{id}"` 沿撞坑 #64 公共 API 范本 · 11 tests + 9 质量门全绿 **2576 passed / 88.84%** / mypy --strict 0 / 235 files / MD lint 192 files / 撞坑累计 70 类沿用 · 撞坑 #18 风险门控应用 · docs `docs/v0.2.53.51-audit-filing-skeleton-2026-06-29.md` 10 段) | ✅ |
| 6/30 | 周一 | **v0.2.53.52 Dashboard Audit UI**(`8b224a2` · feat dashboard · `GET /api/approval-gate/audits?limit=10` 端点 + `build_approval_gate_audits_payload` 响应 + `DashboardContext.audit_store` 字段 + `with_audit_store()` 不可变更新(撞坑 #64)+ `_try_build_audit_store()` 联动注入(BUSINESS_WRITER_ENABLED=1)+ HTML inspector `audit-card` + `renderAudits()` 8 端点 hydrate · 6 tests + 9 质量门全绿 **2582 passed / 88.92%** / mypy --strict 0 / 237 files / MD lint **193 files** · 撞坑累计 70 类沿用 · docs `docs/v0.2.53.52-dashboard-audit-ui-2026-06-30.md` 10 段 · §3.5 oauth2 误记已更正) | ✅ |
| 6/30 | 周一 | **v0.2.53.53 路径 4 实写 launch checklist v2**(`82574ec` · docs-only · 8/1 后启动用 · 5 门 v2 升级(DASHBOARD_WRITE_API + confirm_text + BUSINESS_WRITER_ENABLED + real_write_handler_enabled + 新增顶级 `ENABLE_PATH_4_WRITE=1`)+ 8 项前置条件(6 沿用 + 2 新增已落地)+ 8 步骤实施 checklist(4 已落地 + 4 剩余)+ 4 重防误发 + 实施失败回滚 plan(4 门任一未达 → 立即 raise NotImplementedError)· 不打 v0.2.x tag · 不移动 v0.1.0 tag · docs `docs/v0.2.53.53-path4-launch-checklist-2026-06-30.md` 271 lines) | ✅ |
| 6/30 | 周一 | **v0.2.55 Path 4 实写提前落地**(用户授权"8/1 的任务提前到今天" · handler 路径 4 `dry_run=false` 分发接通 · `ENABLE_PATH_4_WRITE=1` 第 5 门代码落地 · `/api/status` 暴露第 5 门与 `path4_write_ready` · 默认仍拒写 · 2591 passed / 88.85% / MD lint 200) | ✅ |
| 6/30 | 周一 | **v0.2.55.5 QQ SMTP 10 封 spike 收口**(`a0a4956` · 10 批 × 1 封 · `sent=10 tech_fail=0` · 撞坑 #78/#79 · 后续 90 封 **用户确认跳过**) | ✅ |
| 6/30 | 周一 | **v0.2.55.6 MODIFICATION-LOG 累计修正 + 项目检查漂移修复**(`39e36d6` · 三入口/quality_snapshot 同步 live 基线 2595/88.85%/203 md) | ✅ |
| 6/30 | 周一 | **v0.2.56 D5.6.3 spike 严判放宽设计 docs-only** — 设计 + @审计员 review PASS(撞坑 #78 · 9 重门控 · `--multi-confirm`) · 代码未改 · 等用户授权后实施 | ✅ |
| 6/30 | 周一 | **v0.2.56.1 D5.6.3 实施 + Phase 1 维持期锚定** — `spike_send_100.py` `--count 1-10` + `--multi-confirm` + 10 pytest · 2605 passed | ✅ |
| 6/30 | 周一 | **用户决策:90 封 QQ SMTP spike 跳过** — 不追加真实发送 · 10 封样本视为足够 · Phase 1 维持期继续 | ✅ |
| 6/30 | 周一 | **7/1 月度复盘提前执行收官**(用户授权"直接复盘")— 27 项决议维持 + 8 项专属议程 A1-A8 全部维持 + 议程 6 归档不执行(6/22 仅 9 天 · 远未到 1 月边界)+ 撞坑 #71/#76/#78/#79 沿用 + 8/1 不打 tag 维持 · reports/2026-07-01-monthly-review-decision.md 改为正式版 · 本棒三入口同步 + commit | ✅ |
| 7/2 | 周三 | **Phase 1 维持期第 1 次 weekly `make ci` 全绿** — 9 质量门 baseline 重验通过(2605 passed / 88.85% / MD lint 208 / mypy 0 errors / ruff 全绿 / alembic exit 0 / uv build OK)· 业务代码 0 改动 · 撞坑累计 #71/#76/#78/#79 沿用 · docs/v0.2.57-phase1-weekly-checkpoint-2026-07-02.md 新建(首个 weekly 周检范本)+ 三入口同步 + commit | ✅ |
| 7/9 | 周三 | **Phase 1 维持期第 2 次 weekly `make ci` 全绿** — 9 质量门 baseline 重验通过(2605 passed / 88.85% / MD lint 209 / mypy 0 errors / ruff 全绿 / alembic exit 0 / uv build OK)· 业务代码 0 改动 + 0 commit(本周无 commit)· 撞坑累计 #71/#76/#78/#79 沿用 · docs/v0.2.57.2-phase1-weekly-checkpoint-2026-07-09.md 新建(第 2 个 weekly 周检范本)+ 三入口同步 + commit | ✅ |
| 7/16 | 周三 | **Phase 1 维持期第 3 次 weekly `make ci` 全绿** — 9 质量门 baseline 重验通过(**2791 passed / 1 skipped / 89.09%** / **MD lint 256** / **mypy 248 files** / ruff 全绿 / alembic exit 0 / uv build OK)· 业务代码 0 改动 + 0 commit(本周无 commit · 沿 docs-only 规则)· 撞坑累计 **84 类**沿用(沿 7/3 收口基线)· docs/v0.2.57.3-phase1-weekly-checkpoint-2026-07-16.md 新建(第 3 个 weekly 周检范本)+ 三入口同步 + commit | ✅ |
| **7/8** | **周三** | **Phase 1 维持期第 3 次 weekly 提前 8 天预热启动 ✅** — 9 质量门 baseline 重验通过(**2904 passed / 1 skipped / 89.12%** / **MD lint 258** / **mypy 256 files** / ruff 全绿 / alembic exit 0 / uv build OK)· 业务代码 0 改动(撞坑 #71 docs-only 边界严判)· 撞坑累计 **85 类**沿用(`2c971e1` 撞坑 #85 三层防御 + `ae071f0` send_one_approved 收件人先校验 7/7 已 push)· docs/v0.2.57.3-phase1-weekly-checkpoint-2026-07-16.md 沿 7/8 preheat 实测 baseline 升级 + §0 7/8 preheat 段新增 + §11 send_one_approved 收件人校验补项 + §6 真实业务候选(阶段 1.2/1.3/3/4 均需单独授权)· **7/16 当天再做一次 docs-only 收口**(数字若变化以新 commit 沿 docs-only 规则更新本文件)· 三入口同步 + commit | ✅ |
| 8/1(本日-跨项目)| 周六 | **8/1 后 v0.2.x 链路收口跨项目沉淀 docs-only**(沿 `d879847` 范本 + `v0.2.2-p5-oauth-phase2-launch-2026-06-18` 7 段格式)— `Agent Assistant/L2_memory/_cross-project/v0.2.x-linkage-closure-2026-08-01.md` 新建(7 段 + 累计 commits 202+ + 撞坑 84 类沿用 + 8/1 选项 B 最终决策 + 10 项关键设计 + 8/1 后候选棒)+ 主项目 `docs/v0.2-launch-plan.md` 追加跨项目沉淀索引 + SESSION-STATE 同步 · docs-only · 业务代码 0 改动(撞坑 #71 沿用)· docs-only 不前进 pytest/coverage(撞坑 #50 第三/四层沿用)· 撞坑累计 84 类 0 新增 | ✅ |
| 7/23 | 周三 | **Phase 1 维持期收官前第 4 次 weekly `make ci` 全绿**(Phase 1 维持期 4/4 全收官) — 9 质量门 baseline 重验通过(2605 passed / 88.85% / MD lint 211 / mypy 0 errors / ruff 全绿 / alembic exit 0 / uv build OK)· 业务代码 0 改动 + 0 commit(连续 4 周 0 commit)· 撞坑累计 #71/#76/#78/#79 沿用 · docs/v0.2.57.4-phase1-weekly-checkpoint-2026-07-23.md 新建(Phase 1 收官前最后一次周检)+ 三入口同步 + commit | ✅ |
| 7/25 | 周六 | **阶段 3 第 1 次 A3 readiness docs-only 刷新** — 9 项前置条件实质满足(QQ-only 口径 · #2/#9 outlook/gmail 已豁免)· 撞坑累计 #71/#76/#78/#79 沿用 · 业务代码 0 改动 · docs/v0.2.58-a3-readiness-2026-07-25.md 新建 + 三入口同步 + commit | ✅ |
| 7/28 | 周二 | **阶段 3 第 2 次 A3 readiness docs-only 刷新** — 9/9 项实质满足沿用 · 撞坑累计 #71/#76/#78/#79 沿用 · docs/v0.2.58.2-a3-readiness-2026-07-28.md 新建 + 三入口同步 + commit | ✅ |
| 7/31 | 周五 | **阶段 3 第 3 次 A3 readiness docs-only 刷新**(阶段 3 收官) — 9/9 项实质满足沿用 · 撞坑累计 #71/#76/#78/#79 沿用(连续 5 周 0 新增)· docs/v0.2.58.3-a3-readiness-2026-07-31.md 新建 + 三入口同步 + commit | ✅ |
| 8/1 | 周六 | **阶段 4 · 8/1 release tag 评估 docs-only 收官**(不动 tag · 7/1 复盘决议 #25 维持) — 9/9 项 readiness 实质满足 · 撞坑累计 #71/#76/#78/#79 沿用(连续 6 周 0 新增)· docs/v0.2.59-8-1-tag-evaluation-2026-08-01.md 新建 + 三入口同步 + commit | ✅ |
| 7/1(本日)| 周三 | **v0.2.63 7/1 月度复盘正式 docs-only 收口**(用户授权「按推荐执行」= #1 + A 两步走 · 撞坑 #80 CLAUDE.md 阶段号漂移修复 + 9 节月度复盘沿 v0.2.62 范本)— 2 docs-only commits + CLAUDE.md L7/L16 翻 `v0.2.1-rc1` 维持期口径 + docs/v0.2.63-7-1-monthly-review-closure-2026-07-01.md 新建(10 节 · 撞坑 #80 沉淀)+ 三入口同步 + `v0.2.1` 仍不打(沿撞坑 #60)· 业务代码 0 改动 · docs-only 不前进 pytest/coverage(撞坑 #71 沿用)| ✅ |
| 7/1(本日-#2)| 周三 | **v0.2.64 `v0.2.1` 正式 tag 落地**(用户逐项授权「#2 OK 打 tag」+撞坑 #60 反转决议)— `git tag -a v0.2.1 71b4602 -m "..."` annotated tag + docs/v0.2.64-v0.2.1-tag-decision-execution-2026-07-01.md 新建(8 节)+ 三入口同步 + tag 列表翻牌(`v0.2.1` ❌ 不打 → ✅ 已落地)+ 9/9 readiness 实质满足 + 撞坑 #80 衍生闭环维持 · 业务代码 0 改动(连续 6 周 + 1 天 · 撞坑 #71 沿用)· 不可逆(本地删除需 `git tag -d` 强制)| ✅ |
| 7/1(本日-Day 1 阶段 1)| 周三 | **Day 1 阶段 1 基础设施落地(7 天计划启动 · 撞坑 #71 决议 B 范围内)**(用户授权「按这个计划执行」+ B+B+B 推荐组合)— `scripts/run_menu_bar.py` 新写(52 行 · 菜单栏常驻入口 · 撞坑 #71 docs-only 边界外基础设施文件)+ Makefile `menu-bar` target + `ops/day1-baseline.md` 新写(9 节)+ commit `b9e086a` · 9/9 质量门 baseline 不变(2611 / 88.95% / 230 md / 238 mypy)+ `make check-snapshot` 四重防御 OK · 业务代码 0 改动(Day 1 · 撞坑 #71 沿用)· 撞坑 #59 outlook-gmail 红线维持(本棒未触发)· **撞坑 #71 决议 B 明确:Day 1-2 基础设施放行,Day 3+ 业务功能 docs-only 待评审** · 撞坑累计 80 类 0 新增 | ✅ |
| 7/1(本日-Day 1 阶段 2)| 周三 | **Day 1 阶段 2 `.env` + Keychain + menu-bar 实测(撞坑 #59 QQ 例外激活)**(用户选 A 提供 LLM API Key + QQ 邮箱 + 16 位授权码 + 64 hex SQLCipher Key · 撞坑 #1 教训维持 · 不打印真实凭据到 chat/docs/commit)· `scripts/spike_set_smtp_password.py --provider qq --set-password` 写 Keychain(成功 · round-trip OK)+ `.env` 4 字段填齐(`MINIMAX_API_KEY` 125 chars / `IMAP_USER` 16 chars / `DB_PATH` / `DB_ENCRYPTION_KEY` 64 hex · `.gitignore` 保护)· SQLCipher decrypt OK · Keychain OK · `make menu-bar` 前台启动成功(肉眼确认图标)· `ops/day1-phase2-env.md` 新写(8 节)+ commit `9557179` · 9/9 质量门 baseline 不变(撞坑 #71 沿用)· **撞坑 #59 outlook/gmail 红线维持**(QQ SMTP 例外激活 · 不构成 outlook/gmail 真实凭据激活)· 撞坑累计 80 类 0 新增 | ✅ |
| 7/1(本日-Day 1 阶段 3)| 周三 | **Day 1 阶段 3 docs 同步(撞坑 #80 衍生 MD count 225→226)**(MD 撞坑 #50 漂移防御自动触发)+ 6 文件同步(CLAUDE.md L7/L16 + README.md L7 + SESSION-STATE.md L33 + MODIFICATION-LOG.md L116 + docs/v0.2-launch-plan.md L264 + `src/my_ai_employee/quality_snapshot.py` L21)+ commit `51ac171` · `make check-snapshot` 四重防御全绿 · 业务代码 0 改动(撞坑 #71 沿用)· 撞坑累计 80 类 0 新增 | ✅ |
| 7/1(本日-Day 2 预写)| 周三 | **Day 2 组件提前 — `ops/start-menubar.sh` 4 子命令闭环(撞坑 #71 B 放行 · docs-only 边界外基础设施文件)**(用户问「是否提前写 Day 2 组件」后立即执行)· `ops/start-menubar.sh` 新写(chmod +x · start/stop/status/restart + `--dry-run` + 颜色输出)+ `ops/day2-start-menubar-prereq.md` 新写(6 节 · 设计要点 + 实测闭环 4 步全绿 + Day 2 启动步骤 + 撞坑决议)+ commit `2f97fdd` · 撞坑 #71 决议 B 范围内 · 撞坑 #59 红线维持(本脚本不读真实凭据)· 撞坑 #50 漂移防御(本脚本不读 quality_snapshot)· 撞坑 #1 教训维持(本脚本不 echo 任何 Key)· 业务代码 0 改动 · 撞坑累计 80 类 0 新增 | ✅ |
| 7/1(本日-Day 2 启动)| 周三 | **Day 2 收口 — 菜单栏后台常驻 + 5 子模块代码路径验证(95%)**(用户确认「Day 2 启动 OK」+ `bash ops/start-menubar.sh start` → PID=38516 · status/stop 闭环 4 步全绿)· `ops/day2-closure.md` 新写(8 节 · Day 2 时段完成度 + 方案 A 启动实测 + 5 子模块测试 122 passed / 60 子测试 + 撞坑累计 + 9/9 质量门 baseline 维持)+ commit `dda81a6` · 撞坑 #59 红线部分激活(QQ SMTP Keychain 已就位 · outlook/gmail 仍维持)· 撞坑 #71 沿用 · 撞坑 #50 漂移防御 · 撞坑 #80 衍生 MD 漂移维持 · **业务风险类 0 新增** · 撞坑累计 80 类 0 新增 | ✅ |
| 7/1(本日-Day 2 撞坑 #81)| 周三 | **Day 2 B 操作「5 子模块点击无响应」撞坑沉淀(撞坑 #81 docs-only 新登记)**(用户实测:菜单栏后台启动成功(图标可见)但 ⌥⌘N + 5 菜单项点击 + 「退出」全无响应)· `ops/day2-b-no-response.md` 新写(6 节 · 现象表 + 3 候选根因分析 + 撞坑 #81 登记 + Day 2 收口验证清单 + Day 3 启动准备 + 维护者)+ commit `ddc4f8b` · 3 候选根因(未实测验证):① macOS TCC 辅助功能未授权(最可能)② macOS 焦点问题(Terminal 抢焦点)③ rumps 0.4.0 + Python 3.12 兼容性 · 不阻塞 Day 2 收口 100%(A OK + D 确认)· 业务代码 0 改动(撞坑 #71 沿用)· 撞坑累计 80 → **81**(撞坑 #81 docs-only 收口)· 9/9 质量门 baseline 不变(2611 / 88.95% / 229 md / 238 mypy) | ✅ |
| 7/1(本日-Day 2 撞坑 #81 修复准备)| 周三 | **Day 2 撞坑 #81 TCC 修复 runbook + 诊断脚本(用户选 B · Day 3 真发暂停等 #81 复测)**(用户决策点 B · 用户实测发现「TCC 应授权 Python.framework 3.12 而非 .venv/bin/python3」· 关键洞察 · 沿 v0.1-real-spike 范本)· `ops/check-pitfall-81.sh` 新写(93 行 · chmod +x · bash -n 通过 · 4 段诊断:菜单栏进程状态 + TCC 授权目标 + 最近日志 + 复测命令 + `--open` 深链)+ `ops/day2-81-tcc-fix-runbook.md` 新写(8 节 · 结论 + 实测进程链 + 修复步骤 0-5 + 复测清单 3 项 + 分支诊断 5A-5D + Day 3 门控关系 + 一键诊断脚本)+ `ops/day2-b-no-response.md` §5.2 翻牌「B 已选」+ commit `8af498e` · docs-only · 零业务风险(只改系统授权 + 重启进程 · 不发邮件 · 不写 DB)· 撞坑 #71 沿用 · 撞坑 #59 红线维持 · 撞坑累计 81 类 0 新增 · 9/9 质量门 baseline 不变 · 等用户完成 Step 1-5 + §4 三项打勾 → 回报「#81 复测通过」→ 再授权 Day 3 真发 | ✅ |
| 7/1(本日-Day 2 撞坑 #81 修复收口)| 周三 | **Day 2 撞坑 #81 TCC 修复收口(用户实测「3/3 通过」+ docs-only)**(用户完成 Step 1-3:TCC 补授权 Python.framework 3.12 → `make menu-bar` 前台启动 → 点击桌面失焦 → 测 3 项:①「系统健康」弹窗 ✅ · ②「授权引导」跳转系统设置 ✅ · ③ ⌥⌘N 有反馈 ✅)· `ops/day2-81-fix-closure.md` 新写(6 节 · 用户实测复测结果 + 修复路径 + 撞坑 #81 类别升级 + 撞坑累计更新 + Day 3 启动准备 + 9/9 质量门 baseline 维持)+ 6 文件 MD count 同步(231 → 232 · 撞坑 #50 漂移防御)+ `make check-snapshot` + `make lint` 四重防御全绿+ commit(预计)· docs-only · 零业务风险(只改系统授权 + 重启进程 · 不发邮件 · 不写 DB)· 撞坑 #71 沿用 · 撞坑 #59 红线维持 · 撞坑累计 81 类(撞坑 #81 收口不新增撞坑号)· 9/9 质量门 baseline 不变(2611 / 88.97% / 232 md / 238 mypy)· **Day 3 启动准备就位**:撞坑 #81 已修复 + 5 重门控待用户逐项 OK + IMAP/SMTP 真实凭据就位(Keychain 16 位授权码) | ✅ |
| 7/1(本日-Day 3 C 路径真发 1 封)| 周三 | **Day 3 C 路径真发 1 封收口(撞坑 #76/#78/#79 5 重门控全开 + 撞坑 #59 QQ 例外激活 + 撞坑 #81 已修复)**(用户决策点 C:SMTP 真发但不走 IMAP · 收件人=自己 477753009@qq.com · 5 重门控全 OK)· `SMTP_REAL_NETWORK=1 uv run python scripts/spike_send_100.py --real ...` 一次跑通 · **1 封 SENT 成功** · 报告 `output/spike/spike_send_100_20260701_140144.md`(6 项通过 + 1 项 REAL N/A)· `ops/day3-c-real-send-1-closure.md` + commit `e788c87`/`bcbbcb1`(口径修正 + quality_snapshot SMTP 文案)· 撞坑累计 81 类 0 新增 · **Day 4 启动准备就位** | ✅ |
| 7/1(本日-Day 4 财务+Notes)| 周三 | **Day 4 A 路径收口(财务 faker 2024/2025 导入 + 去重 + Notes spike + D8 异常 + 月报)**(沿 7 天计划 D4 · 选项 A)· wechat/alipay 2025+2024 导入 parsed=40 inserted=38 · 去重验证 duplicates=10 inserted=0 · Notes spike failed=0 skipped=30 · D8 3 kinds · 月报 `reports/finance-monthly-2026-06.md`(37 transactions)· `ops/day4-a-finance-notes-closure.md` 新写 · 真实 CSV/Notes 真同步 N/A(留 4 重门控)· 业务代码 0 改动(撞坑 #71 沿用)· 9/9 质量门 baseline 不变 | ✅ |
| 7/1(本日-Day 5 Dashboard)| 周三 | **Day 5 A 路径收口(Dashboard 只读驾驶舱 · DASHBOARD_REAL_DB=1)**(用户「Day 5 启动 OK」· 沿 7 天计划 D5 · 选项 A)· 主库 DB 打开 · 7 hydrate 端点 HTTP 200 + read_only 全 true · reports count=50 · Path 4 五门未误开 · `ops/day5-dashboard-closure.md` 新写 · 业务代码 0 改动(撞坑 #71 沿用)· MD 234→235 · 9/9 质量门 baseline 不变 | ✅ |

## 📋 6/24 下一棒(用户手动触发)

1. ✅ **手动 launchctl kickstart** — 补足真触发 1 次(沿 v0.2.10 + v0.2.21 选项 C launchctl print 10 维度验证已就绪)
2. ✅ **W3 真账单 spike 启动** — 2026-06-24 完成(`--max-rows 1` 跑通,详见 v0.2.32)
3. ✅ **v0.2.33-v0.2.36 阶梯验证 + 全量入库** — `--max-rows 5/10/25/49` 阶梯 1→5→10→25→49 五阶段全部收口 · 选项 B 路径 · 撞坑 #50/#52/#53/#54 沉淀
4. **outlook/gmail SMTP 真实发送 spike 启动** — 沿 v0.2.2 #8 工厂模式(`b2cf3c5`)+ OAuth/XOAUTH2 真链路(`9966ad0`)+ D5.6.5 4 重防误发范本
5. ✅ **D8 改进项延后**(2026-06-20 关闭 — `f0d8bd3` feat + docs closure · 沿 [[d4.7.4-v1.0.3-deferred]] 范本 · B 类自动解封)
6. **状态漂移审查机制实战演练**(沿 [[v0.2.4-drift-review-mechanism-2026-06-18]] §3 撞坑恢复 3 步范本 + §4 7/1 月度复盘 checklist)
7. ~~**P1-1 mypy tests 13 errors 修复**~~ ✅ 2026-07-01 已修复(14 errors → 0 · 撞坑 #31 · cast 范本)
8. ✅ **7/1 月度复盘提前执行** — B 类延后清单已三态归档(D4.7.4 v1.0.3 / W3 / mypy strict / SMTP provider 白名单已完成;真实 SMTP 送达继续延后)+ 状态漂移审查机制实战 + v0.2.1 release tag readiness 7/8 实质满足但暂不打 tag
8. ✅ **7/1 月度复盘提前执行** — B 类延后清单已三态归档(D4.7.4 v1.0.3 / W3 / mypy strict / SMTP provider 白名单已完成;真实 SMTP 送达继续延后)+ 状态漂移审查机制实战 + v0.2.1 release tag readiness 7/8 实质满足但暂不打 tag
9. ✅ **7/1 月度复盘提前执行收官(2026-06-30)** — 27 项决议维持 + 8 项专属议程 A1-A8 全维持 + 撞坑 #71/#76/#78/#79 沿用 + 8/1 不打 tag 维持 + Phase 1 维持期进行中
10. **8/1** — v0.2.1 release tag 锚定(沿 D5.7.2 范本,W3 真账单 spike 全量跑通 + outlook/gmail 真实 SMTP 发送 spike 跑通)

## 🔒 端午不休息期间禁止触碰(范围收窄)

- ❌ outlook/gmail SMTP provider 决策(单独门控)
- ❌ v0.1.0 tag 锚(2af775f 不动,沿 D5.7.2 范本)
- ❌ Agent Assistant 项目(7 文件夹重构 uncommitted churn,避免混合未提交变更)

**可继续**:
- ✅ v0.2.2+ 启动候选(候选 #5 OAuth Phase 2 docs-only 已启动 1 commit `b7b9ea7`,主代码 4 commits 沿 docs 6/19-22 实施)
- ✅ 真账单 spike(等用户提供真实 CSV)

## 🆘 6/23 重启后首查项

1. 读 `reports/v0.2.1-closure-2026-06-17.md`(9 段 11 表,128 行)
2. 读 `reports/v0.2.2-p0-l2-emit-2026-06-17.md`(v0.2.2 P0 收口 · 3 tests / 4 文件)
3. 读 `reports/v0.2.2-p2-1click-confirm-ui-2026-06-17.md`(v0.2.2 #2 收口 · 32 tests / 5 文件)
4. 读 `reports/v0.2.2-p3-l3-fuzzy-matching-2026-06-17.md`(v0.2.2 #3 收口 · 24 tests / 4 文件)
5. 读 `reports/v0.2.2-p6-badge-realtime-refresh-2026-06-17.md`(v0.2.2 #6 收口 · 17 tests / 3 文件)
6. 读 `reports/v0.2.2-p7-fk-circular-2026-06-18.md`(v0.2.2 #7 收口 · 0 tests / 1 文件 · 57→0 errors)
7. 读 `reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md`(v0.2.2 #5 commit 2 收口 · 12 tests / 2 文件 · +804)
8. 读 `reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md`(v0.2.2 #5 commit 4 收口 · 12 tests / 2 文件 · +1269)
9. 跑 `make test` 验证 9/9 质量门仍绿
10. 跑 `git status` 确认工作区 clean
11. 跑 `git tag --list` 确认 v0.1.0 = 2af775f 未动

## 📂 关键文件指针

- **本文件**: `我的AI员工/SESSION-STATE.md`
- **2026-07 月度复盘提前执行版**: `我的AI员工/reports/2026-07-monthly-review.md`
- **v0.2.1 docs 收口报告**: `我的AI员工/reports/v0.2.1-closure-2026-06-17.md`
- **v0.2.2 P0 收口报告**: `我的AI员工/reports/v0.2.2-p0-l2-emit-2026-06-17.md`
- **v0.2.2 #2 收口报告**: `我的AI员工/reports/v0.2.2-p2-1click-confirm-ui-2026-06-17.md`
- **v0.2.2 #3 收口报告**: `我的AI员工/reports/v0.2.2-p3-l3-fuzzy-matching-2026-06-17.md`
- **v0.2.2 #6 收口报告**: `我的AI员工/reports/v0.2.2-p6-badge-realtime-refresh-2026-06-17.md`
- **v0.2.2 #7 收口报告**: `我的AI员工/reports/v0.2.2-p7-fk-circular-2026-06-18.md`
- **v0.2.2 #5 commit 2 MicrosoftOAuth2 收口报告**: `我的AI员工/reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md`
- **v0.2.2 #5 commit 3 GoogleOAuth2 收口报告**: `我的AI员工/reports/v0.2.2-p5-oauth-google-2026-06-18.md`
- **v0.2.2 #5 commit 4 XOAUTH2 SMTP 鉴权集成收口报告**: `我的AI员工/reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md`
- **v0.2.2 #5 commit 5 OAuth 2.0 Phase 2 依赖加锁收口报告**: `我的AI员工/reports/v0.2.2-p5-oauth-deps-2026-06-18.md`
- **v0.2.2 #5 docs-only 启动文档**: `我的AI员工/docs/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md`
- **v0.2.2 #5 Agent Assistant 跨项目沉淀**: `Agent Assistant/L2_memory/_cross-project/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md`
- **v0.2.1 #3 ExpenseServiceStub 实化**: `de5de10`(12 new tests · 7 方法)
- **v0.2.1 #4 NoteStore 状态机化**: `0a1386c`(13 new tests · 5 状态机)
- **v0.2.1 #5 NoteStore L2/L3 跨源去重**: `75f87cc` + `b751820`(11 + 9 new tests)
- **v0.2.1 #3/#4/#5 docs-only 校准报告**: `我的AI员工/reports/v0.2.1-candidates-closure-2026-06-18.md`
- **v0.2.1+ L2 跨源写入**: `我的AI员工/reports/v0.2.1-l2-cross-source-write-2026-06-17.md`
- **v0.2.1 启动候选清单**: `我的AI员工/docs/v0.2.1-candidates-2026-06-17.md`
- **v0.2.52 SMTPProviderFactory 协议不匹配修复收口报告**: `我的AI员工/docs/v0.2.52-smtp-provider-factory-protocol-mismatch-2026-06-25.md`(撞坑 #61+#62+P1 状态三入口同步)
- **v0.2.52.1 OutboxDispatcher 自动路由收口报告**: `我的AI员工/docs/v0.2.52.1-outbox-dispatcher-auto-routing-2026-06-25.md`(撞坑 #63 5 路径严判)
- **v0.2.52.3 公共 API 一致性收口报告**: `我的AI员工/docs/v0.2.52.3-public-api-consistency-2026-06-25.md`(撞坑 #64 公共 API 迁移范本 + 5 处断言迁移)
- **v0.2 launch plan 整体收口**: `我的AI员工/reports/v0.2-closure-2026-06-18.md`(13 子阶段双链锚定 · 57 主项目 commits · 撞坑恢复范本)
- **v0.2.2 #8 SMTPProviderFactory 收口**: `我的AI员工/reports/v0.2.2-p8-smtp-provider-factory-2026-06-18.md`(撞坑恢复 commit · 10 new tests)
- **v0.2.4 状态漂移审查机制入库**: `我的AI员工/docs/v0.2.4-drift-review-mechanism-2026-06-18.md`(4 机制 + 7/1 月度复盘 checklist + 撞坑恢复 3 步范本)
- **v0.2.5 SMTP 真实发送 spike preflight**: `我的AI员工/docs/v0.2.5-smtp-real-send-preflight-2026-06-18.md`(4 模块链路核对 + 5 重防误发门控 + InMemory 5 封跑通 · 撞坑恢复 3 步实战演练 1)
- **v0.2.7 outlook/gmail SMTP 真实发送 spike 准备**: `我的AI员工/docs/v0.2.7-outlook-gmail-smtp-spike-prep-2026-06-21.md`(6 项启动条件 checklist + 5 重风险门控 + 3 个启动命令范本 · 撞坑恢复 3 步实战演练 2)
- **v0.2 release notes + v0.2.1 release tag 锚定策略**: `我的AI员工/docs/v0.2-release-notes-2026-06-22.md`(285 commits / 80 feat / 126 new tests / 8 大特性用户视角 + 8 项 tag 锚定前置条件 + B 类延后清单 5 项 7/1 评估方向)
- **v0.2.9 W3 真账单 spike 准备**: `我的AI员工/docs/v0.2.9-w3-real-bill-spike-prep-2026-06-22.md`(6 项启动条件 checklist + 4 重风险门控 + 3 个启动命令范本 + 5 阶段启动流程 · 撞坑恢复 3 步实战演练 3)
- **v0.2.10 全链路重启 checklist**: `我的AI员工/docs/v0.2.10-full-restart-checklist-2026-06-22.md`(6 模块链路核验 + 7 阶段启动 checklist + 3 真实 spike 启动路径 · 撞坑恢复 3 步实战演练 4)
- **v0.2.11 全链路重启 7 阶段 dry-run 预演**: `我的AI员工/docs/v0.2.11-7-stage-dry-run-2026-06-20.md`(4 个 dry-run 验证点结果 + 阶段 5/6/7 占位说明 · 撞坑恢复 3 步实战演练 5)
- **v0.2.12 6/23 全链路重启实战前置**: `我的AI员工/docs/v0.2.12-6-23-restart-prep-2026-06-20.md`(5 step 实战预演 + SIGKILL 137 误报处理 · 撞坑恢复 3 步实战演练 6)
- **v0.2.13 6/23 全链路重启实战手册**: `我的AI员工/docs/v0.2.13-6-23-restart-playbook-2026-06-20.md`(7 阶段实战手册 + 16 类撞坑汇总 · 撞坑恢复 3 步实战演练 7)
- **v0.2.14 E+A 实操就绪验证首次落地**: `我的AI员工/docs/v0.2.14-pitfall-recovery-drill-8-2026-06-20.md`(E+A 用户决策落地 + 撞坑 #1 SQLCIPHER_KEY + #16.5 ruff format + #18 ruff PATH 三类新撞坑真触发 + 真恢复 + 8/8 质量门 baseline 5/8 ✅ 实测 · 撞坑恢复 3 步实战演练 8 · 范本累计 8 个)
- **v0.2.15 A 候选 6/23 实操就绪最后冲刺**: `我的AI员工/docs/v0.2.15-A-sprint-restart-readiness-2026-06-20.md`(A 冲刺 6/20 当天完成不等 6/21 + 5 步骤全部完成 + 撞坑 #19 classifier 误判 + #20 classifier 双重混淆 + #21 pwd 漂移 + #22 grep 连写错误 四类新撞坑真触发 + 真恢复 + 8/8 质量门 baseline 6/8 ✅ 实测(从 5/8 推到 6/8)+ 阶段 1-5 实测就绪 · 撞坑恢复 3 步实战演练 9 · 范本累计 9 个 · 范本类型累计 5 类)
- **v0.2.16 7/1 月度复盘准备**: `我的AI员工/docs/v0.2.16-7-1-monthly-review-prep-2026-06-20.md`(5 复盘项全部预先 docs 化 + 7/1 12:00 启动 → 17:00 收官 + 提前 11 天 docs-only 准备避免当天突击 · 沿 [[v0.2.4-drift-review-mechanism-2026-06-18]] §3 + §4 + [[b-class-deferral-2026-06-09]] 范本)
- **v0.2 启动规划**: `我的AI员工/docs/v0.2-launch-plan.md`
- **v0.2.63 7/1 月度复盘正式 docs-only 收口**: `我的AI员工/docs/v0.2.63-7-1-monthly-review-closure-2026-07-01.md`(10 节 · 撞坑 #80 沉淀 · docs-only)
- **v0.2.64 `v0.2.1` 正式 tag 落地**: `我的AI员工/docs/v0.2.64-v0.2.1-tag-decision-execution-2026-07-01.md`(8 节 · 撞坑 #60 反转决议 · tag 列表翻牌 · docs-only 收口)
- **B 类决策延后**: `Agent Assistant/L2_memory/_core/b-class-deferral-2026-06-09.md`
- **环境误报诊断(本轮前置)**: `Agent Assistant/L2_memory/_core/2026-06-18-venv-sigkill-137-false-alarm.md`
- **6 重防误发范本(D6.6)**: `Agent Assistant/memory/2026-06-14-4-error-fixes.md`

## 维护者

**Mr-PRY** · 2026-06-30 端午不休息链路不停 + **v0.2.55 Path 4 实写提前落地(2026-06-30 · `bbd17f8` · 用户授权提前接通五门实写路径 · handler `dry_run=false` 分发 + `ENABLE_PATH_4_WRITE=1` 第 5 门 · `/api/status` 暴露 `path4_write_ready` · 默认仍拒写 · 2591 passed / 88.85% / MD lint 200 · 不打 tag)** + **v0.2.53.53 路径 4 实写 launch checklist v2 已收口(2026-06-30 · `82574ec` · docs-only · 5 门 v2 升级 + 8 步骤 checklist · 撞坑 #18 风险门控 · 不打 v0.2.x tag · 不移动 v0.1.0 tag)** + **v0.2.53.52 Dashboard Audit UI(2026-06-30 · `8b224a2` · GET /api/approval-gate/audits?limit=10 + audit-card + 6 tests · 撞坑 #64/#65 · 2582 passed / 88.92%)** + **v0.2.53.51 audit 落档骨架(2026-06-29 · `bcf7706` · approval_gate_audits 表 + ApprovalGateAuditStore Protocol/Stub/InMemory + BusinessWriterImpl 4 动作成功/失败 audit 真实落档 + audit_id 字符串 "audit:{id}" 沿撞坑 #64 公共 API 范本 · 11 tests · 9 质量门全绿 2576 passed / 88.84% / mypy --strict 0 / 235 files / MD lint 192 files / 撞坑累计 70 类沿用 · 撞坑 #18 风险门控应用)** + **v0.2.53.50 Dashboard 报告页搜索 UX 强化(`2950f6a` · 1 file / +89 -22 HTML · 排序/高亮/清除/匹配计数 4 状态映射)** + **v0.2.53.49 BusinessWriterImpl 写保护锁 + fake store 实写测试(`7fca5aa` · _real_write_handler_enabled=False 默认锁定 + 11 fake store tests)** + **v0.2.53.48 Dashboard 系统健康硬编码修复(`873d271`)** + **v0.2.53.47 状态快照同步(`a12f081` · 2546/88.83%/189 md)** + **v0.2.53.46 4 动作实写骨架跨项目 memory 沉淀(`6a6fffc`)** + **v0.2.53.46 撞坑 #50 第二/三层合并 quality_snapshot(`8edb592`)** + 2026-06-24 端午不休息 + **v0.2.36 W3 真账单 `--max-rows 49` 全量入库已收口(2026-06-24 · 选项 B 路径 · 真实支付宝 49 笔全量入库 → spike-49 跑通 `parsed=49 inserted=24 categorized=24 duplicates=25 needs_confirm=0 failed=0 candidate_count=0 version=2027` · 阶梯 1→5→10→25→49 五阶段范本 + 撞坑 #53 v2.0 跨 spike 累计公式 Σ(inserted) + Σ(duplicates) = Σ(max-rows) = 90 = 49 + 41 = 1+5+10+25+49 ✅ + 撞坑 #54 选项 B 优于选项 A 范本 · 撞坑 #50 双层防御范本沿用 · docs-only 收口 · 2265 passed / 1 skipped / 88.77% coverage / 0 mypy / 0 ruff / 0 MD lint · 撞坑累计 21 类(本轮新增 #54))** + **v0.2.35 W3 真账单 spike + 撞坑 #53 已沉淀(2026-06-24 · 阶梯 4 阶段范本 + 跨 spike 累计公式 v1.0 + v0.2.35 漂移小修 · docs-only 沿用)** + **v0.2.33 状态口径二次纠偏(`aa2a937` · docs-only · 撞坑 #50 第二层范本起点)** + **v0.2.34 W3 真账单 spike-10 阶梯验证(`bbb76a7` · docs-only)** + **v0.2.32 W3 真账单 spike + 撞坑 #49 已收口(2026-06-24 · 真实支付宝 62 笔 → `--max-rows 1` `parsed=1 inserted=1 categorized=1 version=2027` · detect_version 扫前 30 行 + `AlipayCSV2027RealParser` + 4 tests · 8 现有 2024/2025/2026 tests 全绿 · 2265 passed / 1 skipped / 0 mypy / 0 ruff / 0 MD lint · HEAD `5e25983` · 撞坑累计 16 类(本轮新增 #46/#47/#48/#49))** + **v0.2.31 候选 review 汇总闭环(`1e932c7` · 6 维度聚合 + review_decision 三分类 + 14 tests · 撞坑 #46/#47/#48)** + **v0.2.30 候选导出硬化(`5167163` · `.gitignore` 保护 + CLI 错误硬化)** + **v0.2.29 候选 review/export 机制(`dc40b7c` · 38 tests)** + **v0.2.28 L2 fingerprint sign-lock(`36d07ce` · 6 tests)** + **v0.2.25-v0.2.27 P0 二修 + W3 spike docs 链路 4 commit** + 2026-06-22 端午不休息 + **v0.2.14 E+A 实操就绪验证首次落地 docs-only(2026-06-20 端午不休息第 2-3 天锚定 · E+A 用户决策落地 + 撞坑 #1 SQLCIPHER_KEY + #16.5 ruff format + #18 ruff PATH 三类新撞坑真触发 + 真恢复 + 8/8 质量门 baseline 5/8 ✅ 实测 + 2/8 ⏸️ 沿 v0.2.13 baseline + 1/8 🟢 collect 漂移 + 撞坑恢复 3 步实战演练 8(范本累计 7 → 8 个 · 从"规划态"升级到"实测态")+ E+A 决策链 + 组合 4 推荐 + 撤销 E 边界补 docs)** + **v0.2.13 6/23 全链路重启实战手册 docs-only(7 阶段实战手册(每阶段精确命令 + 预期输出 + 撞坑处理 + 下一阶段门槛) + 16 类撞坑汇总 · 撞坑恢复 3 步实战演练 7)** + **v0.2.12 6/23 全链路重启实战前置 docs-only + dry-run 深化(5 step 实战预演(.env ✅ + 8/8 质量门 baseline 沿用 ✅ + launchd 5 源 ✅ + 菜单栏 5 子模块 ✅ + Notes 4 子模块 ✅) · SIGKILL 137 误报沿 [[2026-06-18-venv-sigkill-137-false-alarm]] 范本处理 · 撞坑恢复 3 步实战演练 6)** + **v0.2.11 全链路重启 7 阶段 dry-run 预演 docs-only(4 个 dry-run 验证点结果 + 阶段 5/6/7 占位说明 · 撞坑恢复 3 步实战演练 5)** + **v0.2.10 全链路重启 checklist docs-only(6 模块链路核验 + 7 阶段启动 checklist + 3 真实 spike 启动路径 · 撞坑恢复 3 步实战演练 4)** + **v0.2.9 W3 真账单 spike docs-only 准备(6 项启动条件 checklist + 4 重风险门控 + 3 个启动命令范本 + 5 阶段启动流程 · 撞坑恢复 3 步实战演练 3)** + **v0.2.8 release notes 收口 + v0.2.1 release tag 锚定策略同步 docs-only(285 commits / 80 feat / 126 new tests / 8 大特性用户视角 + 8 项 tag 锚定前置条件 + B 类延后清单 5 项 7/1 评估方向 · 沿 D5.7.2 范本 8/1 锚定)** + **v0.2.7 outlook/gmail SMTP 真实发送 spike 准备 docs-only(6 项启动条件 checklist + 5 重风险门控 + 3 个启动命令范本 + 5 阶段启动流程 · 撞坑恢复 3 步实战演练 2)** + **v0.2.6 D4.7.4 v1.0.3 改进项延后(2026-06-20 端午不休息第 3 天锚定 · B 类自动解封 + sensitive 词表 21→27 词 + factual 触发 4→7 正则 + 5 new tests)** + **v0.2.5 SMTP 真实发送 spike preflight docs-only(4 模块链路核对 + 5 重防误发门控 + InMemory 5 封跑通 · 撞坑恢复 3 步实战演练 1)** + **v0.2.4 状态漂移审查机制入库 docs(4 机制 + 7/1 月度复盘 checklist + 撞坑恢复 3 步范本)** + **v0.2 launch plan 整体收口 docs(57 主项目 commits · 13 子阶段双链锚定)** + **v0.2.2 #8 SMTPProviderFactory 撞坑恢复(`b2cf3c5` + `51da8fd` · 10 new tests)** + **v0.2.1 #3 ExpenseServiceStub 实化(`de5de10` · 12 tests) + v0.2.1 #4 NoteStore 状态机化(`0a1386c` · 13 tests) + v0.2.1 #5 NoteStore L2/L3 跨源去重(`75f87cc` + `b751820` · 11+9 tests)docs-only 校准** + v0.2.2 P0 关闭 + v0.2.2 #2 关闭 + v0.2.2 #3 关闭 + v0.2.2 #6 关闭 + v0.2.2 #7 关闭 + v0.2.2 #5 docs-only 启动(`b7b9ea7`) + v0.2.2 #5 commit 2 MicrosoftOAuth2 关闭(`c0f83d4`) + v0.2.2 #5 commit 3 GoogleOAuth2 关闭(`564b8db`) + v0.2.2 #5 commit 4 XOAUTH2 SMTP 鉴权集成关闭(`9966ad0`) + v0.2.2 #5 commit 5 OAuth 2.0 Phase 2 依赖加锁关闭(`6a0549e`)
**模型**:MiniMax-M3
**沿用范本**:[[~/.claude/CLAUDE.md]] §7 / [[d5.7.2-docs-only-closure]] / [[b-class-deferral-2026-06-09]] / [[d5.6.3-p1-1-5-changes]] / [[d8.3-anomaly-alert]] / [[d9.3-expense-service-protocol]] / [[d6.4-transactions-l2]] / [[d9.5-double-process-pattern]] / [[2026-06-18-venv-sigkill-137-false-alarm]]
