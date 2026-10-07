# immich-cn

> **immich-cn 为 Immich 提供中国本地化的反向地理编码地理数据**：核心是中文地名、中文与拼音检索、行政层级，以及自动发布与镜像；地图、EXIF 时区、CDN 与缓存、Nginx 示例属于可选辅助能力，不构成对 Immich 界面的复刻。

[![CI](https://github.com/webees/immich-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/ci.yml) [![Data Update](https://github.com/webees/immich-cn/actions/workflows/update-data.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/update-data.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Container](https://img.shields.io/badge/ghcr.io-immich--cn-blue)](https://github.com/webees/immich-cn/pkgs/container/immich-cn)

完整范围、本地化现状与加速边界见 [中国本地化与加速](docs/china.md)；术语、命名与文档写法遵循 [规范与约定](docs/conventions.md)。

本项目按独立实现组织：本仓库当前树中的代码、配置、工作流与数据构建脚本由本项目维护；在文末「致谢」所列同类项目范围内，仓库路径名与生产代码中未发现被引用或打包的代码文件与人工整理数据文件。核查范围、关键词与边界见 [规范与约定](docs/conventions.md)。对 Immich 文本格式的兼容属于消费端适配，不定义本项目的内部数据模型。以上均为当前仓库状态与项目声明。

设计重点不是复制某个数据格式或使用方式，而是建立自己的规范模型后再适配消费者：

| 维度 | 设计 |
|:--|:--|
| 代码许可 | 代码 MIT；数据制品另有许可与署名要求 |
| 构建入口 | 可测试的 Python 包 + 统一命令行 |
| 外部依赖 | GeoNames、Natural Earth、i18n-iso-countries；可选高德与 Nominatim |
| 行政区粒度 | 7 种展示粒度 × 完整/默认，共 14 个变体 |
| 发布方式 | GitHub 发布 + GHCR 多架构镜像 |

自动更新、缓存边界与发布校验见对应专题文档。

## 数据模型

本项目不以“保留上游相同格式与相同使用方式”为目标。规范数据模型是第一等产物，`immich-cn-dataset-sqlite-v1.zip` 内含带索引的 SQLite 数据库，直接表达地点、四级行政名、国家、来源哈希与构建元数据；支持 SQLite 3 的工具可以查询和二次开发，具体兼容性取决于客户端版本，不要求先理解 Immich 的文本列约定。

层间关系明确：

- **规范层**：SQLite 数据集定义本项目的稳定语义、版本和查询方式；
- **适配层**：`geodata*.zip` 把规范模型导出为 Immich 可读取的文本目录；
- **使用层**：命令行、数据镜像与服务端镜像按场景选择，而不是把某一种兼容方式当成唯一入口。

新增消费者时增加适配器或导出器，不改规范层；Immich 用户继续使用兼容导出，两者可以独立演进。完整格式说明见 [数据格式](docs/data-format.md)，决策见 [ADR 0001](docs/adr/0001-immich-output-contract.md)。

## 自动更新

数据更新按设计为无人值守流程：在 GitHub Actions、上游数据源与仓库权限正常时，每天自动检查上游地理数据，发现变化后重新翻译、打包、校验并发布，同时推送新的容器镜像。

| 阶段 | 行为 |
|:--|:--|
| 触发 | `每天北京时间 13:23`（UTC 05:23）定时执行，也支持手动 `workflow_dispatch` |
| 存活性 | GitHub 的 `schedule` 可能延迟甚至整轮跳过（2026-10-06/07 实测只有一次 `schedule` 运行）；`monitor-update.yml` 每 6 小时检查 `Auto Data Update` 的新鲜度，超过 30 小时没有触发、运行停住、最近一次失败或长期没有成功时创建带 `automation` 标签的议题，恢复后自动评论并关闭 |
| 上游校验 | 用 `ETag` / `Last-Modified` 条件请求校验 GeoNames、Natural Earth、i18n-iso-countries；未变化时返回 **304，不传输正文** |
| 更新检测 | 用「来源文件 SHA256 + 构建配置 + 发布器修订」计算发布指纹，与上一次发布对比；无变化则跳过发布，避免无意义的版本与重复导入 |
| 构建 | 重新生成四级行政层级、汉化 `cities500`、导出 7 种展示粒度 × 完整/默认共 14 个地理数据变体与规范数据集 |
| 校验 | 文件完整性、GeoNames ID 去重、CN/HK/TW/MO 展示名零缺失、国家名称覆盖率全部通过才允许发布 |
| 发布 | 更新滚动发布 `auto-release`、创建当日至多一个不可变快照 `data-YYYY-MM-DD`（同日后续修订用 `data-YYYY-MM-DD-sha-<短 SHA>`）、推送两个多架构镜像 |
| 保留策略 | 默认保留最近 3 个 `data-*` 快照；达到策略期限后自动清理，手动修改策略除外 |
| 失败处理 | 任一阶段失败自动创建或更新带 `automation` 标签的议题，并附上运行链接 |

工作流分工：

- `update-data.yml`：调用可复用的 `_build-data.yml`，完成增量校验、指纹比对、发布、快照清理与失败通知；
- `ci.yml`：每次提交执行静态检查、单元测试与镜像冒烟构建；
- `release.yml`：手动创建 Immich 对齐版本发布（`X.Y.Z.N`，强制重新构建与推送）；
- `cleanup.yml`：每周清理超出保留策略的 `data-*` 快照、Actions 运行记录与 GHCR 版本，稳定前可启用 `prune-all`；
- `monitor-update.yml`：每 6 小时检查自动数据更新的新鲜度，异常时创建 `automation` 议题，恢复后自动关闭。

你只需要定期 `docker compose pull`，或使用发布的固定地址 `releases/latest/download/immich-cn-geodata-admin2-default-v1.zip`，即可持续获得最新数据。

## 快速开始

### 方式一：镜像直用

`webees/immich-cn-server` 基于官方 `immich-server`，在启动时把中文地理数据注入到目标目录；仍需要按 Immich 官方要求配置数据库、缓存与持久化目录。示例 Compose 默认通过 `IMMICH_CN_GHCR_MIRROR=ghcr.nju.edu.cn` 拉取；完整示例见 [examples/compose.server.yml](examples/compose.server.yml)。

```yaml
# docker-compose.yml（只列出需要改动的部分）
services:
  immich-server:
    image: ${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn-server:latest
    environment:
      # 中国本地化默认时区
      TZ: Asia/Shanghai
      # 可选：切换行政区展示粒度，默认 {admin_2}
      IMMICH_CN_PATTERN: "{admin_2} {admin_3}"
      # 可选：强制 Immich 重新导入地理数据
      IMMICH_CN_FORCE_RELOAD: "1"
```

### 方式二：数据挂载

如果你希望继续使用官方 `immich-app/immich-server` 镜像，可以用数据镜像提供文件；示例默认走中国大陆可达的 GHCR 镜像源，可用 `IMMICH_CN_GHCR_MIRROR=ghcr.io` 回退官方源：完整示例见 [examples/compose.volume.yml](examples/compose.volume.yml)。

```yaml
services:
  immich-server:
    image: ${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/immich-app/immich-server:release
    volumes:
      - ./immich-cn/geodata:/build/geodata:ro
```

```bash
# 一次性把数据镜像中的文件复制到宿主机目录
docker run --rm -v "$PWD/immich-cn:/out" \
  "${IMMICH_CN_GHCR_MIRROR:-ghcr.nju.edu.cn}/webees/immich-cn:latest" \
  --target /out
```

### 方式三：发布下载

在 [发布页面](https://github.com/webees/immich-cn/releases) 下载两个资产，按下面命令解压即可得到与挂载路径一致的目录结构：

```bash
curl -fsSL -o immich-cn-geodata-admin2-default-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-geodata-admin2-default-v1.zip
curl -fsSL -o immich-cn-i18n-json-v1.zip \
  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-i18n-json-v1.zip
unzip -o immich-cn-geodata-admin2-default-v1.zip -d .
mkdir -p i18n-iso-countries
unzip -o immich-cn-i18n-json-v1.zip -d i18n-iso-countries
```

`immich-cn-geodata-*.zip` 里只有 `geodata/`；国家名称覆盖单独发布为 `immich-cn-i18n-json-v1.zip`，其成员是 Immich 1.136.0 ~ 3.2.x 读取的 `langs/` 目录下 `en.json` 与上游 `LICENSE`，所以要解压到 `i18n-iso-countries/` 下才对得上后面的挂载路径。Immich 3.3.0 起改读 `countryInfo.txt`，不需要这个覆盖包。

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

# 全流程：获取 → 翻译 → 打包 → 校验，默认无需 API Key
immich-cn all
```

产物位于 `dist/`：规范数据集 `immich-cn-dataset-sqlite-v1.zip`、Immich 默认粒度 `immich-cn-geodata-admin2-default-v1.zip`、`immich-cn-geodata-admin2-full-v1.zip`（数据增强版）、各展示粒度变体、`immich-cn-checksums-sha256-v1.txt` 与 `immich-cn-manifest-json-v1.json`。

### 方式五：静态加速

需要把 Immich 放在国内 CDN 或反向代理后面时，可以使用 [examples/compose.acceleration.yml](examples/compose.acceleration.yml) 和 [examples/nginx/immich-cn.conf](examples/nginx/immich-cn.conf)。该示例只对 `/_app/immutable/*` 开启长期缓存，HTML、API、原始照片与视频默认绕过，避免把私有内容写进公共缓存。

jsDelivr 等免费 CDN 只作为 GitHub 分支、标签或提交中静态文件的**可选**通道；它不能直接代理 GitHub 发布资产，也不保证中国大陆线路质量。完整缓存矩阵、jsDelivr 实测边界、地图同源加速与校验命令见 [中国本地化与加速](docs/china.md)。

默认 CDN 基址使用中国加速候选 `cdn.jsdmirror.com`，可用 `IMMICH_CN_JSDELIVR_BASE` 或 `scripts/jsdelivr_url.py --base` 改为用户信任的端点；第三方镜像源必须验证 TLS 与 SHA256，不能视为官方回源。

### 配置总览

本节列出当前仓库的全部配置入口。默认值以 Compose 示例与实现为准；未列出的 Immich 变量保持官方默认。静态资源加速默认关闭，启用方式是切换 [examples/compose.acceleration.yml](examples/compose.acceleration.yml) 并挂载 [examples/nginx/immich-cn.conf](examples/nginx/immich-cn.conf)。

#### 服务端镜像

适用于 `webees/immich-cn-server`，也适用于将数据目录挂载到官方 `immich-app/immich-server` 的部署。

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_PATTERN` | `{admin_2}` | 展示粒度，例如 `{admin_2} {admin_3}`；取值见「展示粒度」 |
| `IMMICH_CN_FORCE_RELOAD` | `0` | 设为 `1` 时把 `geodata-date.txt` 更新为当前北京时间，强制重新导入 |
| `IMMICH_CN_GEODATA_DIR` | `/opt/immich-cn/geodata` | 镜像内地理数据源目录 |
| `IMMICH_CN_LANGS_DIR` | `/opt/immich-cn/i18n-iso-countries/langs` | 国家名称覆盖目录，适用于 Immich 1.136.0 ~ 3.2.x |
| `IMMICH_CN_PATTERNS_TABLE` | `/opt/immich-cn/immich-cn-patterns-tsv-v1.gz` | 运行时切换粒度所用的变体表 |
| `IMMICH_BUILD_DATA` | `/build` | Immich 构建数据根目录；数据写入 `$IMMICH_BUILD_DATA/geodata` |
| `IMMICH_CN_DATA_DATE` | 构建时写入 | 只读数据批次元信息 |

#### 数据镜像

适用于 `webees/immich-cn`，入口命令是 `immich-cn-install`。

| 变量或参数 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_TARGET` | `/out` | 释放目录，等价于 `--target` |
| `IMMICH_CN_PATTERN` | `{admin_2}` | 释放时的展示粒度，等价于 `--pattern` |
| `IMMICH_CN_GEODATA_DIR` | `/opt/immich-cn/geodata` | 镜像内地理数据源目录 |
| `IMMICH_CN_LANGS_DIR` | `/opt/immich-cn/i18n-iso-countries` | 国家名称覆盖目录，适用于 Immich 1.136.0 ~ 3.2.x |
| `IMMICH_CN_PATTERNS_TABLE` | `/opt/immich-cn/immich-cn-patterns-tsv-v1.gz` | 释放时切换粒度所用的变体表 |
| `--target <目录>` | `/out` | 释放目录，优先级高于 `IMMICH_CN_TARGET` |
| `--pattern '<pattern>'` | `{admin_2}` | 展示粒度，优先级高于 `IMMICH_CN_PATTERN` |
| `--geodata-only` | 关闭 | 只释放 `geodata/`；Immich 3.3.0 及以上不需要国家名称覆盖 |

#### 网络与加速

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_CN_GHCR_MIRROR` | `ghcr.nju.edu.cn` | Compose 拉取前缀；可改为 `ghcr.io` 或其他可信镜像源 |
| `IMMICH_CN_JSDELIVR_BASE` | `https://cdn.jsdmirror.com` | 可选静态文件加速基址；不能代理 GitHub 发布资产 |
| `IMMICH_CN_HTTP_PORT` | `8080` | 仅加速示例中的 Nginx 宿主机端口 |
| CDN 静态资源缓存 | 关闭 | 需要时使用加速示例，并只缓存 `/_app/immutable/*` |

#### 构建与提供方

默认离线构建不需要 API Key；`AMAP_API_KEY` 仅在 `--provider amap` 时必填。

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `AMAP_API_KEY` | 无 | 高德密钥；`--provider auto` 缺少时回退离线并告警 |
| `IMMICH_CN_AMAP_QPS` | `3` | 高德请求速率上限 |
| `IMMICH_CN_AMAP_BATCH_SIZE` | `20` | 高德批量逆地理编码的每批坐标数 |
| `IMMICH_CN_AMAP_COUNTRIES` | `CN,HK,MO` | 使用高德的国家或地区代码 |
| `IMMICH_CN_NOMINATIM_QPS` | `1` | Nominatim 速率上限；服务条款要求为 1 |
| `IMMICH_CN_NOMINATIM_COUNTRIES` | `TW,JP` | 使用 Nominatim 的国家或地区代码 |
| `IMMICH_CN_LOG_LEVEL` | `INFO` | 构建日志级别 |

构建参数包括 `--provider`、`--chinese-variant`、`--patterns`、`--extra-countries`、`--min-population`、`--revalidate`、`--force`、`--skip-fetch`、`--work-dir`、`--dist-dir`、`--cache-dir`、`--config-dir`、`--jobs`、`--keep-raw`、`--clean`、`--quiet`；默认值与边界见 [本地开发](docs/development.md)。

#### 照片时区工具

| 变量或参数 | 默认值 | 说明 |
|:--|:--|:--|
| `IMMICH_API_KEY` | 无 | 执行写入时必填；需要 `asset.update` 权限 |
| `IMMICH_BASE_URL` | `http://localhost:2283` | Immich 服务地址 |
| `--timezone` | `Asia/Shanghai` | 要写入资产的 IANA 时区 |
| `--apply` | 关闭 | 默认试运行；显式传入后才写入 Immich |

#### 上游 Immich 配置

以下变量属于 Immich 上游契约，本项目只保留或透传，默认不覆盖：`TZ`、`IMMICH_CONFIG_FILE`、`IMMICH_HELMET_FILE`、`IMMICH_TRUSTED_PROXIES`、`IMMICH_WORKERS_INCLUDE`、`IMMICH_WORKERS_EXCLUDE`、`IMMICH_ALLOW_SETUP`、`IMMICH_IGNORE_MOUNT_CHECK_ERRORS`、`IMMICH_ALLOW_EXTERNAL_PLUGINS`。完整边界见 [Immich 集成契约](docs/immich-integration.md)。

### 刷新生效

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
| `{admin_2} {admin_4}` | 苏州市 周市镇 |
| `{admin_3} {admin_4}` | 昆山市 周市镇 |
| `{admin_2} {admin_3} {admin_4}` | 苏州市 昆山市 周市镇 |

存在至少一个非空层级时，显示名会自动回退到上一级；若全部层级为空，构建校验应拒绝该记录。完整的组合规则见 [架构设计](docs/architecture.md)。

> [!NOTE]
> 默认（离线）数据在中国大陆的 `admin_4` 通常回退到区县：GeoNames 的乡镇级 `ADM4` 要素不少（实测 11,878 条），但带 `admin4` 代码的只有 73 条，拼不出第四级层级。需要精确到乡镇时，配置 `AMAP_API_KEY` 并加上 `--provider amap`。

## 数据来源

| 数据 | 用途 | 许可 |
|:--|:--|:--|
| [GeoNames](https://download.geonames.org/export/dump/) `cities500` / `admin*Codes` / `alternateNamesV2` / 国家数据转储 | 地点、行政区、中文别名 | CC BY 4.0 |
| [Natural Earth](https://www.naturalearthdata.com/) `ne_10m_admin_0_countries` | 无城市点时回退到国家边界 | 公有领域 |
| [i18n-iso-countries](https://github.com/michaelwittig/node-i18n-iso-countries) | 国家名称中文覆盖（Immich 3.2.x 及以下；3.3.0 起改用 `countryInfo.txt`） | MIT |
| OpenStreetMap / Nominatim（可选） | 补充海外行政区 | ODbL 1.0 |
| 高德地图（可选） | 补充中国大陆区县与乡镇 | 高德开放平台条款 |

> 代码采用 MIT，但**生成的地理数据制品不适用 MIT**，请阅读 [许可与署名](docs/licensing.md)。

## 文档索引

- [架构设计](docs/architecture.md)
- [中国本地化](docs/china.md)
- [集成契约](docs/immich-integration.md)
- [规范约定](docs/conventions.md)
- [数据格式](docs/data-format.md)
- [数据来源](docs/data-sources.md)
- [部署说明](docs/deployment.md)
- [照片时区](docs/timezone.md)
- [镜像发布](docs/packages.md)
- [运维手册](docs/operations.md)
- [本地开发](docs/development.md)
- [许可署名](docs/licensing.md)

## 许可声明

源代码、配置、持续集成工作流与文档以 [MIT](LICENSE) 发布；数据库与地理数据制品不适用 MIT，署名要求汇总在 [NOTICE](NOTICE)，完整说明见 [许可与署名](docs/licensing.md)。

## 致谢说明

- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)：早期中文 Immich 地理数据思路提供了启发；本项目按独立实现组织，当前树未引用或打包该项目的代码与人工整理数据（核查方式见 [规范与约定](docs/conventions.md)）。
- [Immich](https://github.com/immich-app/immich)：反向地理编码的实现与文档。
- [GeoNames](https://www.geonames.org/)、[Natural Earth](https://www.naturalearthdata.com/)、[OpenStreetMap](https://www.openstreetmap.org/)：开放地理数据。
