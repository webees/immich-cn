# 许可与署名

仓库根目录的 [NOTICE](../NOTICE) 汇总了各数据源的署名要求，本文件给出完整说明与再分发注意事项。

> 本文件是工程与合规信息说明，不是法律意见。许可证的最终解释和适用义务应由使用者结合实际使用方式自行确认。

## 代码许可

本项目源码、配置、CI 工作流与文档以 [MIT](../LICENSE) 发布。

`immich-cn-server` 镜像包含上游 Immich 服务端的 [AGPL-3.0-only](https://github.com/immich-app/immich/blob/main/LICENSE) 代码，因此该组合镜像的整体许可必须是 `AGPL-3.0-only AND MIT`，不能只按本项目的 MIT 代码声明。纯数据镜像 `immich-cn` 不包含 Immich 服务端代码。

## 数据许可

**数据制品不适用 MIT。** `dist/*.zip`（包括规范数据集 `immich-cn-dataset-sqlite-v1.zip`）、镜像中的 `geodata` 目录等产物来自多个上游数据源，再分发时必须遵守各自的许可：

| 来源 | 许可 | 要求 |
|:--|:--|:--|
| GeoNames | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 保留署名（GeoNames） |
| Natural Earth | 公有领域 | 无强制要求，建议署名 |
| OpenStreetMap / Nominatim（可选） | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | 署名 + 派生数据库同许可 |
| 高德地图（可选） | 高德开放平台服务条款 | 默认不随本项目制品再分发 |
| i18n-iso-countries | MIT | 保留版权声明 |

### 默认制品

使用默认提供方（`offline`）构建的制品包含 GeoNames 与 Natural Earth 数据，再分发时应保留以下署名：

> 地理数据来源于 GeoNames（https://www.geonames.org/），以 CC BY 4.0 授权；国界数据来源于 Natural Earth（https://www.naturalearthdata.com/），属公有领域。数据处理由 immich-cn（https://github.com/webees/immich-cn）完成。

### ODbL 数据

如果启用了 `nominatim` 提供方，制品中会包含 OpenStreetMap 派生数据：

> © OpenStreetMap contributors，数据以 ODbL 1.0 授权。

ODbL 对“派生数据库”设有同许可条件。再分发包含 OSM/Nominatim 数据的制品时，应自行确认并满足相应的署名与许可义务。

### 高德数据

`AMAP_API_KEY` 属于调用者自己的账号。高德开放平台条款可能限制地理编码结果的存储、展示或再分发，因此本项目的默认构建**不使用**高德，CI 中也只在显式配置密钥与 `--provider amap` 时才会调用。若需要分发高德派生数据，应先独立审阅并确认符合高德的服务条款。

## 独立声明

本项目按独立实现组织：本仓库当前树中的数据处理代码、配置与构建脚本由本项目维护，许可与再分发义务以本文和 [NOTICE](../NOTICE) 为准。项目使用 Immich、GeoNames、Natural Earth、i18n-iso-countries 等公开接口与公开数据格式。核查范围、关键词与为什么本文不对历史过程或法律状态作结论，见 [规范与约定](conventions.md)。

如果你认为本项目侵犯了你的权利，请提交 issue，我们会尽快处理。
