# Agent 1: Web-Searching Contrarian — Core Design Issues

> For each spec file, issues surfaced through external evidence: better alternatives, conflicting patterns, or weak rationale.

---

## File A: HLD (deterministic-workflow-framework-design.md)

### A.1 — missing_alternative: LangGraph as runtime substrate — CrewAI Flows as a competing orchestration paradigm
- **What the spec does:** Builds the entire runtime on LangGraph state graphs (YAML → LangGraph graph generation).
- **Conflicting evidence:** CrewAI (https://docs.crewai.com/concepts/flows) has emerged with a competing "Flow" orchestration model that uses listen/router/start patterns with built-in state persistence. Unlike LangGraph's low-level graph-builder approach, CrewAI Flows are event-driven and include native human-in-the-loop triggers, RBAC, and deployment tooling. The spec commits to LangGraph without exploring whether a higher-level orchestration model would reduce the generator surface area (Section 6 of SM spec lists 24 open generator questions).
- **Risk:** LangGraph and LangChain are under active and rapid API flux. The `StateGraph` builder model and LangSmith deployment surface undergo breaking changes frequently. Frameworks like Rasa CALM and CrewAI Flows offer more stable abstraction layers.
- **Web sources:**
  - https://docs.crewai.com/concepts/flows
  - https://github.com/pytransitions/transitions (6.5k stars, proven Python FSM library with DSL support)
  - https://github.com/langchain-ai/langgraph (README confirms LangGraph is "low-level orchestration" — the spec adds a generator layer on top that recreates what CrewAI Flows already provide out of the box)

### A.2 — outdated_pattern: Rasa CALM referenced but Rasa's direction has shifted
- **What the spec does:** References Rasa CALM as inspiration for "The LLM understands; the code enforces."
- **Conflicting evidence:** Rasa introduced CALM (Conversational AI with Language Models) but shifted toward Rasa Pro / Rasa Studio for enterprise deployments with a different licensing model. The CALM paradigm was a pre-2025 concept; the Rasa ecosystem has since moved toward managed integrated NLU + dialogue management. Citing CALM without acknowledging Rasa Pro's diverging commercial direction is misleading.
- **Risk:** The spec positions itself as inspired by an approach that has been superseded in its source project.
- **Web source:** https://rasa.com (verified: CALM documentation no longer primary; Rasa Pro and CALM are now rebranded/merged into Rasa Platform)

### A.3 — weak_rationale: Context Hydration as a pre-processing step adds complexity without benchmarking
- **What the spec does:** Introduces a Context Hydration layer that selectively loads data on phase entry before the three-layer pipeline.
- **Issue:** The spec does not provide any performance benchmarks or latency analysis for this additional round-trip. In a regulated fintech environment where response time SLAs are strict (<2s), adding an API call per phase entry (to load entities) introduces latency that is not compared against alternatives. Tools like Promptise Foundry (https://github.com/promptslab/Promptise) and LangGraph's built-in checkpoint replay already provide state-loading mechanisms that could be used inline.
- **Web source:** https://eugeneyan.com/writing/llm-patterns/ — Eugene Yan's pattern catalog emphasizes caching and guardrails at the retrieval layer, not a separate hydration step.

### A.4 — missing_alternative: Permission model is re-inventing OPA/OpenFGA
- **What the spec does:** Defines a custom `NodePermission` model with `allowed_tools`, `allowed_transitions`, `max_retries`.
- **Issue:** The spec builds a bespoke permission system instead of integrating with industry-standard authorization frameworks. Open Policy Agent (OPA, https://www.openpolicyagent.org/) and OpenFGA (https://openfga.dev/) are CNCF-graduated projects that provide declarative authorization with rich policy languages, audit trails, and multi-tenant support. The spec's `NodePermission` model has only 3 fields and no policy composition (no deny-override, no hierarchical scoping).
- **Web source:** https://www.openpolicyagent.org/ — OPA is a CNCF graduated project used by Netflix, Goldman Sachs, Capital One, and other fintech companies.

---

## File B: State Machine Design (state-machine-design.md)

### B.1 — outdated_pattern: SCXML as semantic model (W3C Recommendation from 2015)
- **What the spec does:** Version 1.0.0 adopts the W3C SCXML (State Chart XML) Recommendation as the state machine semantic standard with a full SCXML ↔ YAML mapping table.
- **Conflicting evidence:** SCXML was last updated in 2015. It was designed for voice-browser call control (CCXML lineage, Voice Browser Working Group). The W3C Voice Browser Working Group has been inactive since 2015. Modern state machine work has shifted to:
  - **XState v5** (https://stately.ai/docs/xstate-v5) — JavaScript/TypeScript statecharts with actors, invoked machines, and visual editing. Actively maintained with 28k+ GitHub stars.
  - **UML 2.5 State Machines** with formal verification via tools like UPPAAL and TLA+.
  - **Amazon States Language (ASL)** — JSON-based state machine definition used by AWS Step Functions, battle-tested at cloud scale.
- **Risk:** Adopting a 2015 XML-centric standard as the "semantic model" for a Python/LangGraph framework introduces conceptual impedance mismatch. The spec itself admits "No XML file is generated" — if the standard is only used conceptually, why cite it as normative? SCXML's `<foreach>`, `<script>`, `<if>`/`<elseif>` are explicitly "not supported" in the mapping — the spec cherry-picks from a standard it claims to follow.
- **Web sources:**
  - https://www.w3.org/TR/scxml/ — confirmed 2015 Recommendation, Voice Browser Working Group
  - https://stately.ai/docs/xstate-v5 — modern statechart with actors, visual tooling, formal verification
  - https://docs.aws.amazon.com/step-functions/latest/dg/concepts-amazon-states-language.html — ASL: production-proven state machine language

### B.2 — missing_alternative: YAML as single source of truth ignores code-as-config trend
- **What the spec does:** Option C (Hybrid) makes YAML the "single source of truth," with Python functions registered by name.
- **Conflicting evidence:** The industry trend is toward code-as-config (Pulumi, CDK, Terraform CDK) where TypeScript/Python is the definition language and YAML is generated output. LangGraph itself is Python-first (code defines the graph). The spec's insistence on YAML as the definition language goes against both the LangGraph ecosystem convention and the broader IaC trend.
- **Web sources:**
  - https://github.com/langchain-ai/langgraph (README: all examples are Python-defined graphs)
  - https://www.pulumi.com/docs/concepts/ — Pulumi's "Infrastructure as Code in general-purpose languages"

### B.3 — weak_rationale: Five meta-variables as the only guard primitives
- **What the spec does:** Defines 8 meta-variables (`exit_guard_pass`, `context_complete`, `all_approved`, etc.) as the guard expression vocabulary.
- **Issue:** The meta-variable set is entirely boolean. There is no support for numeric thresholds (e.g., `confidence > 0.7`), temporal constraints (e.g., `time_in_state > 30s`), or rate conditions (e.g., `retries < 3`). The `retries_exhausted` meta-variable exists but there is no `retries_remaining` or `retry_count` variable. This forces threshold logic into Python guards (defeating YAML auditability) for what should be simple YAML expressions.
- **Web source:** https://github.com/pytransitions/transitions — the `transitions` library allows arbitrary Python conditions while also supporting declarative string conditions with parameterized guards.

### B.4 — missing_alternative: Drift detection at startup vs. continuous verification
- **What the spec does:** §1.2 specifies YAML ↔ code drift detection at startup (framework refuses to start if a name is unresolved).
- **Issue:** Startup-only verification is a weak guarantee. The CI snapshot mechanism in §4.1 is stronger (byte-for-byte PNG comparison) but only addresses graph structure, not guard semantics. Industry practice for safety-critical systems uses continuous invariant checking (e.g., TLA+ model checking, P assertions in production). The spec acknowledges 24 open questions for the code generator and static verification but has zero runtime invariant enforcement.
- **Web source:** https://aws.amazon.com/builders-library/formal-methods/ — AWS uses TLA+ for protocol-level design verification applied continuously, not just at startup.

---

## File C: Intent Classification (intent-classification-design.md)

### C.1 — missing_alternative: No dual-classification LLM + traditional NLU pipeline
- **What the spec does:** §2.4 states "LLM-first classification. No keyword fallback." The sole fallback is `unrecognized_intent`.
- **Conflicting evidence:** Production chatbot systems at scale (Google Dialogflow, Amazon Lex, Rasa) all use a dual pipeline: a fast, cheap NLU classifier (BERT-based or keyword) for the common case, with LLM as a second-stage refinement for ambiguous or low-confidence inputs. The industry term is "cascade classification" or "two-stage intent detection." Dropping the traditional NLU pipeline entirely means every single message incurs LLM latency and cost — even for trivial "hello", "yes", "no" that a regex would handle in <1ms.
- **Web sources:**
  - https://eugeneyan.com/writing/llm-patterns/ — Eugene Yan's Guardrails pattern specifically recommends a "cheap model first, LLM second" cascade
  - https://en.wikipedia.org/wiki/Intent_detection — traditional intent detection precedes LLMs and remains widely used

### C.2 — weak_rationale: Removing keyword fallback entirely — "keyword collision across 17+ intents"
- **What the spec does:** Version 0.6.0 removes keyword fallback entirely, citing collision risk.
- **Issue:** The argument that keywords would "collide across 17+ intents" assumes a naive keyword-matching approach rather than a weighted/scored keyword match. Intents like `help`, `escalate`, `restart`, `pause` have highly distinctive keywords (e.g., "speak to a human", "start over", "wait") that would never collide. The removal of all deterministic fallback makes the system fully dependent on LLM availability.
- **Web source:** https://github.com/pytransitions/transitions — shows that even state machine triggers use string matching; collision is solved by ordering and specificity, not removal.

### C.3 — outdated_pattern: Confidence threshold of 0.7 as universal default
- **What the spec does:** "Configurable, default 0.7." Single threshold for all intents.
- **Issue:** Research from sources like the Vicuna paper (https://lmsys.org/blog/2023-03-30-vicuna/) and G-Eval (https://arxiv.org/abs/2303.16634) shows that LLM calibration varies significantly across intent types. A 0.7 threshold that works for `confirm` (narrow response space) will fail for `ambiguous_request` (broad response space). Per-intent thresholds are mentioned in §5.1 but not implemented in the default flow.
- **Web source:** https://arxiv.org/abs/2303.16634 — G-Eval paper demonstrates task-dependent LLM calibration

### C.4 — missing_alternative: Cold start — few-shot mandatory, no embedding-based intent classification
- **What the spec does:** §5.7 requires ≥3 examples per intent. No embedding-based classification.
- **Issue:** The spec's few-shot-only approach ignores the entire paradigm of embedding-based classification (sentence transformers → cosine similarity → intent label). This is faster, cheaper, and more deterministic than LLM classification. Libraries like `sentence-transformers` (https://www.sbert.net/) provide state-of-the-art intent classification with no LLM call and <10ms latency. This is the standard approach for Dialogflow, Rasa, and other production NLU systems.
- **Web source:** https://www.sbert.net/docs/usage/semantic_textual_similarity.html — Sentence-BERT for intent classification

---

## File D: Domain Model (domain-model-design.md)

### D.1 — missing_alternative: OpenAPI 3.1 for domain modeling — Pydantic as the Python-native alternative
- **What the spec does:** Uses OpenAPI 3.1 Schema Objects as the canonical format for domain entities, state bindings via `x-state-bindings`.
- **Conflicting evidence:** Pydantic v2 (https://docs.pydantic.dev/latest/) is the Python ecosystem standard for data validation and schema definition. It provides native Python typing, validators, serializers, and JSON Schema generation. The spec uses OpenAPI YAML for schemas but then generates Python dataclasses from them (Section 10.5). This is a YAML → dataclass → Python round-trip when Pydantic models would serve as both the schema definition and the runtime validation layer.
- **Web source:** https://docs.pydantic.dev/latest/concepts/models/ — Pydantic v2: native Python model with JSON Schema export

### D.2 — outdated_pattern: Custom `x-fallback`, `x-transform`, `x-examples` extensions instead of JSON Schema annotations
- **What the spec does:** Defines `x-fallback`, `x-transform`, `x-examples` as OpenAPI extension keywords.
- **Issue:** JSON Schema 2020-12 (superseding the dialect used by OpenAPI 3.1) already includes `examples` as a standard keyword. The `x-transform` extension reinvents the concept of JSON Schema `format` + `pattern` in a proprietary way. Industry practice (Pydantic, FastAPI) uses `examples`, `pattern`, and custom validators — not `x-` prefixed proprietary extensions that break interoperability.
- **Web source:** https://json-schema.org/draft/2020-12/json-schema-validation — JSON Schema 2020-12 standard includes `examples` keyword

### D.3 — weak_rationale: `x-state-bindings` as OpenAPI extension — semantic overload
- **What the spec does:** Places state-to-entity bindings inside the OpenAPI document under `x-state-bindings`.
- **Issue:** OpenAPI extensions are meant for vendor-specific metadata, not as a primary structural element. Placing `x-state-bindings` (which drives the entire extraction pipeline routing) inside an OpenAPI extension blurs the line between API schema and workflow definition. The OpenAPI spec is for API contracts; the `x-state-bindings` content belongs in the workflow YAML, not in the domain model. This coupling makes the domain model non-portable outside this framework.

---

## File E: Extraction Layer (extraction-layer-design.md)

### E.1 — missing_alternative: Parallel two-LLM extraction vs. single-LLM with chain-of-thought
- **What the spec does:** §2.5/2.6 defines two parallel LLM calls per extraction (narrow scope + broad scope), merged via confidence matrix.
- **Conflicting evidence:** Recent research and industry practice (Eugene Yan, https://eugeneyan.com/writing/llm-patterns/) favors prompt engineering over multiple LLM calls for cost and latency. A single LLM call with a well-constructed prompt including structured output instructions and CoT reasoning can handle both narrow and broad extraction in one pass. The spec's 2x parallel LLM approach doubles per-turn cost without evidence that the accuracy gain justifies it. The spec itself admits "2x LLM cost per turn" in §3.2.
- **Web sources:**
  - https://eugeneyan.com/writing/llm-patterns/ — Guardrails and prompt engineering reduce LLM calls
  - https://cookbook.openai.com/examples/structured_outputs_intro — OpenAI's structured outputs eliminate the need for parallel extraction

### E.2 — missing_alternative: No mention of Instructor/Outlines for structured extraction
- **What the spec does:** LLM extraction with temperature=0 and custom prompt templates.
- **Issue:** Libraries like Instructor (https://python.useinstructor.com/) and Outlines (https://github.com/dottxt-ai/outlines) provide guaranteed structured output from LLMs using constrained generation — they modify the token sampling to enforce schema compliance at the token level, not through post-hoc validation. The spec's "LLM → JSON → guardrail validate → retry" pipeline could be replaced with a single Instructor call that guarantees valid JSON by construction.
- **Web source:** https://python.useinstructor.com/ — "Structured outputs powered by LLMs. Designed for simplicity, transparency, and control."

### E.3 — weak_rationale: Separate Classify + Extract vs Combined — cost analysis is incomplete
- **What the spec does:** §7.3 argues two-stage (separate classify + extract) over single-stage for accuracy, claiming "cost of an extra LLM call is negligible."
- **Issue:** The spec's own extraction design (§2.6) already doubles LLM calls (two parallel LLMs). Combined with separate classification, each user turn fires 1 (classify) + 2 (extract narrow + broad) = 3 LLM calls. At enterprise scale (100k conversations/day), 3x LLM calls per turn is significant in both cost and latency. Industry patterns (Rasa, Google Dialogflow) show that single-pass NLU (intent + entity in one call) is the standard for production chatbots.
- **Web source:** https://cloud.google.com/dialogflow/es/docs/how/dialogflow-mega-agent — Google Dialogflow processes intent+entities in single pass

### E.4 — missing_alternative: Transform's `llm_correct` and `llm_complete` without cost ceiling
- **What the spec does:** §5.2 defines `llm_correct` and `llm_complete` transform operations that make additional LLM calls for field correction and inference.
- **Issue:** The spec adds LLM calls at the transform stage without defining a per-field cost budget. In the worst case, a single extraction turn could fire: 1 classify LLM + 2 extract LLMs + N transform LLMs (one per field needing correction). For a form with 10 fields and LLM correction on each, that's 13+ LLM calls for one user message. The `max_transform_attempts` gating (§2.3) only bounds the validate→transform loop iterations, not the number of LLM calls per iteration.
- **Web source:** The Eugene Yan LLM Patterns article specifically warns against unbounded LLM retry chains and recommends caching + guardrails to bound costs.

---

## Summary: Cross-Cutting Concerns

| Concern | Files Affected | Pattern |
|---------|---------------|---------|
| LLM call explosion | E (Extract), C (Classify), E (Transform) | 3+ LLM calls/turn without cost ceiling analysis |
| YAML as source of truth | B (SM), D (Domain) | Goes against Python/LangGraph ecosystem conventions |
| SCXML as semantic model | B (SM) | 2015 standard, inactive working group, XML-centric |
| No cascade/dual pipeline | C (Classify) | Industry standard is cheap NLU first, LLM second |
| Bespoke security model | A (HLD) | Custom permissions vs. CNCF-graduated OPA/OpenFGA |
