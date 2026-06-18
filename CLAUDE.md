

## Project Principles

1. **Architecture-First.** Clean, well-structured architecture is the foundation of every decision. Prefer clarity over cleverness.
2. **Fintech-First, Industry-Agnostic.** Primary use case targets fintech (insurance, banking, payment). Architecture must remain generic enough to extend to any regulated industry's agentic workflow (healthcare, legal, government).
3. **Guided Framework, Not Out-of-the-Box.** This is a reference architecture and design pattern framework—not a pre-built, plug-and-play solution. It provides the *how* and *why*; users adapt it to their industry. Detailed implementation questions are deferred for architect-level discussions during adoption, not solved upfront.
4. **Actionable & Extensible.** Every design decision must result in something that can be built and extended. Framework-level concerns (security, multi-tenancy, deployment) are identified early but not prematurely solved.
5. **Learnable.** Documentation, examples, and API design must guide users from understanding to adoption. A new developer should be able to read the spec and understand *what* to build and *why*.
6. **Framework as Interface + Pattern Injection.** The framework exposes clean interfaces but internally injects proven patterns (state-aware prompting, deterministic fallback, sticky mode, sub-workflow reuse). It absorbs the "dirty work" — LLM guardrails, permission enforcement, retry budgets, audit trail — so the developer focuses on business logic.
7. **Code Conventions.** Every method ≤ 50 lines. Every file ≤ 1000 lines. Executors are small, composable, and single-responsibility. Complex workflows are split across files and sub-workflows.
8. **LLM Output is JSON.** All LLM interactions produce structured JSON output. The framework enforces output validation guardrails (schema check, field presence, type coercion). Free-text generation is limited to Layer 3 (Response).
9. **Follow VISION.md.** [docs/VISION.md](./docs/VISION.md) is the authoritative master reference for this project. All design decisions must align with the vision. When writing specs: (a) check the Vision checklist before declaring a spec complete, (b) record every significant design decision with its rationale (WHY) in the Architecture Decisions table AND inline in the relevant spec — accuracy/cost/latency trade-offs must be explicit.

<!-- INITIATIVE:chat-experience-deterministic-work-flow START -->
## Active Initiative: chat-experience-deterministic-work-flow

> Design and build a deterministic workflow framework for enterprise chatbots in regulated industries. Three-layer architecture (NLU/Extraction → Routing/Execution → Response) with per-node LLM/deterministic switch. Outcome: spec documents (no implementation code yet).

### Projects in scope
| Project | Role | Branches |
|---------|------|----------|
| deterministic-workflow | peer | main, feat/deterministic-framework |
| saas-app | peer | main |

### Key Decisions
- Python + LangGraph, generic framework (not single-industry)
- LLM-assisted NLU with deterministic core workflows
- Per-node control granularity (not per-layer binary switch)
- Sub-workflow reuse for shared capabilities
- Spec-first with Python reference implementation
- Design docs: schemas + samples only. No implementation code until requested.
- Docs/comments in English, discussion in Chinese.

### References
- [Primary] zelkim/langgraph-insurance-chatbot (TypeScript, LangGraph.js, insurance quote)
- [Secondary] Prodigal Payment Collection Agent (Python FSM, payment collection)
- [Supplementary] chatbot-FSM-experiment (FastAPI+Next.js, healthcare scheduler)

<!-- INITIATIVE:chat-experience-deterministic-work-flow END -->

