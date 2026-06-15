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

.PHONY: test
test: ## 跑单元测试
	@echo "$(BLUE)🧪 跑 pytest 单元测试 + 覆盖率$(RESET)"
	@$(PYTHON) -m pytest

.PHONY: test-verbose
test-verbose: ## 跑测试（详细输出）
	@$(PYTHON) -m pytest -v --tb=long

.PHONY: lint
lint: ## Markdown 格式检查
	@echo "$(BLUE)📝 检查 Markdown 格式$(RESET)"
	@if [ -x node_modules/.bin/markdownlint-cli2 ]; then \
		node_modules/.bin/markdownlint-cli2 "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || exit 1; \
	elif command -v markdownlint-cli2 >/dev/null 2>&1; then \
		markdownlint-cli2 "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || exit 1; \
	else \
		echo "$(RED)❌ markdownlint-cli2 未安装$(RESET)"; \
		echo "  $(YELLOW)请先跑: make install-npm$(RESET)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✅ 0 错误$(RESET)"

.PHONY: lint-fix
lint-fix: ## 自动修复 MD 格式
	@if [ -x node_modules/.bin/markdownlint-cli2 ]; then \
		node_modules/.bin/markdownlint-cli2 --fix "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || exit 1; \
	elif command -v markdownlint-cli2 >/dev/null 2>&1; then \
		markdownlint-cli2 --fix "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || exit 1; \
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
	@$(PYTHON) -m pytest tests/scripts/test_sync_notes.py -v

.PHONY: monthly-report
monthly-report: ## D10.2 — 数字生活月报生成(沿 D5.6.5 4 退出码范本)
	@echo "$(BLUE)📊 生成当月数字生活月报(默认上月)$(RESET)"
	@$(PYTHON) -m scripts.monthly_report generate --month $$(date -v-1d +%Y-%m 2>/dev/null || date -d 'last month' +%Y-%m)

.PHONY: validate-monthly
validate-monthly: ## D10.2 — 校验月报模板必含占位符(10 占位符)
	@echo "$(BLUE)✅ 校验月报模板(10 占位符)$(RESET)"
	@$(PYTHON) -m scripts.monthly_report validate

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
