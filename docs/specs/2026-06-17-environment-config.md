# Environment Configuration

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Environment-specific configuration for dev, e2e, and prod deployments.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial environment config spec: dev, e2e, prod |
| 2026-06-17 | 0.2.0 | Section 3 comparison table: add LLM +1 extra retry note; Section 5: add Option B (Cloud Secret Manager) as alternative config strategy |
| 2026-06-17 | 0.4.0 | Section 3 table: add max_attempts row; add §6 Implementation Options (Env File Hierarchy vs External Config Server) with comparison matrix |
| 2026-06-18 | 0.5.0 | Add LLM_MODEL_ESCALATION_ENABLED, LLM_MODEL_TIERS, LLM_FAILURES_BEFORE_ESCALATION env vars to .env, .env.dev, .env.prod; add model_escalation blocks to framework.yaml per environment (§4); add escalation rows to §3 comparison table |

---

## 1. Three Environments

| Environment | Purpose | LLM | Retry | Checkpoints | Tools |
|-------------|---------|-----|-------|-------------|-------|
| **dev** | Local development, spec authoring, fast iteration | Real or mock | Short | In-memory | Mock / local only |
| **e2e** | CI pipeline, eval runs, integration tests | Real (eval context) | Standard | In-memory or local DB | Mock + real (non-destructive) |
| **prod** | Production deployment | Real | Full + 1 LLM retry | PostgreSQL / Redis | Real (with permission enforcement) |

## 2. Environment Variable Hierarchy

```
.env              ← base defaults (committed, safe values)
.env.local        ← local overrides (gitignored, secrets)
.env.{env}        ← environment-specific overrides (dev / e2e / prod)
```

Load order: `.env` → `.env.local` → `.env.{ENV}`. Later overrides earlier.

### 2.1 `.env` (base, committed)

```bash
# LLM
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=4096
LLM_MODEL_ESCALATION_ENABLED=true
LLM_MODEL_TIERS=openai:gpt-4o-mini→gpt-4o→gpt-4.1;anthropic:claude-haiku→claude-sonnet→claude-opus
LLM_FAILURES_BEFORE_ESCALATION=2

# Framework
LOG_LEVEL=info
CONTEXT_WINDOW_SIZE=6
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BACKOFF=exponential
RETRY_BASE_DELAY_MS=500
RETRY_MAX_DELAY_MS=10000
GAP_THRESHOLD=0.3

# Checkpoint
CHECKPOINT_BACKEND=in_memory
```

### 2.2 `.env.dev` (local development)

```bash
# Relaxed: faster iteration
LOG_LEVEL=debug
LLM_MODEL=gpt-4o-mini          # cheaper model for dev
LLM_MODEL_ESCALATION_ENABLED=false  # no escalation in dev — fail fast
MAX_TRANSFORM_ATTEMPTS=1       # fail fast
RETRY_BASE_DELAY_MS=100
CHECKPOINT_BACKEND=in_memory
GAP_THRESHOLD=0.5              # relaxed (50% OK in dev)

# Tools
ALLOW_DANGEROUS_OPS=true       # skip dangerous_operation approval in dev
MOCK_EXTERNAL_APIS=true        # mock premium/claims APIs
```

### 2.3 `.env.e2e` (CI / eval)

```bash
# Strict: match prod behavior for accurate evals
LOG_LEVEL=info
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0              # deterministic evals
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BASE_DELAY_MS=500
GAP_THRESHOLD=0.3              # same as prod

# Eval-specific
EVAL_MODE=true
EVAL_DATASET=home-insurance-eval
LANGSMITH_TRACING=true         # trace eval runs
ALLOW_DANGEROUS_OPS=false      # same strictness as prod
MOCK_EXTERNAL_APIS=true        # mock claims APIs, but test the real logic
```

### 2.4 `.env.prod` (production)

```bash
# Strict: full guardrails
LOG_LEVEL=warn
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0
MAX_TRANSFORM_ATTEMPTS=2
RETRY_BACKOFF=exponential
RETRY_BASE_DELAY_MS=500
RETRY_MAX_DELAY_MS=10000
GAP_THRESHOLD=0.3

# Production infrastructure
CHECKPOINT_BACKEND=postgresql
CHECKPOINT_DSN=${POSTGRES_DSN}
LANGSMITH_TRACING=true
ALLOW_DANGEROUS_OPS=false         # must pass human approval gate
MOCK_EXTERNAL_APIS=false          # all real APIs

# Model escalation (prod default: small → medium → large)
LLM_MODEL_ESCALATION_ENABLED=true
LLM_MODEL_TIERS=openai:gpt-4o-mini→gpt-4o→gpt-4.1
LLM_FAILURES_BEFORE_ESCALATION=2

# Security
PII_SCRUBBING=enabled
AUDIT_LOG_RETENTION_DAYS=365
SENSITIVE_FIELD_MASK=partial_mask
```

## 3. Per-Environment Threshold Comparison

> **Note:** LLM +1 extra retry is universal — it applies in all environments regardless of the base retry budget. Short/Standard/Full refer to the base retry budget (`max_attempts`) only; LLM nodes always get +1 on top.

| Config | dev | e2e | prod |
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
| `max_attempts` | 1 | 2 | 2 |
| `LLM_MODEL_ESCALATION_ENABLED` | false | true | true |
| `LLM_FAILURES_BEFORE_ESCALATION` | - | 2 | 2 |

## 4. `framework.yaml` Environment-Specific Sections

```yaml
# framework.yaml
environments:
  dev:
    llm:
      model: "${LLM_MODEL}"
      temperature: 0
      model_escalation:
        enabled: false              # fail fast, no model switching
    rule_engine:
      default: business_rules    # simpler engine for dev
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
      model_escalation:
        enabled: true
        failures_before_escalation: 2
        tiers:
          - provider: openai
            model: gpt-4o-mini
          - provider: openai
            model: gpt-4o
    rule_engine:
      default: durable_rules     # match prod
    retry:
      max_attempts: 2
    tools:
      mock_external: true        # mock APIs but real logic
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
      model_escalation:
        enabled: true
        failures_before_escalation: 2
        trigger_on:
          - provider_error
          - schema_violation
        tiers:
          - provider: openai
            model: gpt-4o-mini
            temperature: 0
            max_tokens: 4096
          - provider: openai
            model: gpt-4o
            temperature: 0
            max_tokens: 4096
          - provider: openai
            model: gpt-4.1
            temperature: 0
            max_tokens: 16384
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

## 5. Environment-Aware Engine Bootstrap

```yaml
# framework.yaml — environment-aware config loading
# The framework selects the matching environment section at startup.
# Set via: ENV=dev   or   ENV=e2e   or   ENV=prod

framework:
  version: "0.2.0"
  env: "${ENV:-dev}"   # resolved at bootstrap, defaults to dev

  config_loading:
    strategy: layered               # Option A: env file hierarchy
    sources:
      - type: file
        path: ".env"                # base defaults (committed)
        required: true
      - type: file
        path: ".env.local"          # local overrides (gitignored)
        required: false
      - type: file
        path: ".env.${ENV}"         # environment-specific overrides
        required: false
    merge: later_overrides_earlier

# Option B: Cloud Secret Manager (alternative to env-file approach)
#   strategy: cloud_secret_manager
#   sources:
#     - type: aws_secrets_manager
#       region: "${AWS_REGION}"
#       secret_id: "deterministic-workflow/${ENV}"
#     - type: hashicorp_vault
#       address: "${VAULT_ADDR}"
#       mount_path: "secret/deterministic-workflow/${ENV}"
#       auth_method: kubernetes  # or token, approle, aws
#   merge: cloud_overrides_file   # cloud secrets override .env defaults

  domain_models:
    - "domain-models/home-insurance.yaml"

  workflows:
    - "workflows/home_insurance_quote.yaml"

# At bootstrap the framework:
# 1. Reads framework.yaml → resolves ${ENV} → selects environments.{env} section
# 2. Loads and merges env files in order (.env → .env.local → .env.{ENV})
# 3. Validates required config per environment rules
# 4. Initializes engine with merged config

environments:
  # See Section 4 for per-environment overrides
  dev: { ... }
  e2e: { ... }
  prod: { ... }
```

---

## 6. Implementation Options

### 6.1 Option A: Env File Hierarchy (Recommended)

The framework loads `.env` → `.env.local` → `.env.{ENV}` from the filesystem. Later files override earlier ones. This is the default strategy and requires no external infrastructure.

| Aspect | Detail |
|--------|--------|
| Strengths | Zero dependencies; easy local development; GitOps-friendly (base `.env` committed, secrets in `.env.local` gitignored); simple to reason about |
| Weaknesses | Secret rotation requires redeploy or file watcher; no centralized audit of config changes; multi-instance drift risk if file sync lags |
| Best for | Single-region deployments; teams without existing secret management infrastructure; fast local iteration |

### 6.2 Option B: External Config Server (Consul / Vault)

Config is stored in an external secret/config server. The framework fetches or subscribes to config at bootstrap, with optional hot-reload via long-poll or watch.

```yaml
# framework.yaml — external config server strategy
config_loading:
  strategy: cloud_secret_manager
  sources:
    - type: hashicorp_vault
      address: "${VAULT_ADDR}"
      mount_path: "secret/deterministic-workflow/${ENV}"
      auth_method: kubernetes
    - type: aws_secrets_manager
      region: "${AWS_REGION}"
      secret_id: "deterministic-workflow/${ENV}"
  merge: cloud_overrides_file
  hot_reload:
    enabled: true
    poll_interval_seconds: 60
```

| Aspect | Detail |
|--------|--------|
| Strengths | Centralized secret rotation; dynamic config update without redeploy; built-in audit log for config access; no file drift across instances |
| Weaknesses | External dependency (Vault/Consul cluster); added latency at bootstrap; operational complexity for dev environments; harder to version-control config changes |
| Best for | Multi-region production; regulated industries requiring secret rotation audit; teams already running HashiCorp or AWS infrastructure |

### 6.3 Comparison Matrix

| Dimension | Option A (Env File Hierarchy) | Option B (External Config Server) |
|-----------|------------------------------|----------------------------------|
| Setup complexity | Low — files only | High — run config server cluster |
| Secret rotation | Manual (re-deploy or file watcher) | Automated (server-native rotation) |
| Config audit trail | Git history only | Config server access logs |
| Hot-reload | Not supported (restart required) | Supported (poll or watch) |
| Multi-instance drift | Possible (file sync lag) | None (single source of truth) |
| Dev experience | Excellent (local files) | Requires local Vault/Consul or mock |
| Compliance | Basic (Git + file permissions) | Strong (access logs, rotation policies) |
| Infrastructure cost | None | Config server cluster + maintenance |

---

## 7. Open Questions

1. **Secrets rotation strategy**: How should secrets (API keys, DB credentials) be rotated across environments? Should the framework support automatic rotation via cloud provider secret stores (AWS Secrets Manager, GCP Secret Manager), or is manual rotation sufficient for v0?

2. **Config hot-reload without restart**: Should the framework support runtime config changes (e.g., LLM model swap, log level change) without process restart? If yes, should this use file watchers, a config server polling mechanism, or a push-based event system?

3. **Multi-region env config sync**: For globally deployed instances, how should environment config stay synchronized across regions? Options: GitOps-based (config as code, synced via CI/CD), centralized config store with regional caching, or per-region independent config with drift detection.

4. **Env-specific LLM provider routing**: Should the framework support routing LLM calls to different providers per environment (e.g., dev→OpenAI, e2e→OpenAI, prod→Azure OpenAI) for compliance reasons? If yes, how should fallback chains work across providers?

5. **Config validation at startup**: Should the framework validate config completeness at bootstrap (fail-fast on missing required keys) or use graceful defaults? What validation rules apply per environment (e.g., prod MUST have `CHECKPOINT_DSN`, dev may omit it)?

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — Section 4.1, framework principles
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — LangSmith, LangGraph CLI
- [Routing & Execution](./2026-06-17-routing-execution-layer-design.md) — retry budgets, permission model
- [Response Generation](./2026-06-17-response-generation-layer-design.md) — gap threshold, PII scrubbing
