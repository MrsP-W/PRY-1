# 我的AI员工 - Makefile
# 用法：make <target>
#
# Python 解释器自动检测：
#   1. 优先用 .venv/bin/python（项目本地 venv）
#   2. 否则用 poetry run python
#   3. 都没有则降级到 python3

# ===== 自动检测 Python =====
PYTHON := $(shell \
    if [ -x .venv/bin/python ]; then \
        echo ".venv/bin/python"; \
    elif command -v poetry >/dev/null 2>&1; then \
        echo "poetry run python"; \
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
	@echo ""
	@echo "  $(GREEN)make hello$(RESET)    验证项目跑通（Hello, 我的AI员工）"
	@echo "  $(GREEN)make dev$(RESET)      启动开发模式（hot reload）"
	@echo "  $(GREEN)make test$(RESET)     跑 pytest 单元测试 + 覆盖率"
	@echo "  $(GREEN)make lint$(RESET)     Markdown 格式检查（基于 .markdownlint.json）"
	@echo "  $(GREEN)make run$(RESET)      启动主程序（占位）"
	@echo "  $(GREEN)make install-hooks$(RESET) 安装 pre-commit hook（自动 MD lint）"
	@echo "  $(GREEN)make clean$(RESET)    清理临时文件（__pycache__/、*.log、*.tmp）"
	@echo "  $(GREEN)make info$(RESET)     显示项目信息（Python 版本 + 关键路径）"
	@echo "  $(GREEN)make venv$(RESET)     创建项目本地 venv（.venv/）"
	@echo "  $(GREEN)make install$(RESET)  安装依赖到 venv"
	@echo "  $(GREEN)make help$(RESET)     显示本帮助"
	@echo ""
	@echo "$(BOLD)📖 文档$(RESET)：README.md / docs/architecture.md / docs/week1-mvp.md"

.PHONY: hello
hello: ## 验证项目跑通
	@echo "$(BLUE)🚀 启动我的AI员工…$(RESET)"
	@$(PYTHON) -m src.main
	@echo "$(GREEN)✅ 跑通！$(RESET)"

.PHONY: dev
dev: ## 开发模式（hot reload）
	@echo "$(BLUE)🔧 启动开发模式（watchdog 监控文件变化）$(RESET)"
	@$(PYTHON) -m pip install watchdog >/dev/null 2>&1 || true
	@$(PYTHON) -m watchmedo auto-restart \
		--directory=src/ \
		--pattern='*.py' \
		--recursive \
		-- $(PYTHON) -m src.main

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
	@command -v markdownlint-cli2 >/dev/null 2>&1 && \
		markdownlint-cli2 "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || \
		npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#data" "#.venv" "#dist"
	@echo "$(GREEN)✅ 0 错误$(RESET)"

.PHONY: lint-fix
lint-fix: ## 自动修复 MD 格式
	@command -v markdownlint-cli2 >/dev/null 2>&1 && \
		markdownlint-cli2 --fix "**/*.md" "#node_modules" "#data" "#.venv" "#dist" || \
		npx --yes markdownlint-cli2 --fix "**/*.md" "#node_modules" "#data" "#.venv" "#dist"

.PHONY: run
run: ## 启动主程序（占位）
	@echo "$(YELLOW)⏳ 主程序占位 — Week 1 D5 接入菜单栏后可用$(RESET)"
	@$(PYTHON) -m src.main --interactive

.PHONY: info
info: ## 显示项目信息
	@echo "$(BOLD)📋 项目信息$(RESET)"
	@echo "  Python:    $$($(PYTHON) --version 2>&1)"
	@echo "  Makefile:  $(CURDIR)/Makefile"
	@echo "  工作目录:  $(CURDIR)"
	@echo "  venv:      .venv/  (存在：$$(test -d .venv && echo '✅' || echo '❌'))"
	@echo "  数据目录:  $$HOME/Library/Application Support/我的AI员工/"

.PHONY: venv
venv: ## 创建项目本地 venv（推荐）
	@echo "$(BLUE)🐍 创建项目 venv（.venv/）$(RESET)"
	@if command -v uv >/dev/null 2>&1; then \
		uv venv .venv --python 3.14; \
	else \
		$(PYTHON) -m venv .venv; \
	fi
	@echo "$(GREEN)✅ venv 创建完成$(RESET)"

.PHONY: install
install: ## 安装依赖到 venv
	@echo "$(BLUE)📦 安装依赖$(RESET)"
	@if [ -x .venv/bin/python ] && command -v uv >/dev/null 2>&1; then \
		uv pip install --python .venv/bin/python -e ".[dev]"; \
	elif [ -x .venv/bin/python ]; then \
		.venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1; \
		.venv/bin/python -m pip install -e ".[dev]"; \
	else \
		echo "$(YELLOW)⚠️  无 .venv，先 make venv$(RESET)"; \
		exit 1; \
	fi
	@echo "$(GREEN)✅ 依赖安装完成$(RESET)"

.PHONY: install-hooks
install-hooks: ## 安装 pre-commit hook
	@echo "$(BLUE)🔗 安装 pre-commit hook（commit 前自动 MD lint）$(RESET)"
	@mkdir -p .git/hooks
	@cp scripts/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "$(GREEN)✅ Hook 已安装$(RESET)"

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
