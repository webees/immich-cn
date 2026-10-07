# 照片拍摄时间与时区

Immich 的照片详情页优先使用 EXIF 的 `dateTimeOriginal` 与 `exifInfo.timeZone`，不是单纯使用 container 的 `TZ`。因此只设置 `TZ: Asia/Shanghai` 可以改善 server log、storage template 等运行时行为，但不能保证每张照片都显示为北京时间。

## 可选工具

仓库提供 [scripts/set_asset_timezone.py](../scripts/set_asset_timezone.py)，通过 Immich 官方 bulk asset API 把 asset 的 `timeZone` 设置为指定 IANA timezone。默认值是 `Asia/Shanghai`，默认只 dry-run。

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

需要具备 `asset.update` permission 的 API key。工具跳过缺少 `dateTimeOriginal` 或已经是目标 timezone 的 asset，并通过 `PUT /api/assets` 批量更新，避免逐张调用。

## 边界

- 该操作修改 Immich metadata，不修改原始照片文件；服务端可能因此排队执行 sidecar write。
- 它保留 `dateTimeOriginal` 的 instant，只改变详情页使用的显示 timezone。若你希望保留照片拍摄地的原始本地时间，不要批量执行。
- 这是一项 opt-in 操作，不是镜像启动时的自动改写。是否统一时区取决于用户意图，不能在数据镜像中静默完成。
- 工具按 Immich v3.3.0 的公开 API contract 编写，并通过 `httpx.MockTransport` 做 API 行为测试；尚未在本仓库中对真实用户数据库执行批量写入。
