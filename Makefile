PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install lint format typecheck test check smoke artifacts entrypoint build clean

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
	$(BIN)/pytest --cov=immich_cn --cov-report=term-missing

check: lint typecheck test ## 全部检查

smoke: ## 用合成数据跑完整流水线（不访问外网）
	$(BIN)/python -m scripts.smoke_data --work-dir build --dist-dir dist

artifacts: ## 校验发布制品（依赖 dist/ 已生成）
	$(BIN)/python scripts/check_artifacts.py dist

entrypoint: smoke ## 校验容器入口脚本
	bash scripts/check-entrypoint.sh

build: ## 真实构建（会下载约 1.5 GiB 上游数据）
	$(BIN)/immich-cn all

clean: ## 清理构建产物
	$(BIN)/python -c "import shutil,pathlib;[shutil.rmtree(p, ignore_errors=True) for p in map(pathlib.Path, ('build','dist','.cache/immich-cn','.pytest_cache','.mypy_cache','.ruff_cache'))]"
