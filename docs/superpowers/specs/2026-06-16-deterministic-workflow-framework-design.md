# Deterministic Workflow Framework — High-Level Design

**Design Scope:** Architecture discussions only. No implementation code.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | Initial three-layer architecture |
| 2026-06-16 | 0.2.0 | Reset to minimal version for step-by-step discussion |

---

## 1. Problem Statement

Enterprise chatbots in regulated industries (finance, health, insurance) need to be auditable and predictable—but users speak natural language. A purely rule-based system can't understand users; a purely LLM-driven system can't guarantee correctness.

## 2. Core Architecture: Three Layers

```
User Input
   │
   ▼
┌─────────────────────┐
│ Layer 1: UNDERSTAND │  → "What does the user want?"
│ Intent + Entities    │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Layer 2: DECIDE      │  → "What should we do?"
│ Routing + Execution  │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Layer 3: RESPOND     │  → "What do we say back?"
│ Message Generation   │
└─────────────────────┘
```

- **Layer 1** extracts intent and structured entities from free-form user input.
- **Layer 2** decides the next state, validates data, and performs deterministic business logic.
- **Layer 3** produces the user-visible response.

## 3. Key Insight: Per-Node Control, Not Per-Layer

The LLM/deterministic decision is not made at the layer level. Each individual node within each layer independently chooses whether to use LLM or deterministic rules.

For example, within Layer 2, a routing node might be a pure `switch` statement (deterministic), while the node next to it might use LLM for semantic validation (LLM). Layers describe *what* happens; nodes describe *how*.

---

## References

1. LangGraph — State graph execution framework (runtime substrate). *github.com/langchain-ai/langgraph*
2. Rasa CALM — "The LLM understands; the code enforces." *rasa.com*
3. zelkim/langgraph-insurance-chatbot — LangGraph.js insurance quote chatbot. *github.com/zelkim/langgraph-insurance-chatbot*
4. Prodigal Payment Collection Agent — Python FSM payment agent. *github.com/AvnishChitrigi/Prodigal-Assignment-Production-Ready-Payment-Collection-AI-Agent*
