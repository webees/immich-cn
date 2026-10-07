# immich-cn

> **immich-cn 为 Immich 提供中国本地化的反向地理编码地理数据**：核心是中文地名、中文与拼音检索、行政层级，以及自动发布与镜像；地图、EXIF 时区、CDN 与缓存、Nginx 示例属于可选辅助能力，不构成对 Immich 界面的复刻。

[![CI](https://github.com/webees/immich-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/ci.yml) [![Data Update](https://github.com/webees/immich-cn/actions/workflows/update-data.yml/badge.svg)](https://github.com/webees/immich-cn/actions/workflows/update-data.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Container](https://img.shields.io/badge/ghcr.io-immich--cn-blue)](https://github.com/webees/immich-cn/pkgs/container/immich-cn)

Immich 的反向地理编码默认输出英文地名。本项目的核心范围是让照片地图显示中文地名，并支持中文、拼音、英文与繁体检索。地图、EXIF 时区、CDN 与缓存、Nginx 回源属于可选支持，不是对 Immich 的完整本地化复刻。完整范围、本地化现状与加速边界见 [中国本地化与加速](docs/china.md)。术语、命名与文档写法遵循 [规范与约定](docs/conventions.md)。

本项目按独立实现组织：本仓库当前树中的代码、配置、持续集成工作流与数据构建脚本由本项目维护，没有引用或打包同类项目的代码文件与人工整理数据文件；核查范围、关键词与边界见 [规范与约定](docs/conventions.md)。文末「致谢」记录了与本项目相关的上游思路来源。对 Immich 文本格式的兼容属于消费端适配，不定义本项目的内部数据模型。以上描述的是当前仓库状态与项目声明，不是对历史过程或法律状态的结论。本仓库的源代码、配置、工作流与文档采用 **MIT** 许可；生成的数据库与地理数据制品不属于 MIT，数据来源、署名与再分发要求见 [许可与署名](docs/licensing.md)。

设计重点不是复制某个数据格式或使用方式，而是建立自己的规范模型后再适配消费者：

| 维度 | 设计 |
|:--|:--|
| 代码许可 | 代码 MIT；数据制品另有许可与署名要求 |
| 构建入口 | 可测试的 Python 包 + 统一命令行 |
| 外部依赖 | GeoNames、Natural Earth、i18n-iso-countries；可选高德与 Nominatim |
| 数据格式 | 规范 SQLite 数据集 + Immich 适配输出 |
| 行政区粒度 | 7 种展示粒度 × 完整/默认，共 14 个变体 |
| 发布方式 | GitHub 发布 + GHCR 多架构镜像 |
| 更新频率 | 每天自动检查，变化后自动校验并发布 |
| 缓存策略 | 静态资源长期缓存；API、照片与视频不缓存 |
| 来源追溯 | 记录来源哈希、构建配置、发布器修订与输出摘要 |
| 发布校验 | 结构、覆盖率、去重、哈希、容器冒烟、Trivy 与 Cosign |

## 数据模型

本项目不以“保留上游相同格式与相同使用方式”为目标。规范数据模型是第一等产物， `immich-cn-dataset-sqlite-v1.zip` 内含带索引的 SQLite 数据库，直接表达地点、四级行政名、国家、来源哈希与构建元数据；支持 SQLite 3 的工具可以查询和二次开发，具体兼容性取决于客户端版本，不要求先理解 Immich 的文本列约定。

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
| 存活性 | GitHub 的 `schedule` 可能延迟甚至整轮跳过（2026-10-06/07 实测只有一次 `schedule` 运行）；`monitor-update.yml` 每 6 小时检查 `Auto Data Update` 的新鲜度，超过 30 小时没有触发、运行停住、最近一次失败或长期没有成功时创建带 `automation` 标签的 issue，恢复后自动评论并关闭 |
| 上游校验 | 用 `ETag` / `Last-Modified` 条件请求校验 GeoNames、Natural Earth、i18n-iso-countries；未变化时返回 **304，不传输正文** |
| 变更检测 | 用「来源文件 SHA256 + 构建配置 + 发布器修订」计算发布指纹，与上一次发布对比；无变化则跳过发布，避免无意义的版本与重复导入 |
| 构建 | 重新生成四级行政层级、汉化 `cities500`、导出 7 种展示粒度 × 完整/默认共 14 个地理数据变体与规范数据集 |
| 校验 | 文件完整性、GeoNames ID 去重、CN/HK/TW/MO 展示名零缺失、国家名称覆盖率全部通过才允许发布 |
| 发布 | 更新滚动发布 `auto-release`、创建当日至多一个不可变快照 `data-YYYY-MM-DD`（同日后续修订用 `data-YYYY-MM-DD-sha-<短 SHA>`）、推送两个多架构镜像 |
| 保留策略 | 默认保留最近 3 个 `data-*` 快照；达到策略期限后自动清理，手动修改策略除外 |
| 失败处理 | 任一阶段失败自动创建或更新带 `automation` 标签的 issue，并附上运行链接 |

你只需要定期 `docker compose pull`，或使用发布的固定地址 `releases/latest/download/immich-cn-geodata-admin2-default-v1.zip`，即可持续获得最新数据。

## 快速开始

### 方式一：开箱即用镜像

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

### 方式二：数据镜像挂载

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

### 方式三：下载发布数据

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

`immich-cn-geodata-*.zip` 里只有 `geodata/`；国家名称覆盖单独发布为 `immich-cn-i18n-json-v1.zip`，其成员是旧版 Immich 实际读取的 `langs/` 目录下 `en.json` 与上游 `LICENSE`，所以要解压到 `i18n-iso-countries/` 下才对得上后面的挂载路径。Immich 3.3.0 起改读 `countryInfo.txt`，不再需要这个覆盖包。

> [!NOTE]
> 语言包裁剪自**下一次数据发布**起生效。已发布的 `data-2026-10-06` 快照与滚动 `auto-release` 里，`immich-cn-i18n-json-v1.zip` 仍是整套 `langs/*.json`（2026-10-07 实测 74 个成员、191,847 字节，sha256 与清单记录一致）；多出的语言文件不影响挂载，只是体积更大。判据与后续收窄说明见 [软件包说明](docs/packages.md)。

```yaml
volumes:
  - ./geodata:/build/geodata
  # 国家名称覆盖：仅 Immich 1.136.0 ~ 3.2.x 需要（3.3.0 起改读 countryInfo.txt）
  # Immich >= 1.136.0
  - ./i18n-iso-countries/langs:/usr/src/app/server/node_modules/i18n-iso-countries/langs
  # Immich < 1.136.0
  # - ./i18n-iso-countries/langs:/usr/src/app/node_modules/i18n-iso-countries/langs
```

### 方式四：本地自行构建

```bash
git clone https://github.com/webees/immich-cn.git && cd immich-cn
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 全流程：获取 → 翻译 → 打包 → 校验，默认无需 API Key
immich-cn all
```

产物位于 `dist/`：规范数据集 `immich-cn-dataset-sqlite-v1.zip`、Immich 默认粒度 `immich-cn-geodata-admin2-default-v1.zip`、`immich-cn-geodata-admin2-full-v1.zip`（数据增强版）、各展示粒度变体、`immich-cn-checksums-sha256-v1.txt` 与 `immich-cn-manifest-json-v1.json`。

### 方式五：静态资源加速

需要把 Immich 放在国内 CDN 或反向代理后面时，可以使用 [examples/compose.acceleration.yml](examples/compose.acceleration.yml) 和 [examples/nginx/immich-cn.conf](examples/nginx/immich-cn.conf)。该示例只对 `/_app/immutable/*` 开启长期缓存，HTML、API、原始照片与视频默认绕过，避免把私有内容写进公共缓存。

jsDelivr 等免费 CDN 只作为 GitHub 分支、标签或提交中静态文件的**可选**通道；它不能直接代理 GitHub Release 资产，也不保证中国大陆线路质量。完整缓存矩阵、jsDelivr 实测边界、地图同源加速与校验命令见 [中国本地化与加速](docs/china.md)。

默认 CDN 构址使用中国加速候选 `cdn.jsdmirror.com`，可用 `IMMICH_CN_JSDELIVR_BASE` 或 `scripts/jsdelivr_url.py --base` 改为用户信任的端点；第三方镜像源必须验证 TLS 与 SHA256，不能视为官方回源。

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

## 工作流

```
每天 13:23 北京时间（cron）
        │
        ▼
  update-data.yml ──► _build-data.yml（可复用）
        │                    │
        │                    ├─ ETag 条件校验（未变化 → 304）
        │                    ├─ immich-cn all（翻译 → 打包 → 校验）
        │                    ├─ 发布指纹比对（无变化 → 跳过发布）
        │                    └─ 推送多架构镜像
        │
        └──► 发布：auto-release（滚动）+ data-*（不可变快照，保留 3 个）

ci.yml ──► ruff + mypy + pytest + 容器入口校验 + Docker 冒烟构建
release.yml ──► 手动创建语义化版本发布
```

- `update-data.yml`：**自动数据更新**，包含增量校验、指纹比对、发布、快照清理与失败通知。
- `ci.yml`：每次提交执行静态检查、单元测试与镜像冒烟构建。
- `release.yml`：手动创建语义化版本发布（总是强制重新构建与推送）。
- `cleanup.yml`：每周清理旧 `data-*` 快照、Actions 运行历史与 GHCR 版本；稳定前可启用 `prune-all`。
- `monitor-update.yml`：每 6 小时检查自动数据更新的新鲜度；定时任务未触发、运行卡住、最近一次失败或长期没有成功时创建 `automation` 告警 issue，恢复后自动关闭。

## 文档

- [架构设计](docs/architecture.md)
- [中国本地化与加速](docs/china.md)
- [Immich 集成契约](docs/immich-integration.md)
- [规范与约定](docs/conventions.md)
- [数据格式与制品命名](docs/data-format.md)
- [规范与约定](docs/conventions.md)
- [规范数据格式](docs/data-format.md)
- [Data sources and processing](docs/data-sources.md)
- [部署指南](docs/deployment.md)
- [照片拍摄时间与时区](docs/timezone.md)
- [Packages 与供应链](docs/packages.md)
- [运维与常见问题](docs/operations.md)
- [本地开发](docs/development.md)
- [许可与署名](docs/licensing.md)

## 许可

源代码、配置、CI workflow 和文档以 [MIT](LICENSE) 发布；database 和 geodata artifact 不适用 MIT，署名要求汇总在 [NOTICE](NOTICE)，完整说明见 [docs/licensing.md](docs/licensing.md)。

## 致谢

- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)：早期中文 Immich 地理数据思路提供了启发；本项目按独立实现组织，当前树未引用或打包该项目的代码与人工整理数据（核查方式见 [规范与约定](docs/conventions.md)）。
- [Immich](https://github.com/immich-app/immich)：反向地理编码的实现与文档。
- [GeoNames](https://www.geonames.org/)、[Natural Earth](https://www.naturalearthdata.com/)、[OpenStreetMap](https://www.openstreetmap.org/)：开放地理数据。
