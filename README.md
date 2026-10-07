# immich-cn

> **面向中国用户的 Immich 本地化增强套件**：提供中文地名与检索、地图与坐标说明、时区体验、CDN 与静态资源加速、国内部署排障，以及全自动数据更新和镜像发布。数据流水线按设计每天自动检查并更新（运行前提见后文）。

[![CI](https://github.com/webees/immich-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/ci.yml) [![全自动更新数据](https://github.com/webees/immich-cn/actions/workflows/update-data.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/update-data.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Container](https://img.shields.io/badge/ghcr.io-immich--cn-blue)](https://github.com/webees/immich-cn/pkgs/container/immich-cn)

Immich 的反向地理编码默认输出英文地名，本项目的目标是让照片地图显示**熟悉的中文地名**，并且可以直接用中文搜索地点。

本地化不止于翻译：项目按「显示、检索、地图、体验、加速、数据」六个层面推进，当前进展与短板都写在 [中国本地化方向](docs/china-localization.md) 里；CDN、缓存边界和 Nginx 源站示例见 [中国网络与加速](docs/china-acceleration.md)。

本项目按独立实现组织：本仓库当前树中的代码、配置、CI 工作流与数据构建脚本由本项目维护，没有引用或打包同类项目的代码文件与人工整理数据文件；核查范围、关键词与边界见 [docs/documentation-policy.md](docs/documentation-policy.md)。文末「致谢」记录了与本项目相关的上游思路来源。Immich 文本格式兼容属于消费者接口适配，不定义本项目的内部数据模型。以上描述的是当前仓库状态与项目声明，不是对历史过程或法律状态的结论。本仓库的源代码、配置、CI 工作流和文档采用 **MIT** 许可；生成的数据库与地理数据制品不属于 MIT，数据来源、署名和再分发要求见 [docs/licensing.md](docs/licensing.md)。

设计重点不是复制某个数据格式或使用方式，而是建立自己的规范模型后再适配消费者：

| 维度 | 本项目设计 |
|:--|:--|
| 构建入口 | 可测试的 Python 包 + 统一 CLI |
| 默认运行 | 默认 provider 不要求 API Key，使用 GeoNames 离线层级表构建 |
| 可选增强 | 高德 / Nominatim provider，带限速与磁盘缓存 |
| 规范数据 | 自有 SQLite 数据集 `immich-cn-dataset-sqlite-v1.zip`，可直接查询、分析或二次开发 |
| 兼容导出 | Immich 文本目录与 zip 是默认适配器，不定义内部模型 |
| 发布方式 | Release 制品 + GHCR 数据镜像 + 开箱即用的 Immich 覆盖镜像 |
| 粒度切换 | 同一镜像内用 `IMMICH_CN_PATTERN` 切换，无需重新构建 |
| 访问加速 | `/_app/immutable` 长缓存 + CDN 回源边界 + Nginx 源站示例 |
| 更新频率 | 每天自动检查并更新，含 ETag 增量校验与发布指纹 |
| 数据追踪 | 每次构建记录源文件 SHA256、ETag、统计与输出摘要 |
| 发布校验 | 结构、覆盖率、去重、制品哈希、容器 smoke、Trivy 与 Cosign |

## 数据模型与使用方式

本项目不以“保留上游相同格式与相同使用方式”为目标。规范数据模型是第一等产物， `immich-cn-dataset-sqlite-v1.zip` 内含带索引的 SQLite 数据库，直接表达地点、四级行政名、国家、来源哈希与构建元数据；支持 SQLite 3 的工具可以查询和二次开发，具体兼容性取决于客户端版本，不要求先理解 Immich 的文本列约定。

层间关系明确：

- **规范层**：SQLite 数据集定义本项目的稳定语义、版本和查询方式；
- **适配层**：`geodata*.zip` 把规范模型导出为 Immich 可读取的文本目录；
- **使用层**：CLI、数据镜像和 Immich 覆盖镜像按场景选择，而不是把某一种兼容方式当成唯一入口。

新增消费者时增加适配器或导出器，不改规范层；Immich 用户继续使用兼容导出，两者可以独立演进。完整格式说明见 [docs/data-format.md](docs/data-format.md)，决策见 [ADR 0001](docs/adr/0001-immich-output-contract.md)。

## 全自动更新机制

数据更新按设计为无人值守流程：在 GitHub Actions、上游数据源和仓库权限正常时，每天自动检查上游地理数据，发现变化后重新翻译、打包、校验并发布，同时推送新的容器镜像。

| 环节 | 行为 |
|:--|:--|
| 触发 | `每天 UTC 05:23`（北京时间 13:23）定时执行，也支持手动 `workflow_dispatch` |
| 上游检查 | 用 `ETag` / `Last-Modified` 条件请求校验 GeoNames、Natural Earth、i18n-iso-countries；未变化时 **304，不传输正文** |
| 变化判断 | 用「上游文件 SHA256 + 构建配置 + 发布器修订」计算发布指纹，与上一次发布对比；无变化则跳过发布，避免无意义的版本和重复导入 |
| 构建 | 重新生成四级行政层级、汉化 `cities500`、导出 7 种粒度 × full/非 full 共 14 个 geodata 变体与规范数据集 |
| 校验 | 文件完整性、GeoNames ID 去重、CN/HK/TW/MO 展示名零缺失、国家名称覆盖率全部通过才允许发布 |
| 发布 | 更新滚动 Release `auto-release`、创建当日至多一个不可变日期快照 `data-YYYY-MM-DD`（同日后续修订用 `data-YYYY-MM-DD-sha-<短提交>`）、推送两个多架构镜像 |
| 保留策略 | 默认保留最近 3 个 `data-*` 快照；达到策略期限后自动清理，手动修改策略除外 |
| 失败兜底 | 任一环节失败自动创建/更新带 `automation` 标签的 issue，附带运行链接 |

你只需要定期 `docker compose pull`，或使用 Release 的固定地址 `releases/latest/download/immich-cn-geodata-admin2-default-v1.zip`，即可持续获得最新数据。

## 快速开始

### 方式一：使用开箱即用的 Immich 镜像（推荐）

`ghcr.io/webees/immich-cn-server` 基于官方 `immich-server`，在启动时把中文 geodata 注入到目标目录；仍需要按 Immich 官方要求配置数据库、缓存和持久化目录。示例 compose 文件（含 redis 与 database，需按 Immich 官方要求提供 `.env` 与持久化目录）：[examples/compose.server.yml](examples/compose.server.yml)。

```yaml
# docker-compose.yml（只列出需要改动的部分）
services:
  immich-server:
    image: ghcr.io/webees/immich-cn-server:latest
    environment:
      # 中国本地化默认时区
      TZ: Asia/Shanghai
      # 可选：切换行政区展示粒度，默认 {admin_2}
      IMMICH_CN_PATTERN: "{admin_2} {admin_3}"
      # 可选：强制 Immich 重新导入 geodata
      IMMICH_CN_FORCE_RELOAD: "1"
```

### 方式二：把数据镜像挂载进官方 Immich

如果你希望继续使用官方 `immich-app/immich-server` 镜像，可以用数据镜像提供文件：完整示例见 [examples/compose.volume.yml](examples/compose.volume.yml)。

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

在 [Releases](https://github.com/webees/immich-cn/releases) 页面下载两个资产，按下面命令解压即可得到与挂载路径一致的目录结构：

```bash
curl -fsSL -o immich-cn-geodata-admin2-default-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-geodata-admin2-default-v1.zip
curl -fsSL -o immich-cn-i18n-json-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-i18n-json-v1.zip
unzip -o immich-cn-geodata-admin2-default-v1.zip -d .
mkdir -p i18n-iso-countries
unzip -o immich-cn-i18n-json-v1.zip -d i18n-iso-countries
```

`immich-cn-geodata-*.zip` 里只有 `geodata/`；国家名称覆盖单独发布为 `immich-cn-i18n-json-v1.zip`，其成员是 `langs/` 与上游 `LICENSE`，所以要解压到 `i18n-iso-countries/` 下才对得上后面的挂载路径。Immich 3.3.0 起改读 `countryInfo.txt`，不再需要这个覆盖包。

```yaml
volumes:
  - ./geodata:/build/geodata
  # 国家名称覆盖：仅 Immich 1.136.0 ~ 3.2.x 需要（3.3.0 起改读 countryInfo.txt）
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

# 全流程：下载 -> 翻译 -> 打包 -> 校验，默认无需 API Key
immich-cn all
```

产物位于 `dist/`：规范数据集 `immich-cn-dataset-sqlite-v1.zip`、Immich 默认粒度 `immich-cn-geodata-admin2-default-v1.zip`、 `immich-cn-geodata-admin2-full-v1.zip`（数据增强版）、各粒度变体、`immich-cn-checksums-sha256-v1.txt` 与 `immich-cn-manifest-json-v1.json`。

### 方式五：CDN 与静态资源加速

需要把 Immich 放在国内 CDN 或反向代理后面时，可以使用 [examples/compose.acceleration.yml](examples/compose.acceleration.yml) 和 [examples/nginx/immich-cn.conf](examples/nginx/immich-cn.conf)。该示例只对 `/_app/immutable/*` 开启长期共享缓存，HTML、API、原始照片和视频默认旁路，避免把私有内容写进公共缓存。

jsDelivr 等免费 CDN 只作为 GitHub 分支、tag 或提交中静态文件的**可选**通道；它不能直接代理 GitHub Release 附件，也不保证中国大陆线路质量。完整缓存矩阵、jsDelivr 实测边界、地图同源加速和验证命令见 [中国网络与加速](docs/china-acceleration.md)。

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

存在至少一个非空层级时，显示名会自动回退到上一级；若全部层级为空，构建校验应拒绝该记录。完整的组合规则见 [docs/architecture.md](docs/architecture.md)。

> [!NOTE]
> 默认（离线）数据在中国大陆的 `admin_4` 通常回退到区县：GeoNames 的乡镇级 `ADM4` 要素不少（实测 11,878 条），但带 `admin4` 代码的只有 73 条，拼不出第四级层级。需要精确到乡镇时，配置 `AMAP_API_KEY` 并加上 `--provider amap`。

## 数据源

| 数据 | 用途 | 许可 |
|:--|:--|:--|
| [GeoNames](https://download.geonames.org/export/dump/) `cities500` / `admin*Codes` / `alternateNamesV2` / 国家 dump | 地点、行政区、中文别名 | CC BY 4.0 |
| [Natural Earth](https://www.naturalearthdata.com/) `ne_10m_admin_0_countries` | 无城市点的国家边界回退 | Public Domain |
| [i18n-iso-countries](https://github.com/michaelwittig/node-i18n-iso-countries) | 国家名称中文覆盖（Immich 3.2.x 及以下；3.3.0 起改用 `countryInfo.txt`） | MIT |
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
- [中国本地化方向](docs/china-localization.md)
- [中国网络与加速](docs/china-acceleration.md)
- [制品命名规范 v4](docs/artifact-spec.md)
- [项目命名规范](docs/naming-conventions.md)
- [文档严谨性规范](docs/documentation-policy.md)
- [规范数据格式](docs/data-format.md)
- [数据源与处理流程](docs/data-sources.md)
- [部署指南](docs/deployment.md)
- [Packages 与供应链](docs/packages.md)
- [自动清理与保留策略](docs/maintenance.md)
- [本地开发](docs/development.md)
- [许可与署名](docs/licensing.md)
- [常见问题](docs/faq.md)

## License

源代码、配置、CI 工作流和文档以 [MIT](LICENSE) 发布；数据库和地理数据制品不适用 MIT，署名要求汇总在 [NOTICE](NOTICE)，完整说明见 [docs/licensing.md](docs/licensing.md)。

## 致谢

- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)：早期中文 Immich geodata 思路提供了启发；本项目按独立实现组织，当前树未引用或打包该项目的代码与人工整理数据（核查方式见 [文档严谨性规范](docs/documentation-policy.md)）。
- [Immich](https://github.com/immich-app/immich)：反向地理编码的实现与文档。
- [GeoNames](https://www.geonames.org/)、[Natural Earth](https://www.naturalearthdata.com/)、[OpenStreetMap](https://www.openstreetmap.org/)：开放地理数据。
