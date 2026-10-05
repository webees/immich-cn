# 本地开发

## 环境

- Python 3.11+
- Docker（仅在验证镜像时需要）

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## 常用命令

```bash
make lint        # ruff check + ruff format --check
make typecheck   # mypy
make test        # pytest
make check       # lint + typecheck + test
make smoke       # 用合成数据跑完整流水线（不访问外网）
make build       # 真实构建（会下载约 1.5 GiB 上游数据）
```

直接使用 CLI：

```bash
immich-cn fetch                  # 只下载数据源
immich-cn build                  # 下载 + 生成 geodata 目录
immich-cn all                    # 全流程 + 校验
immich-cn all --provider amap    # 使用高德增强（需要 AMAP_API_KEY）
immich-cn all --chinese-variant hant
immich-cn verify build/geodata   # 校验已有产物
```

## 目录结构

```
src/immich_cn/        Python 包
  cli.py              命令行入口
  config.py           数据源清单与构建配置
  http.py             下载、缓存、重试
  geonames.py         GeoNames 解析
  chinese.py          中文名解析与覆盖表
  hierarchy.py        行政层级表
  providers/          offline / amap / nominatim
  build.py            流水线编排
  package.py          打包与 manifest
  verify.py           校验
config/overrides.toml 人工覆盖表
docker/               镜像定义与容器脚本
scripts/smoke_data.py 合成数据冒烟构建
tests/                单元测试与合成夹具
docs/                 文档
```

## 测试策略

- `tests/synthetic.py` 构造结构完整的最小 GeoNames 数据集；
- `tests/test_pipeline.py` 用它跑完整的 fetch→build→package→verify（跳过下载）；
- provider 通过 `httpx.MockTransport` 验证请求参数、响应解析与缓存行为；
- Docker 冒烟在 CI 中验证两个镜像可以构建、数据镜像可以运行并按粒度输出。

## 新增一个展示粒度

1. 确认新 pattern 只用 `{admin_1}` ~ `{admin_4}` / `{country}` 占位符；
2. 在 `--patterns` 中追加，例如 `--patterns '{admin_1} {admin_2}'`；
3. 组合规则与去重逻辑在 `immich_cn/patterns.py`，无需改打包代码。

## 新增一个国家/地区

1. 把国家码加入 `--extra-countries`（默认 `CN,HK,TW,MO,JP`）；
2. 如果 GeoNames 中文别名不足，在 `config/overrides.toml` 的 `[places]`/`[admins]` 中补充；
3. 运行 `make smoke` 与 `immich-cn build --extra-countries ...` 验证覆盖率。

## 发布流程

1. 合并到 `main` 后 CI 自动执行；
2. 需要发版本时手动触发 `Release` 工作流并填写版本号；
3. 数据每周由 `Update Data` 工作流自动更新，产出滚动 Release 与不可变日期快照。
