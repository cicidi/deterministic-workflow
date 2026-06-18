---
name: implement-interview
description: "Guided interview that walks a developer through all 11 framework specs to produce a complete implementation plan for their specific product. Use when a developer has a concrete product idea and needs a tailored implementation roadmap."
user-invocable: true
---

# Implement Interview — Deterministic Workflow Framework

## When to Use

A developer says "I want to build X using this framework" and needs to go from product concept → implementation plan. The skill loads all 11 spec documents and interviews the developer step by step.

## Prerequisites

The skill requires access to all spec files in `docs/specs/`. Load them before starting:

```
docs/specs/2026-06-16-deterministic-workflow-framework-design.md       (HLD)
docs/specs/2026-06-16-intent-classification-design.md                  (Intent)
docs/specs/2026-06-16-state-machine-design.md                          (State Machine)
docs/specs/2026-06-17-extraction-layer-design.md                       (Extraction)
docs/specs/2026-06-17-domain-model-design.md                           (Domain Model)
docs/specs/2026-06-17-routing-execution-layer-design.md                (Routing & Execution)
docs/specs/2026-06-17-response-generation-layer-design.md              (Response Generation)
docs/specs/2026-06-17-llm-gateway.md                                   (LLM Gateway)
docs/specs/2026-06-17-tool-ecosystem.md                                (Tool Ecosystem)
docs/specs/2026-06-17-environment-config.md                            (Environment Config)
docs/specs/2026-06-17-auth-token-verification.md                       (Auth & Token)
```

Also read `docs/VISION.md` for the project vision and constraints.

## Interview Flow

### Phase 1: Product Discovery (5-10 minutes)

Ask these questions in order. Wait for answers before proceeding.

1. **What is the product?** (e.g., "insurance claims chatbot", "CI/CD pipeline assistant")

2. **Who are the users?** (e.g., "internal claims adjusters", "external customers")

3. **What is the primary goal?** What does a successful interaction look like?

4. **What are the key workflows?** List the 2-5 main things users do (e.g., "file a claim", "check coverage", "get a quote")

5. **Any regulatory requirements?** GDPR, PCI DSS, SOC2, industry-specific?

### Phase 2: Domain Model Design (10-15 minutes)

For EACH workflow identified in Phase 1:

1. **Entities**: What data entities does this workflow operate on?

   Output template:
   ```yaml
   entity_name:
     description: "..."
     fields:
       field_name:
         type: string|int|float|date|boolean|enum|list
         required: true|false
         description: "..."
   ```

2. **States**: What are the phases of this workflow?

   Output template:
   ```yaml
   state_name:
     description: "..."
     entity: bound_entity
     state_hint: "..."
   ```

3. **Transitions**: How do states connect?

   Output template:
   ```yaml
   - from: state_a
     to: state_b
     guard: "field1 != null AND field2 != null"
   ```

### Phase 3: Strategy Selection (5-10 minutes)

For each node type, present the spec's options and ask the developer to choose:

1. **Extract strategy**: `llm_primary` | `deterministic` | `hybrid`
2. **Validate strategy**: `durable_rules` | `business-rules` | `pyknow` | `native` | `pydantic`
3. **Transform strategy**: `deterministic` | `llm_assisted` | `hybrid`
4. **Response strategy**: `pure_message` | `widget` | `mixed`
5. **Decision strategy**: `rule_engine_only` | `rule_engine + llm_fallback` (deferred)
6. **Rule engine**: `durable_rules` (default) | `business-rules` | `pyknow`
7. **Permission engine**: `native` (YAML lists) | `pycasbin`
8. **LLM Gateway strategy**: `hybrid` (default) | `native_only` | `post_process_only`
9. **LLM provider**: `openai` | `anthropic` | `deepseek` | `ollama`
10. **Auth provider**: `auth0` | `okta` | `keycloak` | `api_key` (dev)

### Phase 4: Environment Setup (3-5 minutes)

1. **dev**: Which tools are mocked? Which LLM model? (default: `gpt-4o-mini` or `deepseek-v4-flash`)
2. **e2e**: Which eval datasets? Connected to LangSmith?
3. **prod**: Which real APIs? Checkpoint backend?

### Phase 5: Tool Selection (3-5 minutes)

1. **External APIs**: Which APIs does this workflow call? (payment, CRM, policy lookup...)
2. **MCP Servers**: Any MCP servers needed? (knowledge base, vector search...)
3. **Visual Editor**: Use LangFlow for drag-and-drop design? (yes/no)
4. **Observability**: LangSmith or LangFuse? (dev-only or all envs?)

### Phase 6: Output

After all phases complete, generate a markdown document with:

```markdown
# [Product Name] — Implementation Plan

## 1. Product Summary
## 2. Domain Model (YAML)
## 3. Workflow Configuration (YAML)
## 4. Strategy Decisions
## 5. Environment Configuration
## 6. Tool Registry
## 7. Implementation Roadmap
   - Phase 1: Domain model + state machine setup
   - Phase 2: Extraction pipeline + intent classification
   - Phase 3: Routing + business logic
   - Phase 4: Response generation + goal checking
   - Phase 5: Auth + permissions + tools
   - Phase 6: Eval setup + testing
## 8. Open Decisions (deferred to architect discussion)
```

## Rules

- If the developer says "I don't know" for any question, suggest the **default recommendation** from the relevant spec.
- If a question doesn't apply (e.g., "no external APIs"), skip it — don't force an answer.
- Every answer maps back to a specific section of a specific spec document. Cite the spec.
- The final output document should be self-contained — a new developer should be able to pick it up and start implementing without reading all 11 specs first.
