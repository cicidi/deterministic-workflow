---
name: auto-tdd
description: |
  Reference stub pointing to the full ai-coworker-auto-tdd skill.
  Load the ai-coworker skill for the complete 3-agent arbitration TDD workflow.
user-invocable: true
---

# Auto-TDD → ai-coworker-auto-tdd

This is a reference stub. The full skill lives at:

**`ai-coworker-auto-tdd`** in the ai-coworker skill registry.

To use it, invoke the ai-coworker-auto-tdd skill. It provides:

- 3-agent arbitration loop (Agent-A impl, Agent-B test, Agent-C judge, Agent-D quality)
- 举一反三 test writing protocol (Tier 1 mock → Tier 2 sim LLM → Tier 3 quality judge)
- Anti-stall protocol (never stops until truly complete)
- Self-managing task queue (auto-discovers and adds new tasks)
- Incremental commit discipline (commit per change, PR at end)

See the full skill at: `ai-coworker-skills/ai-coworker-auto-tdd/SKILL.md`
