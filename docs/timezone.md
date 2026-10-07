# 照片拍摄时间与时区

Immich 的照片详情页优先使用 EXIF 的 `dateTimeOriginal` 与 `exifInfo.timeZone`，不是单纯使用容器的 `TZ`。因此只设置 `TZ: Asia/Shanghai` 可以改善服务端日志、存储模板等运行时行为，但不能保证每张照片都显示为北京时间。

## 可选工具

仓库提供 [scripts/set_asset_timezone.py](../scripts/set_asset_timezone.py)，通过 Immich 官方批量资产 API 把资产的 `timeZone` 设置为指定 IANA 时区。工具优先使用 v3.3.0 推荐的 `PATCH /api/assets`，仅在返回 `404`/`405` 时回退到旧版 `PUT /api/assets`。默认值是 `Asia/Shanghai`，默认只做试运行。

```bash
IMMICH_API_KEY='<api-key>' \
IMMICH_BASE_URL='https://immich.example.com' \
python scripts/set_asset_timezone.py \
  --timezone Asia/Shanghai
```

确认统计结果后，再显式执行：

```bash
IMMICH_API_KEY='<api-key>' \
IMMICH_BASE_URL='https://immich.example.com' \
python scripts/set_asset_timezone.py \
  --timezone Asia/Shanghai \
  --apply
```

需要具备 `asset.update` 权限的 API 密钥。工具跳过缺少 `dateTimeOriginal` 或已经是目标时区的资产，并优先通过 `PATCH /api/assets` 批量更新；仅当旧版返回 `404`/`405` 时才回退到 `PUT /api/assets`，避免逐张调用。

## 适用边界

- 该操作修改 Immich 元数据，不修改原始照片文件；服务端可能因此排队写入关联文件（sidecar）。
- 它保留 `dateTimeOriginal` 的时刻，只改变详情页使用的显示时区。若你希望保留照片拍摄地的原始本地时间，不要批量执行。
- 这是一项按需启用的操作，不是镜像启动时的自动改写。是否统一时区取决于用户意图，不能在数据镜像中静默完成。
- 工具按 Immich v3.3.0 的公开 API 接口约定编写，并通过 `httpx.MockTransport` 做 API 行为测试；尚未在本仓库中对真实用户数据库执行批量写入。
