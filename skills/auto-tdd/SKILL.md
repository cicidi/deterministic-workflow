---
name: auto-tdd
description: |
  Use when implementing features or fixing bugs with a multi-agent TDD loop. Dispatches Agent-A (impl), Agent-B (test), and Agent-C (judge) to run a continuous red-green-refactor cycle with arbitration. Self-manages task queues — when new issues surface during the loop, they are automatically added to the task list.
user-invocable: true
---

# Auto-TDD — 3-Agent Arbitration Loop

Continuous multi-agent test-driven development with automatic arbitration. One agent writes code, one writes tests, and a judge resolves disputes when they disagree. The loop self-manages — discovering new tasks and adding them to the queue until all tests pass.

## When to Use

- Building a new feature from spec with TDD
- Fixing bugs discovered by test failures
- Implementing changes where code and tests need to co-evolve
- Developer wants automated quality gates with human-like review
- Need to run a continuous fix-test loop without manual intervention

## When NOT to Use

- Pure research or exploration with no tests
- Single-line config changes
- Tasks where test expectations are perfectly known upfront (use simple TDD instead)
- Writing documentation or non-code artifacts

## Process

### Phase 0: Setup

1. Ensure all spec documents are loaded and understood
2. Create a structured todo list with every known task
3. Define the success criterion: all tests green, zero failures
4. Set loop interval (default: 30 minutes, or run after each change)

### Phase 1: Initial Implementation (Agent-A)

**Agent-A (Implementation Agent)** writes the first version of the code:

1. Read relevant specs and existing code
2. Implement the feature or fix following framework conventions:
   - File ≤ 1000 lines, method ≤ 50 lines
   - Layer 2 (business logic) must be 100% deterministic
   - All LLM output must be JSON via Gateway
   - Copy-on-Write for state mutations
3. Return: code changes made, files modified, known open questions

**Fallback:** If Agent-A cannot implement, escalate to human with specific blocker.

### Phase 2: Test Writing (Agent-B)

**Agent-B (Test Agent)** writes tests for the code:

1. Read the implementation code, specs, and existing test patterns
2. Write both unit tests and functional tests covering:
   - Happy paths (normal flow, expected inputs)
   - Edge cases (empty data, invalid states, boundary values)
   - Error paths (exception handling, retry exhaustion)
   - Multi-turn functional scenarios (simulated conversations)
3. Include mock LLM gateway for deterministic test runs
4. Return: test files created, coverage gaps intentionally left

**Fallback:** If Agent-B cannot identify test gaps, use checklist: greet, help, ask, provide, status check, correction, unrecognized intent, error handling, session management, database errors.

### Phase 3: Test Execution & Loop

Run `python -m pytest tests/ -v`. For each outcome:

**All pass → DONE.** Commit with descriptive message, update todo.

**Some fail → enter the arbitration loop:**

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  1. Agent-A reads the failing test              │
│  2. Agent-B reads the failing test              │
│  3. Both agents analyze the root cause:         │
│     - Is the test wrong? (bad expectation)       │
│     - Is the code wrong? (bug / missing logic)   │
│  4. If they AGREE on root cause:                │
│     → Wrong agent fixes it                      │
│     → Loop back to test execution               │
│  5. If they DISAGREE:                           │
│     → Agent-C (Judge) reviews both arguments    │
│     → Judge rules: test is wrong OR code is wrong│
│     → Wrong agent fixes it                      │
│     → Loop back to test execution               │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Phase 4: Agent-C (Judge) Protocol

When Agent-A and Agent-B cannot agree on root cause, Agent-C (Judge) intervenes:

1. Read the failing test, the implementation code, and the spec
2. Review both agents' arguments
3. Apply these heuristics:
   - Spec wins over implementation preference
   - Framework conventions win over stylistic choice
   - Test should match actual behavior, not ideal behavior
   - If ambiguous, default to: fix the code to make the test pass, then review if the test expectation is too strict
4. Issue ruling: "Fix X in file Y: line Z" with specific instruction
5. The losing agent implements the fix immediately

### Phase 5: Self-Managing Task Queue

During the loop, the agents may discover new issues. These are automatically added to the todo list:

- Agent-A finds a pre-existing bug → add "fix: {bug}" task
- Agent-B finds an untested code path → add "test: {path}" task
- Agent-C identifies a spec ambiguity → add "clarify: {ambiguity}" task
- Tests reveal a missing feature → add "feat: {feature}" task

Each new task inherits the priority of its discoverer (Agent-A: high for bugs, Agent-B: medium for edge cases, Agent-C: high for blocking issues).

The loop continues until the todo list is empty AND all tests pass.

## Rules

- Never skip the test execution step — always run `pytest` after any code or test change
- Never let Agent-A and Agent-B modify code simultaneously — sequential only
- Agent-C must cite the spec or framework convention when issuing a ruling
- All agents use the same shared codebase — no branches, no merge conflicts
- The loop may self-terminate after 5 arbitration rounds if no progress — escalate to human
- Every commit message must include the number of passing tests

## Sources

- 3-agent architecture: confidence high — derived from the 3-agent TDD loop demonstrated in mfangdai-agent development (commit history: 5b7d929, 53c778b, f11301b)
- Arbitration heuristics: confidence high — based on spec-over-preference, spec-first, framework conventions from VISION.md
- Self-managing todo: confidence high — todo list dynamically extended during the mfangdai-agent loop (P0/P1 test gaps added mid-cycle)
- Loop interval: confidence medium — 30 minutes default based on typical LLM response time for agent analysis
