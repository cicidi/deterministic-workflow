---
name: implement-interview
description: |
  Use when a developer has a concrete product idea and wants a runnable Python agent generated from the deterministic-workflow framework. Time-boxed adaptive interview that walks through product discovery, domain model, and code generation. Focuses on MVP essentials; all framework-level decisions use smart defaults. Outputs a complete Python project (LangGraph state machine + executors + tests) ready to run.
user-invocable: true
---

# Implement Interview — Deterministic Workflow Framework

## When to Use

A developer says "I want to build X using this framework" and wants runnable code, not just a plan document. The skill interviews the developer through a time-boxed adaptive process and generates a complete Python project.

**This skill IS the `spec-generator` from VISION.md**, upgraded to produce code instead of documents.

## When NOT to Use

- Developer only wants a design document, not code
- The product is too vague to describe a single MVP workflow
- Developer wants to hand-write the state machine from scratch

## Prerequisites

Load these spec files before interviewing. They are the source of truth for defaults and constraints:

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

Also read `docs/VISION.md` for project vision and constraints.

## Interview Flow

### META: Time Budget (always first)

Start with exactly one question:

> "How much time do you have? (15 min / 30 min / 1 hour+)"

This determines which levels are asked:

### META: PRD Check (always second, before Level 1)

Ask:

> "Do you already have a PRD (Product Requirements Document) for this product? If yes, share it and I'll use it as the source of truth. If no, I'll generate one from our interview."

**If PRD exists:** Read it. Use it as the authoritative source for all questions. Skip questions already answered in the PRD. Fill remaining gaps via interview.

**If no PRD:** Proceed with the interview. The output will include a generated PRD that the developer must approve before code generation begins.

| Time   | Level 1 | Level 2 | Level 3 | Level 4 |
|--------|---------|---------|---------|---------|
| 15 min | Yes     | No      | No      | No      |
| 30 min | Yes     | Yes     | Partial (1-2 picks) | No |
| 1h+    | Yes     | Yes     | Yes     | Yes     |

### Level 1: Goal & Product (always asked, ~3 min)

Ask these questions in order. Single question per message.

1. **What product are you building?** (e.g., "insurance claims chatbot", "payment collection agent")

2. **Who are the users?** (e.g., "internal claims adjusters", "external banking customers")

3. **What is the primary goal?** What does a successful interaction look like?

4. **What is the #1 MVP workflow?** Describe step by step what the user says and what the agent does in response. Only one workflow at this level. (e.g., "User says 'I want to file a claim' → agent asks for policy number → agent asks for incident date → agent asks for description → agent confirms and submits")

### Level 2: Domain Model (30min+ only, ~5-8 min)

For the MVP workflow from Level 1:

5. **Entities.** What data entities does this workflow operate on?
   - For each: name + 3-5 key fields + types.
   - If developer doesn't know exact fields, generate a reasonable skeleton and note `# TODO: verify fields`.

6. **States.** What phases/states does this workflow move through?
   - For each: name + one-line description.
   - Default states: `start`, `{workflow_name}_in_progress`, `completed`, `error`.

7. **Transitions.** For each state, what causes a transition to the next state?
   - Format: "when {condition}, go from {state_a} to {state_b}"

### Level 3: Strategy Decisions (30min+: pick 1-2; 1h+: all, ~3-5 min)

For 30min, ask only the most impactful questions. For 1h+, ask all four.

8. **LLM provider.** Which LLM to use?
   - Options: `deepseek-v4` (default), `openai`, `anthropic`, `ollama`
   - On "I don't know": use `deepseek-v4`

9. **Auth method.** How are users authenticated?
   - Options: `api_key` (default for dev), `auth0`, `okta`, `keycloak`
   - On "I don't know": use `api_key`

10. **External APIs.** Does this workflow call any external services?
    - Examples: payment gateway, CRM, policy lookup, identity verification
    - On "none" or "I don't know": generate API stub placeholders

11. **RAG / Knowledge base.** Does the agent need to answer questions from documents?
    - On "yes": ask which document source
    - On "no" or "I don't know": skip RAG integration

### Level 4: Extended (1h+ only, ~5-8 min)

12. **Second workflow.** Is there another important workflow? (Repeat Level 2 for it.)
    - On "no": stop here and generate.

13. **Environment differences.** Any differences between dev / e2e / prod?
    - Default: `dev` uses cheap LLM + mock APIs; `e2e` uses prod models + mock APIs; `prod` uses real everything with full guardrails.

14. **Observability.** Which tracing tool?
    - Options: `LangSmith` (default), `LangFuse`, `none`
    - On "I don't know": generate LangSmith config stubs

### Strategy Defaults (NEVER ask these)

The following framework-level decisions use spec defaults. Do NOT ask the developer about them unless the developer explicitly brings them up:

| Decision | Default | Spec Source |
|----------|---------|-------------|
| Extract strategy | `hybrid` (LLM-first + deterministic fallback) | extraction-layer-design §3.2 |
| Validate strategy | `durable_rules` | extraction-layer-design §4 |
| Transform strategy | `deterministic` | extraction-layer-design §5 |
| Response strategy | `pure_message` (LLM, temperature=0.3) | response-generation-layer-design §3 |
| Decision strategy | `rule_engine_only` (no LLM fallback in Layer 2) | routing-execution-layer-design §4 |
| Rule engine | `durable_rules` | tool-ecosystem §3 |
| Permission engine | `native` (YAML allowlists) | routing-execution-layer-design §6 |
| LLM Gateway strategy | `hybrid` | llm-gateway §3 |
| Retry budget | LLM nodes: 3 attempts; deterministic nodes: 2 attempts | routing-execution-layer-design §5 |
| Error handling | All errors → unified errorNode | routing-execution-layer-design §5.2 |

### Completeness Verification (MANDATORY before code generation)

**Purpose:** Prevent the "yolo aggressive → skip everything → declare done too early" failure mode. This phase runs AFTER the interview and BEFORE any code is generated. It is NOT optional.

1. **Requirement ↔ Spec traceability:** For every user-stated requirement, identify which section of the generated spec covers it. If any requirement has no coverage, go back and ask.

2. **Artifacts discovery:** Ask explicitly:
   - "Do you have existing API documentation, Postman collections, or test suites I should review?"
   - "Is there existing code (even in another language) that implements part of this?"
   - "Are there competitor products or reference systems I should understand?"

3. **Multi-party interaction check:** If the system involves 2+ user types (e.g., borrower + loan officer), ask:
   - "Do these users need to communicate with each other through the agent?"
   - "Does the agent need to hide any information from either party?"
   - "Are there payment gates or access control between parties?"

4. **Privacy & security check:**
   - "What contact information should be visible to whom?"
   - "Are there PII (personally identifiable information) concerns?"
   - "Is there a payment or subscription model involved?"

5. **Testing requirements check:**
   - "What test scenarios are most important to you? (beyond the happy path)"
   - "Should tests include edge cases like wrong values, corrections, and topic jumps?"
   - "Do you want simulated LLM-driven conversation tests in addition to deterministic ones?"

6. **Output format check:**
   - "Should the agent be accessible via CLI, REST API, MCP server, or A2A protocol?"
   - "What authentication method should the agent use?"

7. **Completeness self-audit:** Before declaring interview complete, verify:
   - Every user-stated requirement → has a spec section
   - Every spec section → has at least one decision made (not deferred)
   - Every entity → has fields defined
   - Every state → has transitions defined
   - Every strategy → has an explicit choice (not "default, didn't ask")

If ANY check fails, add the missing item to the interview and ask the developer. Do NOT fill gaps with assumptions — ask.

## Code Generation

**PRD MUST come first.** Before generating any code, produce a PRD document (`PRD.md`) and get developer approval. Code is generated from the approved PRD, not from interview notes.

### PRD Generation (Phase 5 — before code)

After the Completeness Verification passes, generate a Product Requirements Document with:

```markdown
# [Product Name] — Product Requirements Document

## 1. Product Summary
## 2. User Personas (who, goals, constraints)
## 3. Core Workflows (with conversation examples)
## 4. Domain Model (entities, states, transitions)
## 5. Feature Checklist (every feature, with status)
## 6. Architecture (three layers, strategy decisions)
## 7. Test Coverage Plan (scenarios to test)
## 8. Out of Scope (explicitly deferred features)
## 9. Open Questions
```

**Review gate:** Present the PRD to the developer. Do NOT proceed to code generation until the developer approves it. If the developer finds gaps, iterate on the PRD.

### Code Generation (Phase 6 — after PRD approved)

After the PRD is approved, generate a runnable Python project.

### Project Structure

```
{product-slug}/
├── config/
│   ├── domain_model.yaml      # Entity + State + Transition definitions
│   ├── workflow.yaml            # Strategy selections, env config, tool registry
│   └── intents.yaml             # Custom intent definitions
├── src/
│   ├── state_machine.py         # LangGraph StateGraph (auto-generated)
│   ├── executors/
│   │   ├── extract.py           # Layer 1: E->V->T pipeline
│   │   ├── classify.py          # Layer 1: Intent classification
│   │   ├── decide.py            # Layer 2: Business logic (developer fills)
│   │   └── respond.py           # Layer 3: Response generation + goal checker
│   ├── gateway.py               # LLM Gateway (output_schema + JSON validate + retry)
│   └── hydration.py             # Context Hydration
├── tests/
│   └── test_workflow.py         # Happy-path test with mocked LLM
├── main.py                      # Entry point
└── README.md                    # Next steps for the developer
```

### Code Generation Rules

1. **Layer 1 — classify.py.** Intent classification prompt per the intent spec §4. Include 17 system intents + custom intents from interview. Temperature=0. `output_schema` = `IntentClassificationResult`. LLM call via `gateway.llm_call()`.

2. **Layer 1 — extract.py.** E→V→T pipeline:
   - Extract: LLM-first with deterministic regex fallback for every field
   - Validate: `durable_rules` ruleset. Declare the rules in `config/domain_model.yaml` under each entity.
   - Transform: coalesce types, normalize dates, trim strings
   - `output_schema` = entity schema. Mandatory field presence + non-empty check.

3. **Layer 2 — decide.py.** Pure Python business logic. No LLM calls. Each method ≤50 lines. Split by concern if needed (`decide_quote.py`, `decide_claim.py`). Include phase-aware routing and return stack for mid-flow detours.

4. **Layer 3 — respond.py.** Goal setting (async LLM call) + response generation + goal checking (parallel). Temperature=0.3 for response. `output_schema` = `WorkflowResponse`. Goal checker compares achieved vs expected fields.

5. **Gateway.** All LLM calls route through `gateway.llm_call(prompt, output_schema, temperature)`. Gateway handles: JSON validation, type coercion, retry on violation. LLM nodes get +1 extra retry.

6. **State Machine.** LangGraph `StateGraph` with nodes, edges, conditional routing. `AgentState` typed with TypedDict. Copy-on-Write + reducer merge semantics. Mermaid state diagram as comment at top of file.

7. **Config YAML.** Domain model follows domain-model-design.yaml schema. Intents follow intent-classification-design.yaml §5. Workflow config references env-config.yaml schema.

8. **Tests.** Mock LLM responses with `unittest.mock`. Test the happy path through the complete workflow. Assert correct state transitions and field population.

### File Size Enforcement

Apply these rules during code generation:

- **File ≤ 1000 lines.** Before writing any generated file, estimate its line count. If it would exceed 1000:
  - `domain_model.yaml`: split by workflow into `domain_model_{workflow}.yaml`, parent uses `$ref`
  - `state_machine.py`: split sub-workflows into `src/sub_workflows/{name}.py`
  - `decide.py`: split by workflow into `decide_{workflow}.py`
  - Any other file: split by logical concern
- **Method ≤ 50 lines.** If any method exceeds 50 lines, extract helpers or split into sub-modules.
- **Warn, don't silently truncate.** If a split is needed, tell the developer which file was split and why.

### Output Summary

After generation, print:

```
Generated {N} files in {dir}/
  config/: {list}
  src/:    {list}
  tests/:  {list}
  root:    main.py, README.md

File size check: {N} files, {M} warnings.
  state_machine.py: {lines} lines
  domain_model.yaml: {lines} lines

Next: cd {dir} && pip install -r requirements.txt && python main.py
```

## Rules

- If the developer says "I don't know" for any question, use the **default recommendation** from the relevant spec.
- If a question doesn't apply, confirm with the developer before skipping — don't silently drop it.
- Every generated code file references the spec section it implements in a comment.
- The generated `test_workflow.py` must pass with `python -m pytest` out of the box (mocked LLM).
- Never generate more than one question per message during the interview phase.
- Maintain the time budget, but the **Completeness Verification phase** is mandatory regardless of time budget.
- **"yolo aggressive" means move fast, not skip quality.** Never skip the completeness verification.

## Anti-Patterns

| Symptom | Why It's Wrong | Fix |
|---------|---------------|-----|
| Asking about extract/validate/transform strategy | These are framework defaults. Unless developer says "I want to change," skip them. | Only ask if developer pushes back on defaults. |
| Asking all 14 questions on a 15-minute budget | Respect the time budget. | Stop after Level 1 and generate with all defaults. |
| **Declaring "done" after code generation** | Code generation is NOT the end. The developer may have unstated requirements discovered during review. | Run Completeness Verification phase after generation. |
| **Accepting "I want a chatbot" without asking about multi-party flows** | Most business systems have 2+ user types with different views. | Ask: "Who else uses this system? Do they see different things?" |
| **Skipping the artifacts discovery question** | Existing APIs, Postman collections, and legacy code contain requirements you'll miss. | Always ask: "Do you have existing docs/tests/APIs I should review?" |
| **Assuming "yolo aggressive" means skip everything** | It means move quickly, NOT skip quality gates. | Follow the process faster, don't drop steps. |
| **Generating code before asking about output format** | Agent might need to be MCP server, CLI, or REST API — different code. | Ask in Completeness Verification step 6. |
| **Not asking about privacy between user types** | Borrower and officer shouldn't see each other's contact info. You won't build it if you don't ask. | Ask in Completeness Verification step 3. |
| **The "strategy defaults" trap** | Using spec defaults for extract/validate/transform is fine. But critical business decisions (payment model, privacy model, multi-party flows) have NO defaults — they MUST be asked. | Distinguish between "framework defaults" (safe to skip) and "business decisions" (must ask). |
| **Committing = done** | Commits track progress, not completion. The work isn't done until the Completeness Verification passes. | Run the verification checklist before every "done" declaration. |
| Generating a 50-page Markdown plan instead of code | The output is Python code. The only Markdown output is README.md with next steps. |
| Asking prompt engineering questions | LLM prompts are generated from spec templates. Prompt optimization is a separate task. |
| Generating files over 1000 lines | Split before writing. Use $ref for YAML, sub-modules for Python. |

## Sources

- Interview flow: confidence high — based on design spec `docs/superpowers/specs/2026-06-18-mvp-interview-skill-design.md`
- Strategy defaults: confidence high — each default matches the relevant spec document's recommendation
- Code generation rules: confidence high — derived from framework specs (HLD, State Machine, Extraction, Routing, Response, LLM Gateway)
- File size enforcement: confidence high — project principle #7 (file ≤1000, method ≤50)
- Anti-patterns: confidence medium — based on observed patterns from prior implement-interview usage
