本 Release 由 GitHub Actions 每周自动更新，代表**最新的数据集**。

## 选择文件

| 需求 | 文件 |
|:--|:--|
| 默认（城市级） | `geodata.zip` |
| 数据增强、边界更准 | `geodata_full.zip` |
| 城市 + 区县 | `geodata_admin_2_admin_3.zip` |
| 到乡镇 | `geodata_admin_2_admin_3_admin_4.zip` |

完整变体列表见 `manifest.json`，文件校验值见 `SHA256SUMS`。

## 使用方式

优先使用容器镜像，可一条命令完成挂载或直接替换 Immich 镜像：

```bash
docker pull ghcr.io/webees/immich-cn:latest
docker pull ghcr.io/webees/immich-cn-server:latest
```

详见 [部署指南](https://github.com/webees/immich-cn/blob/main/docs/deployment.md)。

> [!IMPORTANT]
> Immich 只在 `geodata-date.txt` 比上次导入时间更新时才重新导入数据。
> 如果替换数据后没有生效，请把该文件内容改为当前时间（或设置 `IMMICH_CN_FORCE_RELOAD=1`）。
>
> 同一 Release 内所有变体的时间戳相同，因此切换到同一 Release 的其他变体时需要手动调整该文件。

> [!WARNING]
> 反向地理编码取最近点，边界处存在原理性误差。可以尝试 `_full` 变体，
> 或到 [GeoNames](https://www.geonames.org/) 补充缺失地点。
