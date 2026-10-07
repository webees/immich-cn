# 本地开发

## 环境要求

- Python 3.11+
- Docker（仅在验证镜像时需要）

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## 常用命令

```bash
make help        # 列出全部目标
make install     # 创建 .venv 并安装开发依赖
make lint        # ruff check + ruff format --check
make format      # ruff format + ruff check --fix
make typecheck   # mypy
make test        # pytest + 覆盖率
make check       # lint + typecheck + test + docs + workflows + shellcheck
make smoke       # 用合成数据跑完整流水线（不访问外网）
make artifacts   # 校验 dist/ 制品（压缩包 / 清单 / immich-cn-checksums-sha256-v1.txt）
make entrypoint  # 校验容器入口脚本对 IMMICH_CN_PATTERN 的处理
make build       # 真实构建（首次下载约 260 MiB 压缩数据）
make clean       # 清理 build/ dist/ 与各类缓存
python scripts/cleanup.py --help  # 查看发布 / Actions / GHCR 清理参数（默认试运行）
```

各阶段实测开销（2026-10-06，1318830 行输出）：

| 阶段 | 实测开销 |
|:--|:--|
| 首次下载上游压缩包 | ≈260 MiB（alternateNamesV2 195 MiB 为主） |
| 开启 `--revalidate` 后的日常下载 | 通常仅 cities500 ≈13 MiB；未变化的数据源返回 304 |
| 解压后的中间文件 | ≈0.95 GiB（alternateNamesV2.txt 749 MiB、CN.txt 126 MiB） |
| 解析 alternateNamesV2 建立中文名索引 | ≈10 s |
| 打包 14 个变体（名称组合 + 压缩打包） | ≈1.5 min |
| GitHub Actions 完整流程 | 约 8~25 min（含运行器缓存恢复与镜像推送） |

构建结束后会自动删除不再需要的中间产物（解压出的上游原始文件等，合计约 1.1 GiB）。明文变体表 `immich-cn-patterns-v1.tsv` 默认不会生成，只有加 `--keep-raw` 时才会保留并需要自行清理。

压缩级别实测（对 44.8 MiB 的 cities500 片段）：

| 级别 | 耗时 | 体积 |
|:--|:--|:--|
| 1 | 0.27 s | 16.2 MiB（+16%） |
| **6（当前）** | **0.83 s** | **14.0 MiB** |
| 9 | 1.15 s | 13.8 MiB（−1.6%） |

级别 1 只省约 8 秒 CPU，却让每个制品大约 16%，用户每天要多下载约 88 MB；级别 9 只小 1.6% 但慢 39%。因此维持级别 6。

直接使用 CLI：

```bash
immich-cn fetch                        # 只下载数据源
immich-cn build                        # 下载 + 生成 geodata 目录
immich-cn all                          # 全流程 + 校验
immich-cn all --provider amap          # 使用高德增强（需要 AMAP_API_KEY）
immich-cn all --chinese-variant hant   # 输出繁体
immich-cn verify build/geodata         # 校验已有产物
immich-cn fingerprint dist/immich-cn-manifest-json-v1.json  # 打印发布指纹（判断是否需要重新发布）
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|:--|:--|:--|
| `--provider` | `offline` | `offline` / `amap` / `nominatim` / `auto`（auto = 有密钥用 amap） |
| `--chinese-variant` | `hans` | `hans` 简体 / `hant` 繁体 |
| `--patterns` | 7 种粒度 | 逗号分隔的展示粒度，如 `{admin_2},{admin_2} {admin_3}` |
| `--extra-countries` | `CN,HK,TW,MO,JP` | 需要附带国家数据转储的地区 |
| `--min-population` | `100` | 非完整变体的最小人口阈值 |
| `--work-dir` / `--dist-dir` / `--cache-dir` / `--config-dir` | `build` / `dist` / `.cache/immich-cn` / `config` | 各目录位置 |
| `--jobs` | CPU 数（最多 8） | 打包并发度 |
| `--revalidate` | 关 | 用 ETag/Last-Modified 校验上游，未变化不下载（每日自动更新使用） |
| `--force` | 关 | 强制重新下载全部数据源 |
| `--skip-fetch` | 关 | 直接用 `--work-dir/sources` 中已有数据源 |
| `--keep-raw` | 关 | 保留解压后的原始大文件和明文 `immich-cn-patterns-v1.tsv`（默认不生成明文表） |
| `--clean` | 关 | 执行前清空 work/dist |
| `--quiet` | 关 | 只输出警告与错误 |

`--provider auto` 在没有 `AMAP_API_KEY` 时会回退到离线模式，并打印一行显式告警：产物与 `--provider offline` 完全相同，只有清单的 `config.provider` 记为 `offline`。这样「密钥缺失 / 改名 / 过期」不会伪装成一次成功的高德增强构建；`--provider amap` 则是硬要求，缺密钥直接以 `ConfigError` 失败。

### 提供方变量

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `AMAP_API_KEY` | 无 | 高德密钥；未设置时 `--provider amap` 会直接报错 |
| `IMMICH_CN_AMAP_QPS` | `3` | 高德请求速率上限 |
| `IMMICH_CN_AMAP_BATCH_SIZE` | `20` | 高德批量逆地理编码的每批坐标数 |
| `IMMICH_CN_AMAP_COUNTRIES` | `CN,HK,MO` | 使用高德的国家码 |
| `IMMICH_CN_NOMINATIM_QPS` | `1` | Nominatim 速率上限（服务条款要求 1） |
| `IMMICH_CN_NOMINATIM_COUNTRIES` | `TW,JP` | 使用 Nominatim 的国家码 |
| `IMMICH_CN_LOG_LEVEL` | `INFO` | 日志级别 |

## 目录结构

```
src/immich_cn/        Python 包
  cli.py              命令行入口
  settings.py         数据源清单与构建配置
  fetching.py         下载、缓存、重试
  geonames.py         GeoNames 解析
  localization.py     中文名解析与覆盖表
  hierarchy.py        行政层级表
  providers/          offline / amap / nominatim
  pipeline.py         流水线编排
  dataset.py          规范 SQLite 数据集导出
  packaging.py        打包与清单
  validation.py       校验
  artifact_spec.py    制品命名规范与解析
  domain.py           领域数据模型
  logging_config.py   日志配置
  rate_limit.py       限速器
config/overrides.toml 人工覆盖表
docker/               镜像定义与容器脚本
scripts/smoke_data.py 合成数据冒烟构建
tests/                单元测试与合成夹具
docs/                 文档
```

## 测试策略

- `tests/synthetic.py` 构造结构完整的最小 GeoNames 数据集；
- `tests/test_pipeline.py` 用它跑完整的抓取 → 构建 → 打包 → 校验（跳过下载）；
- 提供方通过 `httpx.MockTransport` 验证请求参数、响应解析与缓存行为；
- Docker 冒烟在 CI 中验证两个镜像可以构建、数据镜像可以运行并按粒度输出。
- `scripts/check-entrypoint.sh` 用合成数据验证容器入口脚本：默认粒度、显式粒度、以及 `geodata-date.txt` 强制刷新。

### 变异实验

判断某个断言是否"恒真"的最可靠办法是**故意破坏实现**，看测试是否真的失败：

```bash
# 必须隔离字节码缓存，否则改写源码后可能仍加载已有 .pyc，得到假的"存活"结论
PYTHONPYCACHEPREFIX=$(mktemp -d) .venv/bin/python -m pytest -q -x
```

两条纪律：

1. 每次变异后确认**变异真的落盘**（比对替换前后的出现次数），否则结论无效；
2. 同步跑一个"控制变异"（必须被杀）与一个"等价变异"（如只改注释，必须存活），用来证明实验本身能区分两种结果。

如果某个变异存活，先判断它是否属于**等价变异**（可观察行为未变）；只有当行为确实变化却仍无测试失败时，才算是覆盖缺口。

还有一类特殊情况：**多层冗余防护**。只回退其中一层时，另一层仍能让测试通过，于是单层变异会"存活"——这并不代表测试无效。此时应把各层**同时**回退，确认完整回归（回到修复前行为）会被测试杀死，再判断覆盖是否充分。

### 死代码巡检

用 AST 扫一遍：函数参数从未被引用、数据类字段只写不读、夹具无人使用、CLI 参数无人消费。已知的**假阳性**（不要据此改代码）：

- `Protocol` 里的方法参数是接口签名，即使实现里用不到也要保留；
- CLI 的 `dest` 往往在 `_options()` / `_run_verify()` 等辅助函数里被消费，只在 `main()` 里搜会误报。

## 新增展示粒度

1. 确认新的展示粒度只使用 `{admin_1}` ~ `{admin_4}` / `{country}` 占位符；
2. 在 `--patterns` 中追加，例如 `--patterns '{admin_1} {admin_2}'`；
3. 组合规则与去重逻辑在 `src/immich_cn/display.py`，无需改打包代码。

## 新增国家地区

1. 把国家码加入 `--extra-countries`（默认 `CN,HK,TW,MO,JP`）；
2. 如果 GeoNames 中文别名不足，在 `config/overrides.toml` 的 `[places]`/`[admins]` 中补充；
3. 运行 `make smoke` 与 `immich-cn build --extra-countries ...` 验证覆盖率。

## 发布流程

1. 合并到 `main` 后 CI 自动执行；
2. 需要发版本时先同步 `pyproject.toml`、`src/immich_cn/__init__.py` 与 `CITATION.cff` 的版本号（`scripts/check_docs.py` 会拒绝三处不一致）；
3. 手动触发 `Release` 工作流并填写相同版本号，预检查会拒绝版本漂移；
4. 数据每天由 `Auto Data Update` 工作流自动更新（含条件校验与发布指纹比对），产出滚动发布与不可变 `data-*` 快照；
5. 需要立即更新时手动触发 `Auto Data Update`，勾选 `force-publish` 可强制发布。
