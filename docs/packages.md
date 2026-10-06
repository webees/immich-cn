# Packages 说明

GHCR 中有两个容器包，它们不是重复镜像，也不是可互换别名：

| Package | 角色 | 基础 | 入口 | 目标平台 |
|:--|:--|:--|:--|:--|
| `ghcr.io/webees/immich-cn` | 纯数据镜像，把 geodata 释放到宿主机目录 | Alpine | `immich-cn-install` | `linux/amd64`, `linux/arm64` |
| `ghcr.io/webees/immich-cn-server` | 开箱即用的 Immich server 覆盖镜像 | 官方 `immich-server` | `immich-cn-entrypoint` + `start.sh` | `linux/amd64`, `linux/arm64` |

## 为什么有两个

`immich-cn` 只负责分发数据，适合继续使用官方 Immich 镜像并挂载数据目录的用户。
`immich-cn-server` 在官方 server 镜像启动前注入数据，适合希望减少手工挂载步骤的用户。

两者都包含同一份 geodata，但用途、入口和升级边界不同。不要用数据镜像替换 Immich server，
也不要假设两个包的 `latest` 摘要相同。

## 标签

| Package | 标签 | 用途 |
|:--|:--|:--|
| `immich-cn` | `latest` | 最近一次成功构建的数据 |
| `immich-cn` | `YYYY-MM-DD` | 当日最新数据，同日重跑可更新 |
| `immich-cn` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn` | `<语义化版本>` | `Release` 工作流创建的版本标签 |
| `immich-cn-server` | `latest` | 最近数据 + 默认 Immich `release` |
| `immich-cn-server` | `release` | 与 Immich `release` 标签对齐 |
| `immich-cn-server` | `release-YYYY-MM-DD` | 当日最新数据与 Immich `release`，同日重跑可更新 |
| `immich-cn-server` | `sha-<短提交>` | 对应控制面代码提交 |
| `immich-cn-server` | `<语义化版本>` | `Release` 工作流创建的版本标签 |

生产环境应固定到 Git SHA 或完整 digest；日期标签只用于当日跟踪。

## 供应链证据

每次镜像发布都会：

- 生成 BuildKit provenance 与 SBOM；
- 在数据目录中保留 i18n 语言文件的上游 `LICENSE`；
- 执行 Trivy 漏洞和许可证扫描；数据镜像的 `HIGH`/`CRITICAL` 阻断，Immich 覆盖镜像只阻断
  相对官方基础镜像新增的漏洞，继承项写入显式例外报告；
- 通过 GitHub OIDC 使用 Cosign keyless 签名；
- 推送后按最终 digest 重新拉取并执行入口 smoke test。

验证签名时以最终 digest 为准：

```bash
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp 'https://github.com/webees/immich-cn/.github/workflows/.*' \
  ghcr.io/webees/immich-cn@sha256:<digest>
```

`healthcheck` 和运行时数据路径属于 `immich-cn-server` 的基础 Immich 契约；数据镜像只保证
`--target` 目录中的 geodata 文件结构可被 Immich 挂载使用。

## 不可混用边界

- `immich-cn-server:release-YYYY-MM-DD` 固定的是本项目数据与该次构建使用的 Immich 标签；
- `immich-cn:YYYY-MM-DD` 不包含 Immich 代码，不能直接运行 server；
- 自定义 Immich 版本时使用 `release.yml` 或 `workflow_dispatch` 的 `immich-version` 输入；
- 回滚镜像前确认 Immich 数据目录与 `i18n-iso-countries` 路径仍匹配目标 Immich 版本。
