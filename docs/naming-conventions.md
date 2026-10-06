# 命名规范

项目采用职责优先、无历史别名的命名方式。

## Python 模块

模块名必须表达单一职责，避免 `utils`、`helpers`、`common`、`misc` 等无边界名称。

| 旧名 | 现行名 | 职责 |
|:--|:--|:--|
| `artifacts.py` | `artifact_spec.py` | 制品命名规范与解析 |
| `build.py` | `pipeline.py` | 构建流水线编排 |
| `canonical.py` | `dataset.py` | 规范 SQLite 数据集 |
| `chinese.py` | `localization.py` | 中文名称解析 |
| `config.py` | `settings.py` | 配置与上游源定义 |
| `http.py` | `fetching.py` | 下载、缓存与重试 |
| `logging_setup.py` | `logging_config.py` | 日志配置 |
| `models.py` | `domain.py` | 领域数据模型 |
| `package.py` | `packaging.py` | 发布制品打包 |
| `patterns.py` | `display.py` | 展示 pattern 与组合 |
| `ratelimit.py` | `rate_limit.py` | 限速器 |
| `verify.py` | `validation.py` | 制品校验 |

## 文件与测试

- 测试文件名与被测模块对应，例如 `pipeline.py` → `test_pipeline.py`。
- 文件名使用小写 snake_case，不使用版本后缀、`new`、`old`、`final` 等词。
- 发布资产使用 [制品命名规范 v4](artifact-spec.md)，不生成兼容别名。
- 运行时占位符 `{admin_2}` 与制品 profile `admin2` 是不同契约，前者不改，后者不写回花括号。
- 工作流使用 `<动作>-<领域>.yml`，例如 `update-data.yml`、`cleanup.yml`。

## 代码标识符

- 类名使用名词，例如 `BuildResult`、`PackageResult`。
- 函数名使用动词或动词短语，例如 `run_build`、`resolve_artifact`。
- 布尔值使用 `is_`、`has_`、`should_` 前缀。
- 常量使用 `UPPER_SNAKE_CASE`，并注明单位或格式。
- 不使用 `data`、`info`、`temp`、`value` 作为跨作用域名称。

## 架构边界

- `dataset.py` 是规范数据层；
- `packaging.py` 是发布适配层；
- `pipeline.py` 只编排阶段，不实现解析细节；
- `providers/` 只处理外部增强；
- `validation.py` 只校验，不修改制品。
