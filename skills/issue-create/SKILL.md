---
name: issue-create
description: "Creates well-structured GitHub issues from deterministic workflow design discussions. Use when turning spec decisions or architecture discussions into actionable implementation tickets."
user-invocable: true
---

# Issue Create — Deterministic Workflow Framework

## When to Use

When the user or AI has finished discussing a design decision, identified a gap, or completed a spec section — and that work needs to become an implementable ticket.

## Process

### Step 1: Identify Scope

Read the current conversation context. Determine which spec document(s) the issue relates to:

| Spec | Area |
|------|------|
| `hl-design` | Overall architecture, framework principles, cross-cutting |
| `intent-classification` | Layer 1 intent detection |
| `state-machine` | FSM design, transitions, guards |
| `extraction-layer` | Extract/Validate/Transform pipeline |
| `domain-model` | Entity/State/Transition schemas |
| `routing-execution` | Layer 2 executors, decision nodes, permissions |
| `response-generation` | Layer 3 goal setting, response modes, PII |
| `llm-gateway` | Mandatory structured output interface |
| `tool-ecosystem` | LangFlow, LangSmith, rule engines, MCP |
| `environment-config` | dev/e2e/prod configuration |
| `auth-token-verification` | OAuth, token verification, identity |

### Step 2: Classify Issue Type

| Type | Template | When |
|------|----------|------|
| **spec-change** | Modify existing spec | A design decision changes something already written |
| **spec-new** | Write new spec section | A gap is identified that needs new spec content |
| **impl-plan** | Implementation planning ticket | Spec is complete, ready to plan code |
| **open-question** | Research/debate ticket | An open question needs resolution before proceeding |

### Step 3: Generate Issue

Ask the user to confirm, then use `github create-issue` with this template:

```markdown
## Context
<!-- Which spec, which section, what was discussed -->

## Current State
<!-- What the spec currently says, or what gap exists -->

## Proposed Change / Task
<!-- What needs to happen -->

## Acceptance Criteria
- [ ] Spec updated with <specific change>
- [ ] Cross-references validated
- [ ] Changelog entry added
- [ ] Chinese translation updated (if applicable)

## Blocks
<!-- What this issue blocks or is blocked by -->
```

### Step 4: Tag and Assign

- Label: `spec-change` | `spec-new` | `impl-plan` | `open-question`
- Assignee: ask user
- Milestone: ask user or leave empty
-

## Rules

- One issue = one change. Don't bundle multiple unrelated changes.
- Always link to the spec file in the issue body.
- Include the current spec version from the changelog in the Context section.
- For `spec-change` issues, include the exact text to change (old → new) when possible.
