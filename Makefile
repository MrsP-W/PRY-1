# 我的AI员工 - Makefile
# 用法：make <target>
#
# 依赖管理：D1.1 切换为 PEP 621 + uv（提交 uv.lock）
# Python 解释器自动检测：
#   1. 优先用 .venv/bin/python（uv 创建的项目本地 venv）
#   2. 否则用 uv run python（无 venv 时自动创建临时环境）
#   3. 都没有则降级到 python3（应急版）

# ===== 自动检测 Python =====
PYTHON := $(shell \
    if [ -x .venv/bin/python ]; then \
        echo ".venv/bin/python"; \
    elif command -v uv >/dev/null 2>&1; then \
        echo "uv run python"; \
    else \
        echo "python3"; \
    fi)

# ===== 颜色 =====
ifneq ($(TERM),dumb)
    BOLD := \033[1m
    GREEN := \033[32m
    YELLOW := \033[33m
    BLUE := \033[34m
    RED := \033[31m
    RESET := \033[0m
endif

.DEFAULT_GOAL := help

.PHONY: help
help: ## 显示帮助
	@echo "$(BOLD)📋 我的AI员工 — 可用命令$(RESET)"
	@echo ""
	@echo "  当前 Python: $(GREEN)$(PYTHON)$(RESET)"
	@echo "  包结构:      $(GREEN)my_ai_employee (src/my_ai_employee/main.py)$(RESET)"
	@echo ""
	@echo "  $(GREEN)make hello$(RESET)    验证项目跑通（Hello, 我的AI员工）"
	@echo "  $(GREEN)make dev$(RESET)      启动开发模式（hot reload）"
	@echo "  $(GREEN)make test$(RESET)     跑 pytest 单元测试 + 覆盖率"
	@echo "  $(GREEN)make lint$(RESET)     Markdown 格式检查（基于 .markdownlint.json）"
	@echo "  $(GREEN)make run$(RESET)      启动主程序（占位）"
	@echo "  $(GREEN)make install-hooks$(RESET) 安装 pre-commit hook（自动 MD lint）"
	@echo "  $(GREEN)make clean$(RESET)    清理临时文件（__pycache__/、*.log、*.tmp）"
	@echo "  $(GREEN)make sync-notes$(RESET) D9.2 — Apple Notes 正常同步(真 AppleScript 调 Notes.app)"
	@echo "  $(GREEN)make spike-notes$(RESET) D9.2 — Apple Notes spike(30 笔 faker 跑通链路,Mock runner)"
	@echo "  $(GREEN)make test-notes$(RESET) D9.2 — Apple Notes 测试套件(12 cases:7 HTML cleaner + 5 CLI)"
	@echo "  $(GREEN)make monthly-report$(RESET) D10.2 — 数字生活月报生成(沿 D5.6.5 4 退出码范本)"
	@echo "  $(GREEN)make validate-monthly$(RESET) D10.2 — 校验月报模板必含占位符"
	@echo "  $(GREEN)make spike-b5-quartz$(RESET) v0.2 B-5 — ⌥⌘N Quartz CGEvent tap S7 真链路 spike"
	@echo "  $(GREEN)make spike-d8-anomaly$(RESET) v0.2 D8.4 — S11 智能财务异常检测 spike(AnomalyDetector 真链路)"
	@echo "  $(GREEN)make mypy$(RESET)     9 质量门 — mypy 类型检查（严格模式）"
	@echo "  $(GREEN)make ruff$(RESET)     9 质量门 — ruff lint 检查"
	@echo "  $(GREEN)make format$(RESET)   9 质量门 — ruff format 检查(--check 模式)"
	@echo "  $(GREEN)make coverage$(RESET) 9 质量门 — pytest + 覆盖率 fail_under=80%"
	@echo "  $(GREEN)make alembic$(RESET)  9 质量门 — alembic upgrade head --sql 验证"
	@echo "  $(GREEN)make build$(RESET)    9 质量门 — uv build 本地构建 wheel + sdist"
	@echo "  $(GREEN)make dashboard-api$(RESET) v0.2.53.2 P2 — 本地 Dashboard 只读 API(127.0.0.1:8765)"
	@echo "  $(GREEN)make menu-bar$(RESET)  Day 1 — 启动菜单栏常驻(前台;后台用 nohup 或 ops/start-menubar.sh)"
	@echo "  $(GREEN)make setup$(RESET)     Day 1.2 — 完全体首次配置向导(Keychain + DB + TCC)"
	@echo "  $(GREEN)make setup-check$(RESET) Day 1.2 — 只检查 Keychain 现状(零副作用)"
	@echo "  $(GREEN)make setup-tcc$(RESET)  Day 1.2 — 只打印 macOS TCC 授权引导"
	@echo "  $(GREEN)make setup-verify-db$(RESET) Day 1.4 — 三表只读验收(schema+索引+行数)"
	@echo "  $(GREEN)make info$(RESET)     显示项目信息（Python 版本 + 关键路径）"
	@echo "  $(GREEN)make venv$(RESET)     创建项目本地 venv（uv venv, Python 3.12）"
	@echo "  $(GREEN)make install$(RESET)  同步依赖到 venv（uv sync --extra dev）"
	@echo "  $(GREEN)make help$(RESET)     显示本帮助"
	@echo ""
	@echo "$(BOLD)📖 文档$(RESET)：README.md / docs/architecture.md / docs/week1-mvp.md"

.PHONY: hello
hello: ## 验证项目跑通
	@echo "$(BLUE)🚀 启动我的AI员工…$(RESET)"
	@$(PYTHON) -m my_ai_employee.main
	@echo "$(GREEN)✅ 跑通！$(RESET)"

.PHONY: dev
dev: ## 开发模式（hot reload）
	@echo "$(BLUE)🔧 启动开发模式（watchdog 监控文件变化）$(RESET)"
	@$(PYTHON) -m watchmedo auto-restart \
		--directory=src/ \
		--pattern='*.py' \
		--recursive \
		-- $(PYTHON) -m my_ai_employee.main

.PHONY: dashboard-api
dashboard-api: ## v0.2.53.2 P2 — 本地 Dashboard 只读 API
	@echo "$(BLUE)🌐 Dashboard 只读 API(127.0.0.1:8765)$(RESET)"
	@$(PYTHON) -m my_ai_employee.dashboard.server

.PHONY: menu-bar
menu-bar: ## Day 1 — 启动菜单栏常驻(前台,Ctrl+C 退出;后台用 nohup 或 ops/start-menubar.sh)
	@echo "$(BLUE)🍎 启动菜单栏常驻(Day 1 基础设施)$(RESET)"
	@$(PYTHON) scripts/run_menu_bar.py

.PHONY: setup
setup: ## Day 1.2 — 完全体首次配置向导(Keychain + DB 初始化 + TCC 引导)
	@echo "$(BLUE)🍎 完全体首次配置向导(Day 1.2)$(RESET)"
	@$(PYTHON) scripts/setup_wizard.py

.PHONY: setup-check
setup-check: ## Day 1.2 — 只检查 Keychain 现状(零副作用)
	@$(PYTHON) scripts/setup_wizard.py --check-only

.PHONY: setup-tcc
setup-tcc: ## Day 1.2 — 只打印 macOS TCC 授权引导
	@$(PYTHON) scripts/setup_wizard.py --tcc-only

.PHONY: setup-verify-db
setup-verify-db: ## Day 1.4 — 只读验收 transactions/notes/outbox schema+索引+行数
	@echo "$(BLUE)🔍 Day 1.4 三表只读验收(不写库)$(RESET)"
	@$(PYTHON) scripts/verify_day14_db_tables.py

.PHONY: test
test: ## 跑单元测试
	@echo "$(BLUE)🧪 跑 pytest 单元测试 + 覆盖率$(RESET)"
	@$(PYTHON) -m pytest

.PHONY: test-verbose
test-verbose: ## 跑测试（详细输出）
	@$(PYTHON) -m pytest -v --tb=long

.PHONY: lint
lint: ## Markdown 格式检查（仅 git tracked *.md，对齐 git ls-files）
	@echo "$(BLUE)📝 检查 Markdown 格式$(RESET)"
	@if [ -z "$$(git ls-files '*.md')" ]; then \
		echo "$(YELLOW)⚠️ 无 tracked Markdown 文件，跳过$(RESET)"; \
		exit 0; \
	fi; \
	if [ -x node_modules/.bin/markdownlint-cli2 ]; then \
		git ls-files -z '*.md' | xargs -0 node_modules/.bin/markdownlint-cli2 || exit 1; \
	elif command -v markdownlint-cli2 >/dev/null 2>&1; then \
		git ls-files -z '*.md' | xargs -0 markdownlint-cli2 || exit 1; \
	else \
		echo "$(RED)❌ markdownlint-cli2 未安装$(RESET)"; \
		echo "  $(YELLOW)请先跑: make install-npm$(RESET)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✅ 0 错误$(RESET)"

.PHONY: lint-fix
lint-fix: ## 自动修复 MD 格式（仅 git tracked *.md）
	@if [ -z "$$(git ls-files '*.md')" ]; then \
		echo "$(YELLOW)⚠️ 无 tracked Markdown 文件，跳过$(RESET)"; \
		exit 0; \
	fi; \
	if [ -x node_modules/.bin/markdownlint-cli2 ]; then \
		git ls-files -z '*.md' | xargs -0 node_modules/.bin/markdownlint-cli2 --fix || exit 1; \
	elif command -v markdownlint-cli2 >/dev/null 2>&1; then \
		git ls-files -z '*.md' | xargs -0 markdownlint-cli2 --fix || exit 1; \
	else \
		echo "$(RED)❌ markdownlint-cli2 未安装$(RESET)"; \
		echo "  $(YELLOW)请先跑: make install-npm$(RESET)"; \
		exit 1; \
	fi

.PHONY: run
run: ## 启动主程序（占位）
	@echo "$(YELLOW)⏳ 主程序占位 — Week 1 D5 接入菜单栏后可用$(RESET)"
	@$(PYTHON) -m my_ai_employee.main --interactive

.PHONY: info
info: ## 显示项目信息
	@echo "$(BOLD)📋 项目信息$(RESET)"
	@echo "  Python:    $$($(PYTHON) --version 2>&1)"
	@echo "  Makefile:  $(CURDIR)/Makefile"
	@echo "  工作目录:  $(CURDIR)"
	@echo "  venv:      .venv/  (存在：$$(test -d .venv && echo '✅' || echo '❌'))"
	@echo "  uv.lock:   $$([ -f uv.lock ] && echo '✅ 已锁版本' || echo '⚠️  未生成')"
	@echo "  数据目录:  $$HOME/Library/Application Support/我的AI员工/"

.PHONY: venv
venv: ## 创建项目本地 venv（Python 3.12，uv 推荐）
	@echo "$(BLUE)🐍 创建项目 venv（Python 3.12 + uv）$(RESET)"
	@if command -v uv >/dev/null 2>&1; then \
		uv venv .venv --python 3.12; \
	else \
		$(PYTHON) -m venv .venv; \
	fi
	@echo "$(GREEN)✅ venv 创建完成$(RESET)"

.PHONY: install
install: ## 同步依赖到 venv（uv sync --extra dev + 可编辑安装本项目）
	@echo "$(BLUE)📦 同步依赖到 venv（uv sync --extra dev + pip install -e .）$(RESET)"
	@if command -v uv >/dev/null 2>&1; then \
		uv sync --extra dev && \
		uv pip install --python .venv/bin/python -e .; \
	elif [ -x .venv/bin/python ]; then \
		.venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1; \
		.venv/bin/python -m pip install -e ".[dev]"; \
	else \
		echo "$(YELLOW)⚠️  无 uv 无 .venv，先 make venv$(RESET)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✅ 依赖安装完成（uv.lock 已锁版本 + 项目可编辑安装）$(RESET)"

.PHONY: install-npm
install-npm: ## 安装 npm 依赖（markdownlint-cli2）
	@echo "$(BLUE)📦 安装 npm 依赖（markdownlint-cli2）$(RESET)"
	@if command -v npm >/dev/null 2>&1; then \
		npm install; \
	else \
		echo "$(RED)❌ npm 未安装，请先装 Node.js$(RESET)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✅ npm 依赖已装（node_modules/ + package-lock.json）$(RESET)"

.PHONY: install-hooks
install-hooks: ## 安装 pre-commit hook
	@echo "$(BLUE)🔗 安装 pre-commit hook（commit 前自动 MD lint）$(RESET)"
	@mkdir -p .git/hooks
	@cp scripts/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "$(GREEN)✅ Hook 已安装$(RESET)"

.PHONY: sync-notes
sync-notes: ## D9.2 — Apple Notes 正常同步(真 AppleScript 调 Notes.app)
	@echo "$(BLUE)📝 同步 Apple Notes 到 notes 表(4 退出码契约)$(RESET)"
	@$(PYTHON) scripts/sync_notes.py sync

.PHONY: spike-notes
spike-notes: ## D9.2 — Apple Notes spike(30 笔 faker,Mock runner 跑通链路)
	@echo "$(BLUE)🧪 Apple Notes spike(30 笔 faker,验证 insert 链路)$(RESET)"
	@$(PYTHON) scripts/sync_notes.py spike --n 30

.PHONY: test-notes
test-notes: ## D9.2 — Apple Notes 测试套件(12 cases)
	@echo "$(BLUE)🧪 跑 Apple Notes 测试(7 HTML cleaner + 5 CLI 集成)$(RESET)"
	@$(PYTHON) -m pytest tests/scripts/test_sync_notes.py -v --no-cov

.PHONY: monthly-report
monthly-report: ## D10.2 — 数字生活月报生成(沿 D5.6.5 4 退出码范本)
	@echo "$(BLUE)📊 生成当月数字生活月报(默认上月)$(RESET)"
	@$(PYTHON) -m scripts.monthly_report generate --month $$(date -v-1d +%Y-%m 2>/dev/null || date -d 'last month' +%Y-%m)

.PHONY: validate-monthly
validate-monthly: ## D10.2 — 校验月报模板必含占位符(10 占位符)
	@echo "$(BLUE)✅ 校验月报模板(10 占位符)$(RESET)"
	@$(PYTHON) -m scripts.monthly_report validate

.PHONY: spike-b5-quartz
spike-b5-quartz: ## v0.2 B-5 — ⌥⌘N Quartz CGEvent tap S7 真链路 spike(沿 D9.5 spike 范本)
	@echo "$(BLUE)🧪 v0.2 B-5 S7 ⌥⌘N Quartz CGEvent tap spike$(RESET)"
	@$(PYTHON) -m scripts.spike_b5_quartz --n 30

.PHONY: spike-d8-anomaly
spike-d8-anomaly: ## v0.2 D8.4 — S11 智能财务异常检测真链路 spike(35 baseline + 1 ¥888 异常笔)
	@echo "$(BLUE)🧪 v0.2 D8.4 S11 AnomalyDetector spike$(RESET)"
	@$(PYTHON) -m scripts.spike_d8_anomaly --db-path /tmp/spike_d8_$(shell date +%Y%m%d_%H%M%S).db

# ===== 9 质量门补齐(v0.2 B-5 + D8 实施前置)=====

# P0-4 只读 launchd 健康采样器位于 scripts/，不纳入历史 CLI/spike 脚本范围；
# 因此在常规 Ruff、format 与 mypy 门中显式覆盖，避免质量漂移漏检。
P0_4_HEALTH_SAMPLE := scripts/sample_launchd_health.py

.PHONY: mypy
mypy: ## 9 质量门 — mypy 类型检查(严格模式 `--strict`,沿 v0.2.42 范本:43 errors 清零 + 失败即阻塞)
	@echo "$(BLUE)🔍 mypy 类型检查(严格模式 --strict)$(RESET)"
	@$(PYTHON) -m mypy --strict src tests $(P0_4_HEALTH_SAMPLE)

.PHONY: ruff
ruff: ## 9 质量门 — ruff lint 检查
	@echo "$(BLUE)🔍 ruff lint 检查$(RESET)"
	@$(PYTHON) -m ruff check src tests $(P0_4_HEALTH_SAMPLE)

.PHONY: format
format: ## 9 质量门 — ruff format 检查(--check 模式)
	@echo "$(BLUE)📐 ruff format 检查(--check 模式)$(RESET)"
	@$(PYTHON) -m ruff format --check src tests $(P0_4_HEALTH_SAMPLE)

.PHONY: format-fix
format-fix: ## ruff format 自动修复
	@$(PYTHON) -m ruff format src tests $(P0_4_HEALTH_SAMPLE)

.PHONY: coverage
coverage: ## 9 质量门 — pytest + 覆盖率 fail_under=80%(沿 v0.1 范本;--cov 见 pyproject addopts)
	@echo "$(BLUE)📊 pytest + 覆盖率检查(fail_under=80)$(RESET)"
	@$(PYTHON) -m pytest --cov-fail-under=80

.PHONY: alembic
alembic: ## 9 质量门 — alembic upgrade head --sql 验证迁移可干净执行
	@echo "$(BLUE)🗄️  alembic upgrade head --sql(验证迁移可干净执行;v0.2.52 P2 修:先写临时文件再 head 避免 head 吃退出码)$(RESET)"
	@$(PYTHON) -m alembic upgrade head --sql > /tmp/alembic_head.sql 2>&1 ; status=$$? ; head -50 /tmp/alembic_head.sql ; exit $$status

.PHONY: alembic-upgrade-head
alembic-upgrade-head: ## alembic upgrade head(真跑迁移)
	@$(PYTHON) -m alembic upgrade head

.PHONY: alembic-downgrade-1
alembic-downgrade-1: ## alembic downgrade -1(回滚 1 个 revision)
	@$(PYTHON) -m alembic downgrade -1

.PHONY: build
build: ## 9 质量门 — uv build 本地构建 wheel + sdist(沿 D1.1 范本)
	@echo "$(BLUE)📦 uv build 本地构建(沿 D1.1 范本)$(RESET)"
	@if command -v uv >/dev/null 2>&1; then \
		uv build; \
	else \
		$(PYTHON) -m pip wheel . -w dist --no-deps; \
	fi
	@echo "$(GREEN)✅ 构建完成(见 dist/)$(RESET)"

.PHONY: check-snapshot
check-snapshot: ## 校验 quality_snapshot + 状态入口文档与 live baseline 对齐
	@echo "$(BLUE)🔍 quality_snapshot 防漂移检查$(RESET)"
	@$(PYTHON) scripts/check_quality_snapshot.py

.PHONY: ci
ci: ## 9 质量门 — 一键跑 9 质量门全链(沿 v0.1.0-preseal-runbook 范本)
	@echo "$(BOLD)🚀 9 质量门一键跑$(RESET)"
	@# coverage 已执行全量 pytest；ci 不重复调用 test，保留其作为独立入口。
	@$(MAKE) mypy
	@$(MAKE) ruff
	@$(MAKE) format
	@$(MAKE) coverage
	@$(MAKE) lint
	@$(MAKE) check-snapshot
	@$(MAKE) alembic
	@$(MAKE) build
	@echo "$(GREEN)✅ 9 质量门全绿$(RESET)"

.PHONY: clean
clean: ## 清理临时文件
	@echo "$(BLUE)🧹 清理临时文件$(RESET)"
	@find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.log" -not -path "./.venv/*" -delete 2>/dev/null || true
	@find . -type f -name "*.tmp" -not -path "./.venv/*" -delete 2>/dev/null || true
	@find . -type f -name "*.swp" -not -path "./.venv/*" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -not -path "./.venv/*" -delete 2>/dev/null || true
	@rm -rf htmlcov/ dist/ build/ *.egg-info 2>/dev/null || true
	@echo "$(GREEN)✅ 清理完成$(RESET)"
