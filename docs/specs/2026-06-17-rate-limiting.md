# Rate Limiting

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Rate limiting strategy across three dimensions (user, tenant, tool), limit tiers, YAML configuration, 429 response format, and implement-interview integration.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial rate limiting spec: three-dimensional limits, tiers, YAML config, 429 response, interview questions |

---

## 1. Role

Rate limiting protects the framework from abuse and overuse. Every API endpoint, tool invocation, and LLM call must be governed by configurable limits. This is a spec-level concern — the `implement-interview` skill will ask users about their specific limits during adoption.

```
Incoming Request
    │
    ▼
┌─────────────────────────────┐
│       RATE LIMITER           │
│                               │
│  [User Limit Check]          │  ← per-user: max requests / window
│  [Tenant Limit Check]        │  ← per-tenant: aggregate limit for org
│  [Tool Limit Check]          │  ← per-tool: each tool has its own budget
│                               │
│  All checks pass?             │
│    ├── Yes → proceed to workflow
│    └── No  → 429 + Retry-After
└─────────────────────────────┘
```

### 1.1 What Rate Limiting Does NOT Cover

- **LLM token limits** → LLM Gateway spec (provider-level rate limits)
- **Authentication / authorization** → Auth Token Verification spec
- **Node-level retry budgets** → Routing & Execution spec §6
- **Concurrency limits (max parallel workflows)** → Framework engine config
- **Resource quotas (CPU, memory)** → Deployment / infrastructure config

---

## 2. Three Dimensions of Rate Limiting

### 2.1 Dimension Overview

| Dimension | Key | Scope | Purpose |
|-----------|-----|-------|---------|
| **Per-User** | `user_id` | Individual authenticated user | Prevent single-user abuse; enforce fair-use |
| **Per-Tenant** | `tenant_id` | Organization / team aggregate | Enforce tier limits; prevent noisy-neighbor |
| **Per-Tool** | `tool_name` | Individual tool (API, MCP, LLM) | Protect expensive/slow resources; cost control |

All three dimensions are evaluated on every request. If ANY dimension is exceeded, the request is rejected with 429.

### 2.2 Per-User Limits

```yaml
# framework.yaml
rate_limiting:
  dimensions:
    user:
      window: sliding              # fixed | sliding | token_bucket
      default:
        requests: 60               # 60 requests per minute (typical chat interaction)
        window_sec: 60
      burst_multiplier: 2          # allow burst up to 2x the limit
```

Per-user limits ensure a single user cannot monopolize resources. The default (60 req/min) is generous for chat interactions — a typical conversation has 10-30 turns.

### 2.3 Per-Tenant Limits

```yaml
rate_limiting:
  dimensions:
    tenant:
      window: sliding
      tiers:
        default:
          requests: 600            # 600 req/min across all users in the tenant
          window_sec: 60
        premium:
          requests: 6000
          window_sec: 60
        enterprise:
          requests: 60000
          window_sec: 60
      # Tenant limits are enforced in addition to per-user limits.
      # A single heavy user within a tenant won't block other users.
```

Per-tenant limits enforce the organization's purchased tier. Even if individual users are within their per-user limits, the aggregate tenant limit caps total throughput.

### 2.4 Per-Tool Limits

```yaml
rate_limiting:
  dimensions:
    tool:
      window: token_bucket          # token_bucket preferred for tools (allows bursts)
      default:
        requests: 100
        window_sec: 60
      tools:
        llm_call:                   # LLM is the most expensive resource
          requests: 30
          window_sec: 60
          window: token_bucket
          burst: 5                  # allow 5 concurrent LLM calls before rate limiting
        claims_gateway_api:        # Dangerous operations get tighter limits
          requests: 10
          window_sec: 60
        vector_search_mcp:          # Search is cheap, higher limit
          requests: 300
          window_sec: 60
        calculate_premium_api:      # Business computation, moderate limit
          requests: 100
          window_sec: 60
```

Per-tool limits protect expensive or rate-limited downstream resources. LLM calls are the most expensive (both cost and latency), so they get the tightest limit. Claims operations get tight limits for security and cost reasons.

### 2.5 Combined Enforcement

```
Request: user_id=alice, tenant_id=acme_corp, tool=llm_call

Check 1: user_id=alice
  current: 25/60 → PASS

Check 2: tenant_id=acme_corp (default tier)
  current: 580/600 → PASS

Check 3: tool=llm_call
  current: 28/30 → PASS

All pass → request proceeds

---

Request: user_id=bob, tenant_id=startup_inc, tool=claims_gateway_api

Check 1: user_id=bob
  current: 10/60 → PASS

Check 2: tenant_id=startup_inc (default tier)
  current: 590/600 → PASS

Check 3: tool=claims_gateway_api
  current: 10/10 → FAIL (limit reached)

→ 429 Too Many Requests
```

---

## 3. Limit Tiers

### 3.1 Tier Definitions

```yaml
# framework.yaml
rate_limiting:
  tiers:
    default:
      user:
        requests: 60
        window_sec: 60
      tenant:
        requests: 600
        window_sec: 60
      llm_calls_per_min: 30
      max_concurrent_workflows: 10
      tools:
        claims_gateway_api: { requests: 5, window_sec: 60 }
        vector_search_mcp: { requests: 100, window_sec: 60 }

    premium:
      user:
        requests: 120
        window_sec: 60
      tenant:
        requests: 6000
        window_sec: 60
      llm_calls_per_min: 100
      max_concurrent_workflows: 50
      tools:
        claims_gateway_api: { requests: 30, window_sec: 60 }
        vector_search_mcp: { requests: 500, window_sec: 60 }

    enterprise:
      user:
        requests: 300
        window_sec: 60
      tenant:
        requests: 60000
        window_sec: 60
      llm_calls_per_min: 500
      max_concurrent_workflows: 200
      tools:
        claims_gateway_api: { requests: 100, window_sec: 60 }
        vector_search_mcp: { requests: 2000, window_sec: 60 }

      # Enterprise can also define custom limits
      custom_limits_enabled: true
```

### 3.2 Tier Assignment

Tier is determined from `UserContext.tenant_id` (Auth Token Verification spec §2.3), mapped via configuration:

```yaml
# framework.yaml
rate_limiting:
  tenant_tier_mapping:
    source: config                     # config | database | external_api
    mappings:
      - tenant_id: acme_corp
        tier: enterprise
      - tenant_id: startup_inc
        tier: default
      - tenant_id: midmarket_co
        tier: premium
    default_tier: default              # tenants not in mapping get default tier
```

### 3.3 Tier Comparison

| Capability | Default | Premium | Enterprise |
|-----------|---------|---------|------------|
| User req/min | 60 | 120 | 300 |
| Tenant req/min | 600 | 6,000 | 60,000 |
| LLM calls/min | 30 | 100 | 500 |
| Concurrent workflows | 10 | 50 | 200 |
| Claims operations/min | 5 | 30 | 100 |
| Custom limits | ❌ | ❌ | ✅ |

---

## 4. Rate Limiting Algorithms

### 4.1 Algorithm Selection

```yaml
# framework.yaml
rate_limiting:
  algorithm:
    default: sliding_window          # best balance of accuracy and memory
    options:
      fixed_window:
        description: "Reset counter at window boundaries (e.g., every 60s)"
        pros: ["Simple", "Low memory"]
        cons: ["Burst at boundary — user can do 2x limit across window edges"]
      sliding_window:
        description: "Track requests in the last N seconds with sub-window granularity"
        pros: ["Smooth", "No boundary burst", "Good accuracy"]
        cons: ["Higher memory (stores timestamps)"]
        config:
          sub_window_sec: 10          # 6 sub-windows in a 60s window
      token_bucket:
        description: "Bucket fills at rate R, each request consumes 1 token. Allows bursts."
        pros: ["Natural burst handling", "Good for tools", "Low memory"]
        cons: ["Burst size tuning needed"]
        config:
          burst_size: 10              # max tokens in bucket
          refill_rate: 1              # tokens per second
```

### 4.2 Per-Dimension Algorithm Override

```yaml
rate_limiting:
  dimensions:
    user:
      algorithm: sliding_window       # smooth, no boundary bursts for users
    tenant:
      algorithm: sliding_window       # same for tenant fairness
    tool:
      algorithm: token_bucket         # tools benefit from burst capacity
```

---

## 5. 429 Response Format

### 5.1 HTTP Response

When any rate limit is exceeded, the framework returns:

```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 30
X-RateLimit-Limit-User: 60
X-RateLimit-Remaining-User: 0
X-RateLimit-Limit-Tenant: 600
X-RateLimit-Remaining-Tenant: 580
X-RateLimit-Limit-Tool: 10
X-RateLimit-Remaining-Tool: 0

{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please retry after 30 seconds.",
  "details": {
    "exceeded_dimension": "tool",
    "exceeded_limit": "claims_gateway_api",
    "user_id": "bob",
    "tenant_id": "startup_inc",
    "current_usage": {
      "user": { "used": 10, "limit": 60, "remaining": 50 },
      "tenant": { "used": 590, "limit": 600, "remaining": 10 },
      "tool": { "used": 10, "limit": 10, "remaining": 0 }
    },
    "retry_after_sec": 30
  }
}
```

### 5.2 Response Schema

```yaml
# 429 error response schema
RateLimitResponse:
  error: string                          # always "rate_limit_exceeded"
  message: string                        # human-readable message
  details:
    exceeded_dimension: user | tenant | tool
    exceeded_limit: string               # which specific limit was hit
    user_id: string
    tenant_id: string
    current_usage:
      user:     { used: integer, limit: integer, remaining: integer }
      tenant:   { used: integer, limit: integer, remaining: integer }
      tool:     { used: integer, limit: integer, remaining: integer }
    retry_after_sec: integer
```

### 5.3 Retry-After Header

The `Retry-After` value is calculated as the maximum wait across all exceeding dimensions:

```
Retry-After = max(
  user_window_sec - (now - user_window_start),     // if user limit exceeded
  tenant_window_sec - (now - tenant_window_start), // if tenant limit exceeded
  tool_window_sec - (now - tool_window_start)      // if tool limit exceeded
)
```

### 5.4 Client Guidance

The 429 response includes actionable information for clients:

```yaml
# In the 429 response body, additional guidance
rate_limit_response:
  client_action:
    recommended: "Implement exponential backoff starting at Retry-After seconds"
    backoff_strategy:
      initial_delay: "{{retry_after_sec}}"
      multiplier: 2
      max_delay: 300
      jitter: true
```

---

## 6. Rate Limit Headers on All Responses

Even on successful responses, the framework emits rate limit headers so clients can self-throttle:

```
# Included on every response (200, 400, etc.)
X-RateLimit-Limit-User: 60
X-RateLimit-Remaining-User: 35
X-RateLimit-Reset-User: 1623456789

X-RateLimit-Limit-Tenant: 600
X-RateLimit-Remaining-Tenant: 20
X-RateLimit-Reset-Tenant: 1623456789

X-RateLimit-Limit-Tool: 30
X-RateLimit-Remaining-Tool: 2
X-RateLimit-Reset-Tool: 1623456789
```

### 6.1 Header Schema

```yaml
# Standard rate limit headers on all responses
headers:
  X-RateLimit-Limit-{dimension}: integer        # max requests allowed in window
  X-RateLimit-Remaining-{dimension}: integer    # requests remaining in current window
  X-RateLimit-Reset-{dimension}: integer        # Unix timestamp when window resets
```

---

## 7. Storage Backend

### 7.1 Backend Options

```yaml
# framework.yaml
rate_limiting:
  storage:
    backend: redis                   # redis | memory | postgresql
    redis:
      host: "${REDIS_HOST}"
      port: 6379
      db: 1
      key_prefix: "ratelimit:"
      # Redis is strongly recommended for production.
      # Memory backend is for development only (lost on restart).
    fallback: memory                 # if Redis is unreachable, fall back to memory limits
```

| Backend | Use Case | Trade-off |
|---------|----------|-----------|
| **Redis** | Production | Accurate across instances; persistent; supports Lua scripting for atomic checks |
| **Memory** | Development / single-instance | Zero dependencies; lost on restart |
| **PostgreSQL** | No Redis available | Accurate; higher latency than Redis |

### 7.2 Redis Key Structure

```
# Redis key pattern for each dimension
ratelimit:user:{user_id}:{window_start_ts}       → counter
ratelimit:tenant:{tenant_id}:{window_start_ts}   → counter
ratelimit:tool:{tool_name}:{window_start_ts}     → counter
```

---

## 8. Implement-Interview Integration

### 8.1 Role

The `implement-interview` skill is a guided interview that walks adopters through configuring the framework for their specific industry and use case. Rate limiting is one of the configuration domains the skill covers.

### 8.2 Interview Questions

When the `implement-interview` skill runs, it asks the following questions about rate limiting:

| # | Question | Why |
|---|----------|-----|
| 1 | **What is your expected monthly active user count?** | Determines baseline tenant limits |
| 2 | **Do you offer tiered pricing (free, pro, enterprise)?** | Maps to limit tiers |
| 3 | **What is the most expensive operation in your system?** | Identifies which tool needs the tightest limit |
| 4 | **Do you call third-party APIs that have their own rate limits?** | Ensures our limits are stricter than downstream limits |
| 5 | **What is your LLM provider's rate limit (requests per minute)?** | Sets the `llm_call` tool limit |
| 6 | **Do you need per-endpoint limits, or is per-user + per-tenant sufficient?** | Determines if per-tool dimension is needed |
| 7 | **What is your SLA for response time?** | Affects window size and burst configuration |
| 8 | **Do you operate in a regulated industry with explicit throttling requirements?** | May require stricter limits and audit trail |

### 8.3 Config Generation from Interview Answers

```yaml
# Example: interview output → generated config
interview_answers:
  mau: 10000
  pricing_tiers: [free, pro, enterprise]
  most_expensive_operation: "LLM call to GPT-4o"
  third_party_limits: "Stripe: 100 req/s; GPT-4o: 500 req/min"
  llm_provider_limit: 500           # requests per minute
  need_per_endpoint: true
  sla_ms: 2000
  regulated: true

# Generated config
rate_limiting:
  tiers:
    free:
      user: { requests: 30, window_sec: 60 }       # generous enough for testing
      tenant: { requests: 300, window_sec: 60 }     # small teams
    pro:
      user: { requests: 60, window_sec: 60 }
      tenant: { requests: 6000, window_sec: 60 }    # mid-size org
    enterprise:
      user: { requests: 300, window_sec: 60 }
      tenant: { requests: 60000, window_sec: 60 }   # large org
  dimensions:
    tool:
      tools:
        llm_call: { requests: 400, window_sec: 60 } # 80% of provider limit
        stripe_api: { requests: 80, window_sec: 1 } # 80% of Stripe limit
```

---

## 9. Bypass and Override

### 9.1 Admin Bypass

Certain roles can bypass rate limits for operational reasons:

```yaml
# framework.yaml
rate_limiting:
  bypass:
    enabled: true
    roles: [admin, system]                  # these roles are exempt from rate limiting
    scopes: ["rate_limit:bypass"]           # OAuth scope alternative
    audit_bypass: true                      # log every bypass for compliance
```

### 9.2 Per-Tenant Override

Enterprise tenants can negotiate custom limits:

```yaml
rate_limiting:
  tenant_overrides:
    - tenant_id: large_enterprise_corp
      tier: enterprise
      overrides:
        user: { requests: 500, window_sec: 60 }
        tenant: { requests: 100000, window_sec: 60 }
        tools:
          llm_call: { requests: 800, window_sec: 60 }
```

### 9.3 Emergency Unlimit

For operational emergencies (incident response, data migration), a global override:

```yaml
rate_limiting:
  emergency_unlimit:
    enabled: false                         # set to true only during incidents
    ttl_sec: 3600                          # auto-disable after 1 hour
    audit: true                            # every request during unlimit is audited
```

---

## 10. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should rate limits be hard-enforced (reject) or soft-enforced (queue + delayed processing) for premium/enterprise tiers? | User experience vs resource protection |
| 2 | Should the framework support dynamic rate limiting (adjust limits based on current system load)? | Adaptive resource management |
| 3 | How should rate limits propagate through A2A chains (Agent A → Agent B → Agent C — which agent's limits apply)? | Multi-agent fairness |
| 4 | Should rate limit counters be shared across instances (Redis cluster) or per-instance (memory) + coordinated? | Horizontal scaling |
| 5 | Should the 429 response include a `Retry-After` per-dimension, or a single aggregate value? | Client retry logic simplicity |
| 6 | For LLM calls: should the rate limit be measured in requests or tokens? Token-based limits are fairer but harder to predict. | LLM cost control |
| 7 | Should the framework expose a `/rate-limits` endpoint so clients can query their current usage without making a request? | Client self-awareness |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — framework architecture
- [Auth Token Verification](./2026-06-17-auth-token-verification.md) — UserContext schema (§2.3), tenant_id
- [LLM Gateway](./2026-06-17-llm-gateway.md) — LLM call contract; model escalation impacts per-provider rate limits
- [Tool Ecosystem](./2026-06-17-tool-ecosystem.md) — tool registration and classification
- [Routing & Execution Layer](./2026-06-17-routing-execution-layer-design.md) — retry budgets (§6), permission model (§7)
- [A2A Protocol](./2026-06-17-a2a-protocol.md) — multi-agent rate limit propagation (future concern)
- [Response Generation](./2026-06-17-response-generation-layer-design.md) — 422 error format (comparable pattern)
