<p align="center">
  <h1 align="center">Deterministic AI Agent</h1>
  <p align="center">
    <strong>If you think AI workflows don't need 100% determinism, this project is not for you.</strong>
  </p>
  <p align="center">
    A reference architecture for auditable, deterministic LLM agents in regulated industries.
    <br />
    Built for correctness. Not probabilistic guessing.
  </p>
</p>

<p align="center">
  <a href="https://github.com/cicidi/deterministic-ai-agent/stargazers">
    <img src="https://img.shields.io/github/stars/cicidi/deterministic-ai-agent?style=social" alt="GitHub stars" />
  </a>
  <a href="https://github.com/cicidi/deterministic-ai-agent/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/cicidi/deterministic-ai-agent" alt="License" />
  </a>
  <a href="https://github.com/cicidi/deterministic-ai-agent">
    <img src="https://img.shields.io/badge/status-spec--phase-blue" alt="Status" />
  </a>
  <a href="https://github.com/cicidi/deterministic-ai-agent">
    <img src="https://img.shields.io/badge/stack-Python%20%2B%20LangGraph-forestgreen" alt="Stack" />
  </a>
</p>

---

## The Problem

LLM agents are **unreliable** where it matters most:

- Banking agents that approve the wrong loan amount
- Insurance agents that misroute a claim
- Healthcare agents that collect incomplete patient data

Existing agent frameworks (LangChain, CrewAI) treat the LLM as the primary decision engine. In regulated industries, **the LLM must assist — never decide.**

### A Real Example: Mid-Workflow Topic Switch

A user in the middle of a payment workflow says:

> "Never mind, I want to pay someone else."

**What a probabilistic agent might do on its own:**

| Guess | Risk |
|-------|------|
| Transfer the same amount to a different person | Wrong recipient → financial liability |
| Cancel and create a brand new payment request | Loses context the user might want to keep |
| Just proceed with the original payment | Ignores the user's explicit intent change |

**What this framework does — 100% deterministic:**

```
1. CLASSIFY → intent: "correction" or "change_topic" (recognized, not guessed)
2. EXTRACT  → nothing. Do NOT guess what the user wants.
3. DECIDE   → State machine: on unlisted intent during active workflow
              → route to CLARIFICATION node (deterministic rule, not LLM choice)
4. RESPOND  → "I noticed you want to change something. Can you clarify:
              • Transfer the same amount to a different person?
              • Start a brand new payment request?
              • Or did you mean something else?"
```

**The LLM saw the intent change. The state machine decided the response. Zero autonomy, zero hallucination, 100% auditable.**

## The Solution

**Deterministic AI Agent** is a three-layer reference architecture that separates LLM-assisted understanding from deterministic execution:

```
           ┌──────────────────────────────────────┐
           │       LAYER 1: UNDERSTAND             │
           │  Classify Intent → Extract Entities   │
           │  (LLM-assisted, guardrail-enforced)    │
           ├──────────────────────────────────────┤
           │       LAYER 2: DECIDE                  │
           │  State Machine → Route → Execute       │
           │  (100% deterministic, auditable)        │
           ├──────────────────────────────────────┤
           │       LAYER 3: RESPOND                  │
           │  Generate Message → Check Completion   │
           │  (LLM allowed, PII-scrubbed)            │
           └──────────────────────────────────────┘
```

**Per-node granularity:** Every node independently chooses LLM or deterministic execution. A workflow can have 5 deterministic nodes + 1 LLM node — not an all-or-nothing binary switch.

## Why This Matters

| | Raw LangGraph | This Framework |
|---|---|---|
| **LLM decides routing?** | Often | Never — state machine |
| **Data validation** | Manual | Extract → Validate → Transform pipeline |
| **Audit trail** | DIY | Every LLM call + every state transition logged |
| **Multi-intent handling** | Not built-in | Classify multiple intents per message, validate combinations |
| **Permission model** | None | Per-node tool + transition allowlists |
| **Fallback** | LLM failure = crash | Keyword/regex fallback on every extraction field |

## Who Is This For

- **Fintech** — insurance quoting, claims processing, payment collection
- **Banking** — KYC onboarding, fraud investigation, loan origination
- **Healthcare** — patient intake, prior authorization, appointment scheduling
- **Legal / Government** — any workflow where hallucination = liability

## Key Design Decisions

> Every decision is documented with **WHY** — not just what we chose.

| Decision | Rationale |
|----------|-----------|
| Python + LangGraph | State graph, checkpoint, streaming; strongest AI ecosystem |
| Two-stage classify + extract | Accuracy > latency: scoped schema per extract call prevents cross-intent field confusion |
| Per-node LLM/deterministic switch | Not per-layer binary — granular control where it matters |
| All LLM output = JSON + guardrails | Schema validation, field presence, type coercion enforced before result enters pipeline |
| Multi-intent per message | Single user utterance → multiple resolved intents (e.g., "file a claim, my phone is X") |
| Sub-workflow reuse | Shared capabilities defined once, invoked from any state |

## Quick Example

A user says: *"I want to file a claim for water damage, my phone is 555-0123"*

```
1. CLASSIFY → [{ intent: "file_claim", confidence: 0.95 },
               { intent: "provide_information", confidence: 0.88 }]

2. EXTRACT  → FileClaimIntentPayload { field_values: {} }
               ProvideInformationIntentPayload { field_values: { phone: "555-0123" } }

3. VALIDATE → phone exists in AgentState? ✓  value non-empty? ✓

4. DECIDE   → State machine routes to file_claim state, stores phone in AgentState

5. RESPOND  → "I've started your claim. What type of water damage occurred?"
```

## Documentation

### Spec Documents (13 complete)

| Spec | Covers |
|------|--------|
| [High-Level Design](docs/specs/2026-06-16-deterministic-workflow-framework-design.md) | 3-layer architecture, per-node control, framework principles |
| [Intent Classification](docs/specs/2026-06-16-intent-classification-design.md) | LLM-first, 17 system intents, multi-intent, complex flag |
| [Extraction Layer](docs/specs/2026-06-17-extraction-layer-design.md) | Extract/Validate/Transform pipeline, typed intent payloads, guardrail |
| [State Machine](docs/specs/2026-06-16-state-machine-design.md) | Transitions + LangGraph fusion, state metadata, intent+state resolution |
| [Domain Model](docs/specs/2026-06-17-domain-model-design.md) | Entity/State/Transition schemas, single source of truth |
| [Routing & Execution](docs/specs/2026-06-17-routing-execution-layer-design.md) | Executors, decision nodes, sub-workflows, retry/error handling, permissions |
| [Response Generation](docs/specs/2026-06-17-response-generation-layer-design.md) | Goal-driven workflow, LLM/widget modes, PII scrubbing |
| [LLM Gateway](docs/specs/2026-06-17-llm-gateway.md) | Mandatory JSON output, schema validation, retry logic |
| [RAG Interface](docs/specs/2026-06-18-rag-interface.md) | DocumentStore, Embedder, Retriever, RAGPipeline — adopt, don't invent |
| [Agent Types](docs/specs/2026-06-18-agent-types.md) | ReadOnlyAgent, EscalationAgent — intent→agent dispatch; writes stay in state machine |
| [Tool Ecosystem](docs/specs/2026-06-17-tool-ecosystem.md) | LangFlow, LangGraph CLI, LangSmith, rule engines, MCP |
| [Environment Config](docs/specs/2026-06-17-environment-config.md) | dev/e2e/prod, env hierarchy, per-env thresholds |
| [Auth & Token](docs/specs/2026-06-17-auth-token-verification.md) | JWT/OAuth/OIDC, multi-tenant isolation |

### Example: Home Insurance

Full end-to-end walkthroughs in [`docs/examples/home-insurance/`](docs/examples/home-insurance/):
- Get a quote (collect property info → risk score → manual/auto approval)
- File & settle a claim (damage details → deductible math → payout)
- High-risk routing (guard-based branching → human review → rejection)

## Tech Stack

| Category | Tool |
|----------|------|
| Runtime | Python + LangGraph |
| State Machine | transitions |
| Visual Editor | LangFlow |
| Dev Server | LangGraph CLI |
| Debug | LangSmith Studio |
| Rule Engines | durable_rules / business-rules / pyknow |
| PII Detection | Microsoft Presidio |

## Project Status

**Phase:** Specification design. Implementation code deferred.

| Deliverable | Status |
|-------------|--------|
| Framework Specs | 13 specs complete |
| Spec Generator Skill | Planned |
| Python Reference Implementation | Planned |

## Getting Involved

- **Star this repo** if you work on enterprise AI agents
- Read the [design docs](docs/specs/) — the architecture applies to any LLM agent framework
- Open an issue for discussion: architecture, industry use cases, implementation questions

---

<p align="center">
  <sub>Built for regulated industries. Designed for correctness.</sub>
</p>
