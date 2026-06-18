# 环境配置

> 属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：dev、e2e 和 prod 部署的环境特定配置。

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 环境配置规范初稿：dev、e2e、prod |
| 2026-06-17 | 0.2.0 | 第 3 节对比表：新增 LLM +1 额外重试说明；第 5 节：新增选项 B（云密钥管理器）作为替代配置策略 |

---

## 1. 三种环境

| 环境 | 用途 | LLM | 重试 | 检查点 | 工具 |
|-------------|---------|-----|-------|-------------|-------|
| **dev** | 本地开发、规范编写、快速迭代 | 真实或模拟 | 短 | 内存 | 模拟 / 仅本地 |
| **e2e** | CI 流水线、评估运行、集成测试 | 真实（评估上下文） | 标准 | 内存或本地数据库 | 模拟 + 真实（非破坏性） |
| **prod** | 生产部署 | 真实 | 完整 + 1 次 LLM 重试 | PostgreSQL / Redis | 真实（含权限强制执行） |

## 2. 环境变量层级

```
.env              ← 基础默认值（已提交，安全值）
.env.local        ← 本地覆盖（gitignored，密钥）
.env.{env}        ← 环境特定覆盖（dev / e2e / prod）
```

加载顺序：`.env` → `.env.local` → `.env.{ENV}`。后加载的覆盖先加载的。

### 2.1 `.env`（基础，已提交）

```bash
# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=4096

# 框架
LOG_LEVEL=info
CONTEXT_WINDOW_SIZE=6
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BACKOFF=exponential
RETRY_BASE_DELAY_MS=500
RETRY_MAX_DELAY_MS=10000
GAP_THRESHOLD=0.3

# 检查点
CHECKPOINT_BACKEND=in_memory
```

### 2.2 `.env.dev`（本地开发）

```bash
# 宽松：加快迭代
LOG_LEVEL=debug
LLM_MODEL=gpt-4o-mini          # 开发环境使用更便宜的模型
MAX_TRANSFORM_ATTEMPTS=1       # 快速失败
RETRY_BASE_DELAY_MS=100
CHECKPOINT_BACKEND=in_memory
GAP_THRESHOLD=0.5              # 宽松（dev 中 50% 可接受）

# 工具
ALLOW_DANGEROUS_OPS=true       # 开发环境跳过危险操作审批
MOCK_EXTERNAL_APIS=true        # 模拟支付/保费 API
```

### 2.3 `.env.e2e`（CI / 评估）

```bash
# 严格：匹配生产行为以便准确评估
LOG_LEVEL=info
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0              # 确定性评估
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BASE_DELAY_MS=500
GAP_THRESHOLD=0.3              # 与生产一致

# 评估特定
EVAL_MODE=true
EVAL_DATASET=home-insurance-eval
LANGSMITH_TRACING=true         # 追踪评估运行
ALLOW_DANGEROUS_OPS=false      # 与生产相同严格度
MOCK_EXTERNAL_APIS=true        # 模拟支付 API，但测试真实逻辑
```

### 2.4 `.env.prod`（生产）

```bash
# 严格：完整护栏
LOG_LEVEL=warn
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BACKOFF=exponential
RETRY_BASE_DELAY_MS=500
RETRY_MAX_DELAY_MS=10000
GAP_THRESHOLD=0.3

# 生产基础设施
CHECKPOINT_BACKEND=postgresql
CHECKPOINT_DSN=${POSTGRES_DSN}
LANGSMITH_TRACING=true
ALLOW_DANGEROUS_OPS=false         # 必须通过人工审批关卡
MOCK_EXTERNAL_APIS=false          # 全部使用真实 API

# 安全
PII_SCRUBBING=enabled
AUDIT_LOG_RETENTION_DAYS=365
SENSITIVE_FIELD_MASK=partial_mask
```

## 3. 各环境阈值对比

> **注意：** LLM +1 额外重试是通用的 — 在所有环境中都适用，无论基础重试预算如何。短/标准/完整仅指基础重试预算（`max_attempts`）；LLM 节点始终在此基础上额外 +1。

| 配置 | dev | e2e | prod |
|--------|-----|-----|------|
| `LLM_MODEL` | gpt-4o-mini | gpt-4o | gpt-4o |
| `LOG_LEVEL` | debug | info | warn |
| `MAX_TRANSFORM_ATTEMPTS` | 1 | 2 | 2 |
| `RETRY_BASE_DELAY_MS` | 100 | 500 | 500 |
| `GAP_THRESHOLD` | 0.5 | 0.3 | 0.3 |
| `CHECKPOINT_BACKEND` | in_memory | in_memory | postgresql |
| `ALLOW_DANGEROUS_OPS` | true | false | false |
| `MOCK_EXTERNAL_APIS` | true | true | false |
| `PII_SCRUBBING` | optional | enabled | enabled |
| `LANGSMITH_TRACING` | false | true | true |

## 4. `framework.yaml` 环境特定章节

```yaml
# framework.yaml
environments:
  dev:
    llm:
      model: "${LLM_MODEL}"
      temperature: 0
    rule_engine:
      default: business_rules    # 开发环境使用较简单的引擎
    retry:
      max_attempts: 1
    tools:
      mock_external: true
      allow_dangerous: true
    goal_check:
      gap_threshold: 0.5

  e2e:
    llm:
      model: "${LLM_MODEL}"
      temperature: 0
    rule_engine:
      default: durable_rules     # 与生产匹配
    retry:
      max_attempts: 2
    tools:
      mock_external: true        # 模拟 API 但使用真实逻辑
      allow_dangerous: false
    goal_check:
      gap_threshold: 0.3
    errorNode:
      strategy: escalate_to_human

  prod:
    llm:
      model: "${LLM_MODEL}"
      temperature: 0
      provider: "${LLM_PROVIDER}"
    rule_engine:
      default: durable_rules
    retry:
      max_attempts: 2
      llm_extra_retry: 1
      backoff: exponential
      base_delay_ms: 500
      max_delay_ms: 10000
    tools:
      mock_external: false
      allow_dangerous: false
    goal_check:
      gap_threshold: 0.3
      on_gap: error_422
    pii:
      scrubbing: enabled
      masking_strategy: partial_mask
    audit:
      retention_days: 365
    checkpoint:
      backend: postgresql
      dsn: "${POSTGRES_DSN}"
    errorNode:
      strategy: escalate_to_human
      human_timeout_minutes: 15
```

## 5. 环境感知的引擎启动

```yaml
# framework.yaml — 环境感知的配置加载
# 框架在启动时选择匹配的环境章节。
# 通过以下方式设置：ENV=dev   或   ENV=e2e   或   ENV=prod

framework:
  version: "0.2.0"
  env: "${ENV:-dev}"   # 启动时解析，默认为 dev

  config_loading:
    strategy: layered               # 选项 A：环境文件层级
    sources:
      - type: file
        path: ".env"                # 基础默认值（已提交）
        required: true
      - type: file
        path: ".env.local"          # 本地覆盖（gitignored）
        required: false
      - type: file
        path: ".env.${ENV}"         # 环境特定覆盖
        required: false
    merge: later_overrides_earlier

# 选项 B：云密钥管理器（替代环境文件方式）
#   strategy: cloud_secret_manager
#   sources:
#     - type: aws_secrets_manager
#       region: "${AWS_REGION}"
#       secret_id: "deterministic-workflow/${ENV}"
#     - type: hashicorp_vault
#       address: "${VAULT_ADDR}"
#       mount_path: "secret/deterministic-workflow/${ENV}"
#       auth_method: kubernetes  # 或 token、approle、aws
#   merge: cloud_overrides_file   # 云密钥覆盖 .env 默认值

  domain_models:
    - "domain-models/home-insurance.yaml"

  workflows:
    - "workflows/home_insurance_quote.yaml"

# 启动时框架执行以下步骤：
# 1. 读取 framework.yaml → 解析 ${ENV} → 选择 environments.{env} 章节
# 2. 按顺序加载并合并环境文件（.env → .env.local → .env.{ENV}）
# 3. 根据环境规则验证必需的配置项
# 4. 使用合并后的配置初始化引擎

environments:
  # 各环境覆盖详见第 4 节
  dev: { ... }
  e2e: { ... }
  prod: { ... }
```

---

## 6. 开放问题

1. **密钥轮换策略**：密钥（API 密钥、数据库凭据）应如何在不同环境间轮换？框架应支持通过云提供商密钥存储（AWS Secrets Manager、GCP Secret Manager）自动轮换，还是手动轮换对 v0 版本足够？

2. **无需重启的配置热重载**：框架是否应支持运行时配置变更（例如 LLM 模型切换、日志级别变更）而无需重启进程？如果支持，应使用文件监视器、配置服务器轮询机制还是基于推送的事件系统？

3. **多区域环境配置同步**：对于全球部署的实例，环境配置应如何跨区域保持同步？选项：基于 GitOps（配置即代码，通过 CI/CD 同步）、带区域缓存的集中式配置存储，或带漂移检测的各区域独立配置。

4. **按环境的 LLM 提供商路由**：框架是否应支持根据不同环境将 LLM 调用路由到不同提供商（例如 dev→OpenAI、e2e→OpenAI、prod→Azure OpenAI）以满足合规要求？如果支持，跨提供商的回退链应如何工作？

5. **启动时的配置验证**：框架应在启动时验证配置完整性（缺少必需键时快速失败）还是使用宽松默认值？每个环境适用哪些验证规则（例如 prod 必须配置 `CHECKPOINT_DSN`，dev 可以省略）？

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 第 4.1 节，框架原则
- [工具生态](./2026-06-17-tool-ecosystem.md) — LangSmith、LangGraph CLI
- [路由与执行](./2026-06-17-routing-execution-layer-design.md) — 重试预算、权限模型
- [响应生成](./2026-06-17-response-generation-layer-design.md) — 差距阈值、PII 清理
