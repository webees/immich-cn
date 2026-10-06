# immich-cn

> 为 [Immich](https://immich.app/) 提供**中文反向地理编码数据**的全自动构建流水线：中文地名、标准四级行政区、**每日自动更新**、开箱即用的容器镜像。

[![CI](https://github.com/webees/immich-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/ci.yml)
[![全自动更新数据](https://github.com/webees/immich-cn/actions/workflows/update-data.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/update-data.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Container](https://img.shields.io/badge/ghcr.io-immich--cn-blue)](https://github.com/webees/immich-cn/pkgs/container/immich-cn)

Immich 的反向地理编码默认输出英文地名，本项目的目标是让照片地图显示**熟悉的中文地名**，并且可以直接用中文搜索地点。

本项目是完全独立的实现，不是任何同类项目的重写版本，也不包含、改写或复用其代码与人工整理数据。
早期中文 Immich geodata 思路带来的启发只在文末「致谢」中说明，不构成代码、数据或格式继承。
项目采用 **MIT** 许可；数据来源和再分发要求单独说明，见 [docs/licensing.md](docs/licensing.md)。

设计重点不是复制某个数据格式或使用方式，而是建立自己的规范模型后再适配消费者：

| 维度 | 本项目设计 |
|:--|:--|
| 构建入口 | 可测试的 Python 包 + 统一 CLI |
| 默认运行 | 零密钥，GeoNames 离线层级表即可完成构建 |
| 可选增强 | 高德 / Nominatim provider，带限速与磁盘缓存 |
| 规范数据 | 自有 SQLite 数据集 `immich-cn-dataset-sqlite-v1.zip`，可直接查询、分析或二次开发 |
| 兼容导出 | Immich 文本目录与 zip 只是默认适配器，不决定内部模型 |
| 发布方式 | Release 制品 + GHCR 数据镜像 + 开箱即用的 Immich 覆盖镜像 |
| 粒度切换 | 同一镜像内用 `IMMICH_CN_PATTERN` 切换，无需重新构建 |
| 更新频率 | 每天自动检查并更新，含 ETag 增量校验与发布指纹 |
| 数据追踪 | 每次构建记录源文件 SHA256、ETag、统计与输出摘要 |
| 发布校验 | 结构、覆盖率、去重、制品哈希、容器 smoke、Trivy 与 Cosign |

## 数据模型与使用方式

本项目不以“保留上游相同格式与相同使用方式”为目标。规范数据模型是第一等产物，
`immich-cn-dataset-sqlite-v1.zip` 内含带索引的 SQLite 数据库，直接表达地点、四级行政名、国家、
来源哈希与构建元数据；任何 SQLite、DuckDB、BI 或程序都可以直接查询和二次开发，
不需要先理解 Immich 的文本列约定。

层间关系明确：

- **规范层**：SQLite 数据集定义本项目的稳定语义、版本和查询方式；
- **适配层**：`geodata*.zip` 把规范模型导出为 Immich 可读取的文本目录；
- **使用层**：CLI、数据镜像和 Immich 覆盖镜像按场景选择，而不是把某一种兼容方式当成唯一入口。

新增消费者时增加适配器或导出器，不改规范层；Immich 用户继续使用兼容导出，两者可以独立演进。
完整格式说明见 [docs/data-format.md](docs/data-format.md)，决策见
[ADR 0001](docs/adr/0001-immich-output-contract.md)。

## 全自动更新机制

数据更新**完全无人值守**：GitHub Actions 每天自动检查上游地理数据，发现变化就重新翻译、打包、校验并发布，同时推送新的容器镜像。

| 环节 | 行为 |
|:--|:--|
| 触发 | `每天 UTC 05:23`（北京时间 13:23）定时执行，也支持手动 `workflow_dispatch` |
| 上游检查 | 用 `ETag` / `Last-Modified` 条件请求校验 GeoNames、Natural Earth、i18n-iso-countries；未变化时 **304，不传输正文** |
| 变化判断 | 用「上游文件 SHA256 + 构建配置 + 发布器修订」计算发布指纹，与上一次发布对比；无变化则跳过发布，避免无意义的版本和重复导入 |
| 构建 | 重新生成四级行政层级、汉化 `cities500`、导出 7 种粒度 × full/非 full 共 14 个 geodata 变体与规范数据集 |
| 校验 | 文件完整性、GeoNames ID 去重、中国与香港记录中文覆盖率、国家名称覆盖率全部通过才允许发布 |
| 发布 | 更新滚动 Release `auto-release`、创建当日至多一个不可变日期快照 `data-YYYY-MM-DD`（同日后续修订用 `data-YYYY-MM-DD-sha-<短提交>`）、推送两个多架构镜像 |
| 保留策略 | 默认只保留最近 3 个 `data-*` 快照，不会无限堆积 |
| 失败兜底 | 任一环节失败自动创建/更新带 `automation` 标签的 issue，附带运行链接 |

你只需要定期 `docker compose pull`，或使用 Release 的固定地址 `releases/latest/download/immich-cn-geodata-admin2-default-v1.zip`，即可持续获得最新数据。

## 快速开始

### 方式一：使用开箱即用的 Immich 镜像（推荐）

`ghcr.io/webees/immich-cn-server` 基于官方 `immich-server`，在启动时把中文 geodata 注入到正确位置，无需手工挂载文件。
完整可用的 compose 文件（含 redis 与 database）：[examples/compose.server.yml](examples/compose.server.yml)。

```yaml
# docker-compose.yml（只列出需要改动的部分）
services:
  immich-server:
    image: ghcr.io/webees/immich-cn-server:latest
    environment:
      # 可选：切换行政区展示粒度，默认 {admin_2}
      IMMICH_CN_PATTERN: "{admin_2} {admin_3}"
      # 可选：强制 Immich 重新导入 geodata
      IMMICH_CN_FORCE_RELOAD: "1"
```

### 方式二：把数据镜像挂载进官方 Immich

如果你希望继续使用官方 `immich-app/immich-server` 镜像，可以用数据镜像提供文件：
完整示例见 [examples/compose.volume.yml](examples/compose.volume.yml)。

```yaml
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:release
    volumes:
      - ./immich-cn/geodata:/build/geodata:ro
```

```bash
# 一次性把数据镜像中的文件复制到宿主机目录
docker run --rm -v "$PWD/immich-cn:/out" ghcr.io/webees/immich-cn:latest --target /out
```

### 方式三：下载 Release 数据

在 [Releases](https://github.com/webees/immich-cn/releases) 页面下载 `immich-cn-geodata-admin2-default-v1.zip`，解压后按下面的路径挂载：

```yaml
volumes:
  - ./geodata:/build/geodata
  # 国家名称覆盖：仅 Immich 1.136.0 ~ 2.x 需要（3.0 起改读 countryInfo.txt）
  # Immich >= 1.136.0
  - ./i18n-iso-countries/langs:/usr/src/app/server/node_modules/i18n-iso-countries/langs
  # Immich < 1.136.0
  # - ./i18n-iso-countries/langs:/usr/src/app/node_modules/i18n-iso-countries/langs
```

### 方式四：本地构建

```bash
git clone https://github.com/webees/immich-cn.git && cd immich-cn
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 全流程：下载 -> 翻译 -> 打包 -> 校验，默认零密钥
immich-cn all
```

产物位于 `dist/`：规范数据集 `immich-cn-dataset-sqlite-v1.zip`、Immich 默认粒度 `immich-cn-geodata-admin2-default-v1.zip`、
`immich-cn-geodata-admin2-full-v1.zip`（数据增强版）、各粒度变体、`immich-cn-checksums-sha256-v1.txt` 与 `immich-cn-manifest-json-v1.json`。

### 生效与刷新

1. 重启 Immich，启动日志出现 `geodata records imported` 表示数据已导入。
2. 首次使用时，在「系统管理 → 任务」中执行一次「提取元数据 → 全部」，让已有照片重新计算位置。
3. 后续新增照片会自动使用新数据，无需重复刷新。

## 展示粒度

用 `{admin_1}` ~ `{admin_4}` 占位符描述要展示的行政区层级，以「中国, 江苏省, 苏州市, 昆山市, 周市镇」为例：

| `IMMICH_CN_PATTERN` / 文件名 | 展示结果 |
|:--|:--|
| `{admin_2}`（默认，`immich-cn-geodata-admin2-default-v1.zip`） | 苏州市 |
| `{admin_3}` | 昆山市 |
| `{admin_4}` | 周市镇 |
| `{admin_2} {admin_3}` | 苏州市 昆山市 |
| `{admin_2} {admin_3} {admin_4}` | 苏州市 昆山市 周市镇 |

缺少对应层级的地区会自动回退到上一级，绝不会输出空地名。完整的组合规则见 [docs/architecture.md](docs/architecture.md)。

> [!NOTE]
> 默认（离线）数据在中国大陆的 `admin_4` 通常回退到区县，因为 GeoNames 几乎没有乡镇级 `ADM4` 记录。
> 需要精确到乡镇时，配置 `AMAP_API_KEY` 并加上 `--provider amap`。

## 数据源

| 数据 | 用途 | 许可 |
|:--|:--|:--|
| [GeoNames](https://download.geonames.org/export/dump/) `cities500` / `admin*Codes` / `alternateNamesV2` / 国家 dump | 地点、行政区、中文别名 | CC BY 4.0 |
| [Natural Earth](https://www.naturalearthdata.com/) `ne_10m_admin_0_countries` | 无城市点的国家边界回退 | Public Domain |
| [i18n-iso-countries](https://github.com/michaelwittig/node-i18n-iso-countries) | 国家名称中文覆盖（旧版 Immich） | MIT |
| OpenStreetMap / Nominatim（可选） | 补充海外行政区 | ODbL 1.0 |
| 高德地图（可选） | 补充中国大陆区县与乡镇 | 高德开放平台条款 |

> 代码采用 MIT，但**生成的数据制品不适用 MIT**，请阅读 [docs/licensing.md](docs/licensing.md)。

## 自动化工作流

```
每天 05:23 UTC（cron）
        │
        ▼
  update-data.yml ──► _build-data.yml（可复用）
        │                    │
        │                    ├─ ETag 条件校验上游（未变化 → 304）
        │                    ├─ immich-cn all（翻译 → 打包 → 校验）
        │                    ├─ 发布指纹对比（无变化 → 跳过发布）
        │                    └─ 推送多架构镜像
        │
        └──► Release：auto-release（滚动）+ data-*（不可变快照，保留 3 个）

ci.yml ──► ruff + mypy + pytest + 容器入口脚本校验 + Docker 冒烟构建
release.yml ──► 手动创建语义化版本 Release
```

- `update-data.yml`：**每日自动更新数据**，包含增量校验、指纹对比、发布、快照清理与失败通知。
- `ci.yml`：每次提交执行静态检查、单元测试与镜像构建冒烟测试。
- `release.yml`：手动创建语义化版本 Release（总是强制重新构建与推送）。
- `cleanup.yml`：每周清理旧 `data-*` 快照、Actions 历史与 GHCR 版本；稳定前可启用 `prune-all`。

## 文档

- [架构设计](docs/architecture.md)
- [制品命名规范 v4](docs/artifact-spec.md)
- [项目命名规范](docs/naming-conventions.md)
- [规范数据格式](docs/data-format.md)
- [数据源与处理流程](docs/data-sources.md)
- [部署指南](docs/deployment.md)
- [Packages 与供应链](docs/packages.md)
- [自动清理与保留策略](docs/maintenance.md)
- [本地开发](docs/development.md)
- [许可与署名](docs/licensing.md)
- [常见问题](docs/faq.md)

## License

代码以 [MIT](LICENSE) 发布；数据制品的署名要求汇总在 [NOTICE](NOTICE)，完整说明见 [docs/licensing.md](docs/licensing.md)。

## 致谢

- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)：早期中文 Immich geodata 思路提供了启发；本项目为完全独立实现，不含代码、数据或格式继承。
- [Immich](https://github.com/immich-app/immich)：反向地理编码的实现与文档。
- [GeoNames](https://www.geonames.org/)、[Natural Earth](https://www.naturalearthdata.com/)、[OpenStreetMap](https://www.openstreetmap.org/)：开放地理数据。
