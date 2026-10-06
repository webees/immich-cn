# 许可与署名

仓库根目录的 [NOTICE](../NOTICE) 汇总了各数据源的署名要求，本文件给出完整说明与再分发注意事项。

## 代码

本项目源码、配置、CI 工作流与文档以 [MIT](../LICENSE) 发布。

## 数据制品

**数据制品不适用 MIT。** `dist/*.zip`、镜像中的 `geodata` 目录等产物来自多个上游数据源，
再分发时必须遵守各自的许可：

| 来源 | 许可 | 要求 |
|:--|:--|:--|
| GeoNames | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 保留署名（GeoNames） |
| Natural Earth | Public Domain | 无强制要求，建议署名 |
| OpenStreetMap / Nominatim（可选） | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | 署名 + 派生数据库同许可 |
| 高德地图（可选） | 高德开放平台服务条款 | 默认不随本项目制品再分发 |
| i18n-iso-countries | MIT | 保留版权声明 |

### 默认制品的许可

使用默认 provider（`offline`）构建的制品包含 GeoNames 与 Natural Earth 数据，
再分发时应保留以下署名：

> 地理数据来源于 GeoNames（https://www.geonames.org/），以 CC BY 4.0 授权；
> 国界数据来源于 Natural Earth（https://www.naturalearthdata.com/），属公有领域。
> 数据处理由 immich-cn（https://github.com/webees/immich-cn）完成。

### 使用 ODbL 数据时

如果启用了 `nominatim` provider，制品中会包含 OpenStreetMap 派生数据：

> © OpenStreetMap contributors，数据以 ODbL 1.0 授权。

由于 ODbL 对"派生数据库"有相同许可要求，如果你再分发这类制品，需要同时提供 ODbL 授权。

### 使用高德数据时

`AMAP_API_KEY` 属于调用者自己的账号。高德开放平台的条款通常限制地理编码结果的再分发，
因此本项目的默认构建**不使用**高德，CI 中也只在你显式配置 Secret 与 `--provider amap` 时才会调用。
若需要分发高德派生数据，请自行确认是否符合高德的服务条款。

## 项目独立性

本仓库以独立实现为原则，不包含从其他同类项目复制的源代码或人工整理的数据文件。
项目使用 Immich、GeoNames、Natural Earth、i18n-iso-countries 等公开接口和公开数据格式；
各部分许可与再分发义务以本文和 [NOTICE](../NOTICE) 为准。

如果你认为本项目侵犯了你的权利，请提交 issue，我们会尽快处理。
