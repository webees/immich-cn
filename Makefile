PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install lint format typecheck test docs workflows shellcheck check smoke artifacts entrypoint audit-ledger audit-pins audit-dead-symbols build clean

help: ## 显示可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## 创建虚拟环境
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: venv ## 安装开发依赖
	$(BIN)/pip install -e ".[dev]"

lint: ## 静态检查与格式检查
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## 自动格式化
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck: ## 类型检查
	$(BIN)/mypy

test: ## 单元测试
	$(BIN)/pytest --cov=immich_cn --cov-report=term-missing --cov-fail-under=70

docs: ## 校验文档与实现的一致性（环境变量/CLI/make/挂载路径）
	$(BIN)/python scripts/check_docs.py

workflows: ## 校验工作流安全契约（注入/超时/权限/并发）
	$(BIN)/python scripts/check_workflows.py

shellcheck: ## 校验 shell 脚本的变量展开等静态问题
	$(BIN)/python scripts/check_shell.py

audit-ledger: ## 校验审计账本一致性（汇总必须能由 history 复算）
	$(BIN)/python scripts/check_audit_ledger.py --path work/audit/state.json

audit-pins: ## 校验 Action pin 与上游 tag 一致（需要网络与 GITHUB_TOKEN）
	$(BIN)/python -m scripts.check_action_pins --repository $${GITHUB_REPOSITORY:-webees/immich-cn}

audit-dead-symbols: ## 扫描 src/ 与 scripts/ 里的零引用模块级定义
	$(BIN)/python -m scripts.check_dead_symbols

check: lint typecheck test docs workflows shellcheck ## 全部检查

smoke: ## 用合成数据跑完整流水线（不访问外网）
	$(BIN)/python -m scripts.smoke_data --work-dir build --dist-dir dist

artifacts: ## 校验发布制品（依赖 dist/ 已生成）
	$(BIN)/python scripts/check_artifacts.py dist

entrypoint: smoke ## 校验容器入口脚本
	bash scripts/check-entrypoint.sh

build: ## 真实构建（首次下载约 260 MiB 压缩数据）
	$(BIN)/immich-cn all

clean: ## 清理构建产物
	$(BIN)/python -c "import shutil,pathlib;[shutil.rmtree(p, ignore_errors=True) for p in map(pathlib.Path, ('build','dist','.cache/immich-cn','.pytest_cache','.mypy_cache','.ruff_cache'))]"
