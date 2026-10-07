# 安全策略

## 报告漏洞

请通过 GitHub 安全公告（仓库的 Security 标签页 → Report a vulnerability）私下报告，不要在公开议题中披露可利用细节。我们通常会在 7 天内给出初步回复；实际响应时间取决于维护者可用情况，不是服务水平承诺。

## 覆盖范围

与本项目相关的安全问题包括但不限于：

- 下载与解压上游数据时的路径穿越（zip slip）；
- 构建流水线中的命令注入；
- 容器镜像的供应链问题（构建来源、标签覆盖）；
- 对用户敏感信息（如 `AMAP_API_KEY`）的泄露。

## 排除范围

- Immich 自身的安全问题，请反馈到 [immich-app/immich](https://github.com/immich-app/immich/security)；
- 上游数据源的准确性问题（请提议题，而不是安全报告）；
- 由用户自行修改 `config/overrides.toml` 或脚本导致的配置错误。

## 供应链安全

- 镜像构建与推送全部在 GitHub Actions 中完成，使用最小权限的 `GITHUB_TOKEN`；
- 仓库当前工作流中的外部 Action 固定到完整提交 SHA，版本标签仅作为注释保留；更新依赖 Dependabot 或人工审查；
- 所有 `actions/checkout` 显式设置 `persist-credentials: false`，令牌不会留在 `.git/config` 供后续步骤读取；工作流中的 GitHub API 调用优先使用 `gh` + `GH_TOKEN`，Python 脚本在需要直接 HTTP 时使用 `urllib` 并从 `GITHUB_TOKEN` / `GH_TOKEN` 环境变量读取令牌，不打印令牌；
- `docker/build-push-action` 开启 `provenance` 与 `sbom`；
- 推送后的两个镜像均按最终摘要执行 Trivy 漏洞与许可证扫描；在当次扫描数据库和扫描范围内，数据镜像的 `HIGH`/`CRITICAL` 会阻断，Immich 覆盖镜像只阻断相对官方基础镜像“新增”的漏洞；
- 上游基础镜像继承的漏洞会写入 `trivy-server-inherited-vuln.txt` 作为显式例外，许可证报告仅留证，避免把基础镜像正常的 GPL/AGPL 依赖误判成漏洞；
- 两个镜像均通过 GitHub OIDC 使用 Cosign 无密钥签名；
- 每次数据构建都会记录上游文件的 SHA256 到清单；
- 发布制品的规范校验和文件可用于校验下载内容。
