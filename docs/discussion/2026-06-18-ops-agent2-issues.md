# Agent 2 — MiniMax Cross-Model Reviewer: OPS & REMAINING Specs Review

> **Date:** 2026-06-18
> **Reviewer:** Agent 2 (Cross-Model Reviewer)
> **Specs:** environment-config, auth-token-verification, conversation-lifecycle, observability-monitoring, cicd-jenkins-pipeline, rate-limiting, widget-templates, rag-interface, agent-types
> **Classification tags:** correctness | completeness | clarity | consistency | trade_off_gap | missing_edge_case

---

## Correctness Issues

### C-1: Environment config has `PII_SCRUBBING=optional` in dev but prod has `enabled` (`environment-config` §2.2)

**Tag:** `correctness`

`.env.dev` does not mention PII_SCRUBBING at all. The comparison table (§3) shows dev = `optional`. `.env` base has no PII_SCRUBBING line. `.env.prod` sets `PII_SCRUBBING=enabled`.

But `framework.yaml` environments.dev also omits any `pii` block — only prod has `pii.scrubbing: enabled`. This means:
- The env var `PII_SCRUBBING` serves only prod and e2e
- Dev has no PII scrubbing config at either level
- A developer working with production data in dev (common during debugging) would leak PII to LangSmith traces (since `LANGSMITH_TRACING` is off in dev, but could be turned on)

**Fix:** Add `PII_SCRUBBING=optional` to `.env.dev` explicitly, or add a `pii:` block with `scrubbing: optional` to `framework.yaml` environments.dev.

---

### C-2: `conversation-lifecycle` §2.3 defines `initial: created` but nothing creates a conversation in `created` state

**Tag:** `correctness`

The lifecycle state machine starts at `created`, but no spec defines HOW a conversation is created. The transition `created → active` fires on `first_message`. But:
- Who calls `create_conversation(user_id, workflow_id)`?
- Is it the MCP server? The REST API? The auth middleware?
- What happens if the user sends a message without a prior `create_conversation` — auto-create or 404?

The auth spec (§5) says "workflow interaction must carry a verified user identity" and injects UserContext, but doesn't define conversation creation. The lifecycle spec assumes conversations exist. This is a bootstrapping gap.

---

### C-3: `agentState` passed to ReadOnlyAgent is `dict[str, Any]` but described as "full AgentState copy" elsewhere (`agent-types` §2.1 vs `conversation-lifecycle` §4.2)

**Tag:** `correctness`

The agent-types spec defines `agent_state: dict[str, Any]` in the `ReadOnlyAgent.query()` signature. But the conversation-lifecycle spec §4.2 defines checkpoint content as `agent_state_snapshot: object # full AgentState copy`, implying a structured object, not a generic dict.

If `AgentState` is a typed object (Pydantic model or dataclass), passing `dict[str, Any]` loses type safety. If it's a dict, then what are its keys? The agent-types spec never enumerates them, yet the dispatch code references `agent_state` for context.

**Fix:** Either define `AgentState` as a typed schema (and use it in all interfaces) or document the dict keys contract. The RAG interface spec references `agentState` but also avoids defining the schema.

---

### C-4: OIDC provider URLs in auth spec are syntactically incorrect (`auth-token-verification` §3 Option A table)

**Tag:** `correctness`

The table shows:
```
Auth0: Public key from https://<domain>/.well-known/jwks.json
Okta: Public key from https://<domain>/oauth2/default/v1/keys
```

The correct paths are:
- Auth0: `https://<domain>/.well-known/jwks.json` — correct
- Okta: `https://<domain>/oauth2/default/v1/keys` — correct for Okta org authorization servers, but for custom authorization servers it's `https://<domain>/oauth2/<authorizationServerId>/v1/keys`

The `framework.yaml` example shows `issuer: "https://my-app.auth0.com/"` which is missing the trailing path — Auth0 issuers are typically `https://<domain>/` (with trailing slash). These are minor but would cause real integration failures.

---

## Completeness Gaps

### CP-1: No conversation creation API/contract defined (`conversation-lifecycle`)

**Tag:** `completeness`

The lifecycle spec defines what states exist and how they transition, but never defines:
1. The API contract for `create_conversation` — What parameters? What returns?
2. Whether `conversation_id` is server-assigned (UUID) or client-assigned
3. Whether a conversation must be tied to a workflow at creation time, or can be workflow-agnostic
4. How `max_active_per_user: 10` (§8.3) is enforced — is there a `POST /conversations` endpoint that checks this? Or a framework hook?

Without the creation contract, every other spec that references conversations is building on an undefined foundation.

---

### CP-2: Missing retry-budget exhaustion behavior in observability (`observability-monitoring` §4)

**Tag:** `completeness`

The alert rules cover error rate, latency, 422 rate, and schema violations. Missing:
1. **Retry budget exhaustion alert** — When `llm_retry_total` spikes, it indicates the LLM is persistently failing. A retry storm is an early warning of LLM provider issues BEFORE the error rate spikes (because retries mask errors). An alert on `rate(llm_retry_total[5m]) > X` would detect this.
2. **Model escalation rate alert** — The environment config spec defines model escalation (gpt-4o-mini → gpt-4o → gpt-4.1). An observability metric for escalation frequency would tell operators: "Your primary model is unhealthy enough that we're failing over frequently." No metric or alert is defined for this.

---

### CP-3: No auth token refresh during long-running conversations (`auth-token-verification` §8 Q3)

**Tag:** `completeness` | `missing_edge_case`

Open Question #3 asks "Should the framework support token refresh (sliding expiration) or only initial verification?"

The spec never answers this, but the conversation-lifecycle spec allows conversations to span 30+ minutes (soft timeout at 30 min, hard at 24 hours). A typical OAuth access token expires in 15-60 minutes. Without refresh support:
- A user 20 minutes into a home insurance quote would get 401 mid-conversation
- The conversation checkpoints include `agentState.user` — on resume, the stale user context would be restored
- The "re-verify on sensitive transitions" rule (§9.1) would fail if the token expired

This is a critical edge case. The spec must either mandate refresh support or reduce conversation timeout below the minimum token TTL.

---

### CP-4: Rate limiting has no circuit breaker for tool failures (`rate-limiting` §2.4)

**Tag:** `completeness` | `missing_edge_case`

Per-tool limits protect against overuse, but don't protect against **downstream failures**. If `claims_gateway_api` starts returning 500 errors:
- The rate limiter still allows 10 req/min for the default tier
- Every one of those 10 requests fails
- Users get 10 failures per minute instead of being told "service temporarily unavailable"

A circuit breaker pattern (open → half-open → closed) should complement rate limiting. When a tool's error rate exceeds a threshold, the rate limit drops to 0 (circuit open), then gradually restores. The CI/CD spec mentions circuit breakers for backend APIs (§5.2) but rate limiting doesn't integrate with them.

---

### CP-5: Widget streaming protocol is under-specified (`widget-templates` §2.7)

**Tag:** `completeness`

The streaming spec defines event types (`message_chunk`, `component_update`, `status_update`, `error`) but doesn't specify:
1. **The wire format** — Are events JSON? Server-Sent Events with `event:` and `data:` fields? NDJSON?
2. **Event ordering guarantees** — Can `component_update` arrive before the preceding `message_chunk` finishes? If the backend sends interleaved text and component updates, how does the frontend reconcile ordering?
3. **Reconnection** — SSE connections drop. What's the last-event-ID mechanism? Does the client request from a checkpoint offset?
4. **Error event structure** — What fields does an `error` SSE event contain? An error code? A retriable flag?

Without these specifications, every implementation will invent its own protocol, defeating the "pre-built chatbot UI" goal.

---

### CP-6: RAG interface has no `aquery` (async) method (`rag-interface` §2.5)

**Tag:** `completeness`

All RAG interface methods are synchronous: `Retriever.retrieve()`, `RAGPipeline.query()`, `TextEmbedder.embed()`. In an async framework (Python asyncio, which LangGraph uses extensively), these become blocking calls that stall the event loop during LLM calls and vector DB queries.

The spec should define async variants:
```python
async def aretrieve(self, query: str, top_k: int = 10, ...) -> list[RetrievedDocument]: ...
async def aquery(self, prompt: str, top_k: int = 5, ...) -> RAGResult: ...
```

Haystack, LlamaIndex, and LangChain all provide async methods. Omitting them from the Protocol makes async backends unusable without wrapping in `run_in_executor()`.

---

## Clarity Issues

### CL-1: `framework.yaml` vs `.env.*` overlap creates confusion about authority (`environment-config`)

**Tag:** `clarity`

The spec describes two config loading paths:
1. `.env` → `.env.local` → `.env.{ENV}` (environment variable hierarchy)
2. `framework.yaml` environments.{env} sections (structured config)

Both define the SAME config values (LLM model, retry budgets, tool settings). The spec never states:

- **Which wins when they conflict?** The load order says "env files loaded first, then framework.yaml selects environment section." Does the YAML section override env vars? Or do env vars override YAML because `${LLM_MODEL}` references pull from env?
- **When should I edit which?** If I want to change the retry budget for dev, do I edit `.env.dev` or `framework.yaml` environments.dev?
- **What is the user story for gradual migration?** Teams starting with env files only who later want structured YAML — how do they migrate incrementally?

A clear "Single Source of Truth" hierarchy is needed.

---

### CL-2: "LLM_GUARDRAIL" concept referenced but never specified (`environment-config` §4 prod)

**Tag:** `clarity`

The `framework.yaml` environments.prod `model_escalation.trigger_on` lists:
```yaml
trigger_on:
  - provider_error
  - schema_violation
```

What is the difference between a "provider_error" and a "schema_violation" in terms of escalation behavior? Does a provider error skip directly to the next tier? Does a schema violation retry on the same tier first? The escalation strategy (retry same tier N times → escalate tier → retry → give up) is never documented.

---

### CL-3: "Goal Check 422" is used as both an HTTP status and a metric name (`observability-monitoring` §2.1)

**Tag:** `clarity`

The metric `goal_check_422_rate` implies HTTP 422 is the error signal for goal check failures. But the Response Generation spec and the Routing & Execution spec may use different error codes for goal check failures. 422 (Unprocessable Entity) is semantically correct for "we understood your request but can't complete it because the goal is unmet," but this semantic mapping is never justified or linked to the Response Generation spec's error format.

A reader unfamiliar with the full spec suite will wonder: "Why 422? Why not 409 (Conflict) or 400 (Bad Request)?"

---

### CL-4: `trace_id = user_id` tracing model uses ambiguous span hierarchy (`conversation-lifecycle` §3.3)

**Tag:** `clarity`

The trace config shows:
```yaml
span_hierarchy:
  root: "user:{user_id}"
  child: "conversation:{conversation_id}"
  grandchild: "turn:{turn_number}"
```

But this implies each turn is a CHILD of conversation. In the three-layer pipeline, a turn spawns Layer 1, Layer 2, and Layer 3 as sequential spans. The hierarchy should be:

```
conversation:{id}
  └── turn:{n}
        ├── layer_1:extract
        ├── layer_2:route
        └── layer_3:respond
```

The spec's "grandchild = turn" flattens the three-layer pipeline. The actual nesting should go deeper, especially because each layer may call LLM Gateway (its own span).

---

## Consistency Issues

### CN-1: Agent permission matrix vs. auth RBAC deferral (`agent-types` §4 vs `auth-token-verification` §5)

**Tag:** `consistency`

Already noted in the contrarian analysis (WR-2), but worth emphasizing as a pure consistency problem:

The auth spec says: "Role-Based Access Control is deferred to a future interface" and labels RBAC integration as "Deferred."

The agent-types spec says: ReadOnlyAgent cannot call APIs, EscalationAgent cannot write DB, State Machine cannot send to human. This IS role-based access control — it's just hardcoded by agent type instead of resolved by the RoleResolver.

If RBAC is truly deferred, the permission matrix in agent-types is premature. If the matrix is the intended RBAC model, the auth spec's "deferred" statement is incorrect. The two specs contradict each other.

---

### CN-2: `max_attempts` semantics differ between env config and retry specs (`environment-config` §3 vs `routing-execution`)

**Tag:** `consistency`

The env config table shows `max_attempts: dev=1, e2e=2, prod=2` with a note: "LLM +1 extra retry is universal."

But what counts as an "attempt"? In the Routing & Execution spec, retry budgets may apply per-node or per-layer. If Layer 2 has `max_attempts=2`, does that mean 2 attempts at the current node, or 2 attempts across all nodes in Layer 2?

The env config simplifies this to a single `max_attempts` number when the Routing & Execution spec may define per-node, per-phase, and per-layer retry budgets. The two specs need to agree on the retry hierarchy.

---

### CN-3: CI/CD triggers inconsistently named across pipeline schema (`cicd-jenkins-pipeline` §3)

**Tag:** `consistency`

The stage-level triggers use inconsistent naming:
- Stage `lint`: `trigger: push_or_pr`
- Stage `eval_mock`: `trigger: push_or_pr`
- Stage `eval_real`: `trigger: pull_request_only`
- Stage `build`: `trigger: merge_to_main`

But the stage overview table (§2.1) uses:
- Lint: `every_push`
- Eval (Mock): `every_push`
- Eval (Real): `PR only`
- Build: `Merge to main`

These are semantically equivalent but syntactically different. If `every_push` and `push_or_pr` are the same thing, use one term. If they differ (push to any branch vs. push or PR to main), define the difference.

---

### CN-4: Widget sandbox CSP conflicts with streaming requirements (`widget-templates` §6.2 vs §2.7)

**Tag:** `consistency`

The widget sandbox (§6.2) sets Content Security Policy:
```yaml
csp:
  script_src: "'self'"
```

This blocks inline scripts, event handlers (`onclick="..."`), and `eval()`. But the streaming spec (§2.7) requires the widget to:
- Process SSE events (requires `EventSource` API, which connects to the framework's `/api/chat/stream`)
- Re-render on `component_update` events (dynamic DOM manipulation)
- Handle `typewriter` text rendering (setInterval/setTimeout for progressive display)

The CSP `connect-src` directive is not specified — SSE connections to `/api/chat/stream` may be blocked by default CSP policies. Also, `'self'` for `script_src` means the widget's own `.tsx` file can load, but any dynamically injected script (common in streaming rendering) would be blocked. Add `connect-src` to the CSP config.

---

## Trade-off Gap

### TG-1: LangSmith vs LangFuse — "both" is not a valid trade-off decision (`observability-monitoring` §7.1 vs §7.2)

**Tag:** `trade_off_gap`

The spec lists LangSmith (Option A — used for traces) and LangFuse (Option B — alternative observability provider). But the framework config (§6.1) shows LangSmith always enabled:
```yaml
langsmith:
  enabled: true
  api_key: "${LANGSMITH_API_KEY}"
```

And the observability provider is separately configured:
```yaml
observability:
  provider: grafana_prometheus    # grafana_prometheus | langfuse | datadog | opentelemetry
```

This creates an implicit **dual-provider** architecture: LangSmith for LLM traces + Prometheus for metrics + Grafana for dashboards. The trade-off of running TWO trace systems (LangSmith traces + OTel traces if using Datadog/OTel) is never analyzed.

| Trade-off | LangSmith + Prometheus + Grafana | LangFuse only |
|-----------|----------------------------------|---------------|
| Cost | LangSmith free tier + OSS | LangFuse cloud or self-host |
| Operational burden | 3 systems to maintain | 1 system |
| Trace depth | LLM calls only | Full pipeline traces |
| Vendor lock-in | Medium (LangSmith) | Low (OSS self-host option) |

The spec should explicitly decide: is LangSmith the only tracing backend, or is the observability provider a wholesale replacement? The current text implies both coexist, which is architecturally expensive.

---

### TG-2: Multi-device strategy defaults to `independent_conversations` without analyzing cost (`conversation-lifecycle` §8.2)

**Tag:** `trade_off_gap`

```yaml
multi_device:
  strategy: independent_conversations
```

Each device gets its own conversation. A user with phone + tablet + desktop = 3 concurrent conversations. The trade-offs:

| Strategy | Pro | Con |
|----------|-----|-----|
| independent_conversations | No distributed locking; simple state management | 3x resource usage; user sees different state per device; "I started on my phone, where's my data on desktop?" |
| single_conversation | Consistent user experience; shared state | Requires distributed locking; message ordering; conflict resolution |

The default maximizes implementation simplicity at the cost of user experience. For a chatbot framework targeting fintech (insurance, banking), users expect to continue conversations across devices. The trade-off decision should acknowledge that `independent_conversations` is a v0 shortcut, not the desired UX.

---

### TG-3: Eval gate thresholds are global but applied per-workflow (`cicd-jenkins-pipeline` §3 eval_real)

**Tag:** `trade_off_gap`

```yaml
gates:
  - metric: "intent_accuracy"
    threshold: ">= 0.90"
  - metric: "goal_check_pass_rate"
    threshold: ">= 0.85"
  - metric: "schema_violation_rate"
    threshold: "<= 0.05"
```

A home_insurance_quote workflow with 95% intent accuracy passes the 90% gate easily. A complex claim_filing workflow with 88% intent accuracy fails. But the gate only tests "changed workflows" — so a 2-line change to claim_filing that doesn't affect intent accuracy still triggers the gate and fails.

The trade-off: per-workflow thresholds (flexible but more config to maintain) vs. global thresholds (simple but may block benign changes). The spec mentions this in Open Question #4 but doesn't resolve it. The current global threshold is a simplifying assumption that will cause false-positive pipeline failures.

---

## Missing Edge Cases

### EC-1: Conversation timeout during active LLM call (`conversation-lifecycle` §5)

**Tag:** `missing_edge_case`

The idle timeout fires after 30 minutes of no user message. But what if:
1. User sends message at T+0
2. Layer 1 processes (T+1s)
3. Layer 2 routes (T+2s)
4. Layer 3 calls LLM (T+3s)
5. LLM takes 25 seconds to respond (T+28s)
6. Framework sends response (T+29s)

Now suppose the LLM takes 31 seconds (network issues, large context, provider slowdown). The response arrives at T+31s — but the timeout timer was set to 30 min and T+31s > T+30min, so the conversation transitions to `timeout` just as the response is being composed.

The spec's timer reset (§5.3) only resets on `agent_message_delivered` — but the message hasn't been delivered yet because the LLM is still generating. This creates a race condition where a slow LLM causes a timeout mid-response.

**Fix:** Reset or extend the timeout timer when an LLM call is in flight. The timer should only count true idle time, not processing time.

---

### EC-2: Rate limiting during conversation resume (`rate-limiting` + `conversation-lifecycle` §6)

**Tag:** `missing_edge_case`

When a user resumes a conversation from `paused` or `timeout`:
1. The resume flow hydrates context (§6.1 step 3)
2. "Optionally re-run Context Hydration for stale external data" (§6.2)
3. Transition to active

Context hydration may trigger LLM calls (to re-summarize stale data) or tool calls (to refresh external data). These count against the user's rate limits. But the user didn't initiate these — the framework did on resume.
- If the user is at 59/60 RPM and resume triggers 2 LLM calls → 429 on resume
- The user sees "rate limited" without having sent a new message

**Fix:** Framework-initiated operations (resume hydration, timeout cleanup, heartbeat checks) should either bypass rate limits (admin/system role) or use a separate allowance.

---

### EC-3: Widget error surface when Claude generates invalid code (`widget-templates` §3.2)

**Tag:** `missing_edge_case`

Template B generates widget code from Claude. What if:
1. Claude generates a `premium_calculator.tsx` that imports a library not in the project's dependencies
2. The generated code has a React hook violation (hooks inside conditionals)
3. The widget renders successfully but has a runtime bug that corrupts `agentState`

The spec §6.2 defines a widget sandbox for security, but not for correctness:
- No build-time validation (TypeScript compilation, linting) before widget registration
- No runtime error boundary (what happens if a widget throws during render?)
- No rollback mechanism (if a generated widget causes repeated errors, how is it reverted?)

Open Question #3 asks about widget version management but the answer should be: generated widgets MUST pass the CI/CD pipeline (TypeScript compile + lint + snapshot tests) before registration.

---

### EC-4: OAuth provider rotation without downtime (`auth-token-verification` §3)

**Tag:** `missing_edge_case`

The auth config is environment-specific:
```yaml
auth:
  dev: { provider: api_key }
  e2e: { provider: auth0, issuer: "https://e2e-auth.example.com/" }
  prod: { provider: auth0, issuer: "https://auth.example.com/" }
```

What if a team migrates from Auth0 to Okta in production? The migration requires:
1. Both providers accept tokens during transition
2. A JWKS cache that handles two issuers simultaneously
3. A `provider_migration_mode: dual` config that validates tokens against both

The spec supports a single provider per environment. Multi-provider is deferred to Open Question #5 but no architectural accommodation is made. The JWKS caching, issuer validation, and audience checking are all single-provider designs.

---

### EC-5: RAG document deduplication across backends (`rag-interface` §2.2)

**Tag:** `missing_edge_case`

The `DocumentStore.write_documents()` has a `policy` parameter: `replace | skip | fail`. But deduplication is by document ID only. What if:
- Two different backend adapters produce documents with the same semantic content but different IDs?
- A document is updated (new version, same ID) and the `replace` policy overwrites the embedding but the old embedding is still in the vector index until a reindex?

The `replace` policy says "overwrite duplicates" but doesn't specify whether overwriting triggers re-embedding or vector index update. If the document store is Elasticsearch (where embeddings live in the index) vs. a separate vector DB (where embeddings are stored elsewhere), the behavior differs.

The interface should specify: `write_documents` with `policy=replace` MUST ensure the new document's embedding is queryable by the retriever immediately, not after a batch reindex.

---

### EC-6: `conversation-lifecycle` archived state has no legal hold mechanism (`conversation-lifecycle` §2.1)

**Tag:** `missing_edge_case`

```yaml
archived:
  terminal: true
  read_only: true
```

For fintech/regulated industries, archived conversations must occasionally be restored for legal discovery, audit investigations, or regulatory inquiries. The spec says archived is "read-only" and "terminal" — no transition out of it.

The Open Question #2 asks about legal hold but the spec never answers: how do you flag a conversation as "do not delete" while keeping the `archive_after_days` auto-cleanup? The archive retention policy (`completed: 90 days`, `abandoned: 30 days`) has no exception for legally held conversations.

---

## Summary

| Issue | Severity | Spec | Recommendation |
|-------|----------|------|----------------|
| C-1: PII_SCRUBBING missing in dev config | Medium | environment-config | Add explicit `PII_SCRUBBING=optional` to dev config |
| C-2: No conversation creation API defined | High | conversation-lifecycle | Define POST /conversations contract |
| C-3: AgentState type inconsistency | Medium | agent-types | Define typed AgentState schema |
| C-4: Incorrect OIDC URL paths | Low | auth | Verify and correct JWKS URI paths |
| CP-1: Missing creation API (see C-2) | High | conversation-lifecycle | As above |
| CP-2: Missing retry/escalation alerts | Medium | observability | Add retry budget exhaustion and model escalation alerts |
| CP-3: Token refresh for long conversations | High | auth | Mandate refresh support or reduce conversation TTL |
| CP-4: No circuit breaker for tool failures | Medium | rate-limiting | Add circuit breaker pattern for per-tool rate limits |
| CP-5: Widget SSE protocol under-specified | Medium | widget-templates | Specify wire format, ordering, reconnection, error structure |
| CP-6: No async RAG interface methods | Medium | rag-interface | Add async variants to all Protocol methods |
| CL-1: Config source authority unclear | High | environment-config | Declare single source of truth hierarchy |
| CL-2: Model escalation trigger semantics | Low | environment-config | Document escalation trigger behavior |
| CL-3: "Goal Check 422" lacks semantic justification | Low | observability | Link to Response Generation spec error format |
| CL-4: Span hierarchy too shallow | Low | conversation-lifecycle | Add Layer 1/2/3 spans under each turn |
| CN-1: RBAC deferral contradicts agent permissions | High | auth ←→ agent-types | Reconcile: implement RBAC or remove permission matrix |
| CN-2: max_attempts semantics between env/routing specs | Medium | environment-config ←→ routing | Define retry hierarchy explicitly |
| CN-3: CI/CD trigger names inconsistent | Low | cicd | Standardize trigger naming |
| CN-4: CSP blocks SSE connections | Medium | widget-templates | Add connect-src to CSP config |
| TG-1: Dual trace provider not justified | Medium | observability | Decide: LangSmith only, or provider replaces it |
| TG-2: independent_conversations UX cost | Medium | conversation-lifecycle | Acknowledge as v0 shortcut; note migration to single_conversation |
| TG-3: Global eval gates block benign changes | Medium | cicd | Add per-workflow gate overrides |
| EC-1: Timeout during LLM call | High | conversation-lifecycle | Extend timeout timer during in-flight LLM calls |
| EC-2: Rate limiting on resume hydration | Medium | rate-limiting + conversation-lifecycle | Bypass or separate allowance for framework operations |
| EC-3: Invalid Claude-generated widgets | Medium | widget-templates | Add CI/CD validation gate for generated widgets |
| EC-4: OAuth provider migration | Medium | auth | Add dual-provider migration mode |
| EC-5: RAG document deduplication semantics | Medium | rag-interface | Specify embedding/index update behavior on replace |
| EC-6: Legal hold for archived conversations | Medium | conversation-lifecycle | Add legal hold flag that blocks auto-deletion |
