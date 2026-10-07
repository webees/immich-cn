# 贡献指南

感谢参与 immich-cn。提交前请先阅读以下约定。

## 开发环境

```bash
make install     # 创建 .venv 并安装依赖
make check       # lint + typecheck + test + docs + workflows + shellcheck
make smoke       # 合成数据端到端冒烟
```

## 提交要求

1. 通过 `make check`；
2. 新增行为需要有对应测试（`tests/`）；
3. 新增数据源或覆盖规则需要在 `docs/data-sources.md` 说明；
4. 变更数据格式或发布流程需要在 `docs/architecture.md` 与 `CHANGELOG.md` 记录；
5. 不要提交 `build/`、`dist/`、`.cache/` 中的产物（已在 `.gitignore` 中忽略）。

## 分支保护

`main` 已启用 Repository Ruleset「保护 main 分支」：

- 禁止删除分支、禁止 force push（non-fast-forward）；
- 必须通过 Pull Request 合并；
- 必须使用 squash 合并并保持线性历史；
- 必须解决全部 review thread，分支必须包含最新 main 后才可合并；
- 必须通过以下状态检查：
  - `静态检查与单元测试 (Python 3.11)`
  - `静态检查与单元测试 (Python 3.12)`
  - `静态检查与单元测试 (Python 3.13)`
  - `Docker 冒烟构建`

Ruleset 当前 `id=24545711`、`enforcement=active`、`bypass_actors` 为空， `strict_required_status_checks_policy=true`，只允许 squash 合并。上面四个名字必须与工作流真实产生的 job 名一致：`scripts/check_workflows.py` 会展开 matrix 模板，拒绝「没有工作流会产生」「由多个工作流同名产生」以及「产生它的工作流没有 pull_request 触发」三种情况。

因此在 ruleset 生效范围内，改动需要先推到功能分支再开 PR。维护者如需保留直推能力，可在 Settings → Rules → Rulesets 中为「Repository admin」添加 bypass actor。

## 地名纠正

优先改 `config/overrides.toml`，并在 PR 描述中给出依据（GeoNames ID 或公开行政资料），例如：

```toml
[admins]
"CN.22" = "北京市"
```

## 代码风格

- Python 3.11+，类型标注齐全，`mypy --strict` 必须通过；
- 使用 `ruff` 统一格式（line-length 120）；
- 注释与日志使用中文，代码标识符使用英文；
- 网络访问必须支持超时、重试与磁盘缓存，并遵守数据源的使用条款。

## 新增提供方

1. 在 `src/immich_cn/providers/` 下实现 `prefetch()` / `enrich()`；
2. 在 `src/immich_cn/providers/__init__.py:build_chain` 中注册；
3. 结果写入 JSONL 缓存，避免重复请求；
4. 补充单元测试并说明在 `docs/data-sources.md`。

## 提交信息

使用 Conventional Commits 风格：

```
feat(provider): 增加某某数据源
fix(build): 修复 XX 情况下缺少 admin2 的问题
docs: 更新部署说明
```

## 许可声明

提交代码即表示你同意以 MIT 许可发布你的贡献。若引入了新的数据源，请在 PR 中说明其许可与再分发限制。
