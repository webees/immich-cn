# immich-cn

> 为 [Immich](https://immich.app/) 提供**中文反向地理编码数据**的全自动构建流水线：中文地名、标准四级行政区、周更数据、开箱即用的容器镜像。

[![CI](https://github.com/webees/immich-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/ci.yml)
[![全自动更新数据](https://github.com/webees/immich-cn/actions/workflows/update-data.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/update-data.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Container](https://img.shields.io/badge/ghcr.io-immich--cn-blue)](https://github.com/webees/immich-cn/pkgs/container/immich-cn)

Immich 的反向地理编码默认输出英文地名，本项目的目标是让照片地图显示**熟悉的中文地名**，并且可以直接用中文搜索地点。

本项目是 [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn) 的独立重写版本，在保留相同数据格式与使用方式的前提下，重新设计了构建流水线与发布方式：

| 维度 | 上游项目 | 本项目 |
|:--|:--|:--|
| 代码许可 | GPL-3.0 | **MIT**（数据许可单独说明，见 [docs/licensing.md](docs/licensing.md)） |
| 构建入口 | Shell 脚本串联 | 可测试的 Python 包 + 统一 CLI |
| 外部依赖 | 必须提供高德 API Key | **默认零密钥**（GeoNames 离线层级表），高德/Nominatim 作为可选增强 |
| 行政区粒度 | 四级别依赖 Amap | 从 GeoNames `ADM3`/`ADM4` 自建区县、乡镇表，离线即可覆盖 |
| 发布方式 | Release zip | **Release zip + GHCR 镜像**（数据镜像 + 开箱即用的 Immich 镜像） |
| 粒度切换 | 下载不同 zip | 同一镜像内用 `IMMICH_CN_PATTERN` 环境变量切换 |
| 更新频率 | 每周一次 | **每天自动检查并更新**（含 ETag 增量校验） |
| 数据来源追踪 | 无 | 每次构建写入源文件 SHA256、ETag、统计到 `manifest.json` |
| 校验 | 无 | 构建后自动执行结构、覆盖率、去重校验 |

## 全自动更新机制

数据更新**完全无人值守**：GitHub Actions 每天自动检查上游地理数据，发现变化就重新翻译、打包、校验并发布，同时推送新的容器镜像。

| 环节 | 行为 |
|:--|:--|
| 触发 | `每天 UTC 05:23`（北京时间 13:23）定时执行，也支持手动 `workflow_dispatch` |
| 上游检查 | 用 `ETag` / `Last-Modified` 条件请求校验 GeoNames、Natural Earth、i18n-iso-countries；未变化时 **304，不传输正文** |
| 变化判断 | 用「上游文件 SHA256 + 构建配置」计算数据指纹，与上一次发布对比；无变化则跳过发布，避免无意义的版本和重复导入 |
| 构建 | 重新生成四级行政层级、汉化 `cities500`、打包 7 种粒度 × full/非 full 共 14 个制品 |
| 校验 | 文件完整性、GeoNames ID 去重、中国记录中文覆盖率、国家名称覆盖率全部通过才允许发布 |
| 发布 | 更新滚动 Release `auto-release`、创建当日不可变快照 `data-YYYY-MM-DD`、推送 `ghcr.io/webees/immich-cn` 与 `ghcr.io/webees/immich-cn-server` 多架构镜像 |
| 保留策略 | 自动清理超过 14 个的旧日期快照，不会无限堆积 |
| 失败兜底 | 任一环节失败自动创建/更新带 `automation` 标签的 issue，附带运行链接 |

你只需要定期 `docker compose pull`，或使用 Release 的固定地址 `releases/latest/download/geodata.zip`，即可持续获得最新数据。

## 快速开始

### 方式一：使用开箱即用的 Immich 镜像（推荐）

`ghcr.io/webees/immich-cn-server` 基于官方 `immich-server`，在启动时把中文 geodata 注入到正确位置，无需手工挂载文件。

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

在 [Releases](https://github.com/webees/immich-cn/releases) 页面下载 `geodata.zip`，解压后按下面的路径挂载：

```yaml
volumes:
  # Immich >= 1.136.0
  - ./geodata:/build/geodata
  # Immich < 1.136.0 还需要国家名称覆盖
  - ./i18n-iso-countries/langs:/usr/src/app/node_modules/i18n-iso-countries/langs
```

### 方式四：本地构建

```bash
git clone https://github.com/webees/immich-cn.git && cd immich-cn
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 全流程：下载 -> 翻译 -> 打包 -> 校验，默认零密钥
immich-cn all
```

产物位于 `dist/`：`geodata.zip`（默认粒度）、`geodata_full.zip`（数据增强版）、各粒度变体、`SHA256SUMS` 与 `manifest.json`。

### 生效与刷新

1. 重启 Immich，启动日志出现 `geodata records imported` 表示数据已导入。
2. 首次使用时，在「系统管理 → 任务」中执行一次「提取元数据 → 全部」，让已有照片重新计算位置。
3. 后续新增照片会自动使用新数据，无需重复刷新。

## 展示粒度

用 `{admin_1}` ~ `{admin_4}` 占位符描述要展示的行政区层级，以「中国, 江苏省, 苏州市, 昆山市, 周市镇」为例：

| `IMMICH_CN_PATTERN` / 文件名 | 展示结果 |
|:--|:--|
| `{admin_2}`（默认，`geodata.zip`） | 苏州市 |
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
        │                    ├─ 数据指纹对比（无变化 → 跳过发布）
        │                    └─ 推送多架构镜像
        │
        └──► Release：auto-release（滚动）+ data-YYYY-MM-DD（快照，保留 14 个）

ci.yml ──► ruff + mypy + pytest + 容器入口脚本校验 + Docker 冒烟构建
release.yml ──► 手动创建语义化版本 Release
```

- `update-data.yml`：**每日自动更新数据**，包含增量校验、指纹对比、发布、快照清理与失败通知。
- `ci.yml`：每次提交执行静态检查、单元测试与镜像构建冒烟测试。
- `release.yml`：手动创建语义化版本 Release（总是强制重新构建与推送）。

## 文档

- [架构设计](docs/architecture.md)
- [数据源与处理流程](docs/data-sources.md)
- [部署指南](docs/deployment.md)
- [本地开发](docs/development.md)
- [许可与署名](docs/licensing.md)
- [常见问题](docs/faq.md)

## 与上游项目的关系

本项目只复用 Immich 与 GeoNames 的**公开数据格式**，代码与流水线均为重新实现，不包含上游项目的源代码或人工整理的数据文件。数据格式兼容意味着你可以直接用本项目替换上游的数据目录。

## 致谢

- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)：最初的思路与数据格式探索。
- [Immich](https://github.com/immich-app/immich)：反向地理编码的实现与文档。
- [GeoNames](https://www.geonames.org/)、[Natural Earth](https://www.naturalearthdata.com/)、[OpenStreetMap](https://www.openstreetmap.org/)：开放地理数据。

## License

代码以 [MIT](LICENSE) 发布；数据制品的许可与署名要求见 [docs/licensing.md](docs/licensing.md)。
