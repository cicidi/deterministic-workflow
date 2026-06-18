---
name: evals-create
description: "Generates goal definitions, eval test cases, and quality check scenarios for deterministic workflows. Use when a workflow is defined and needs comprehensive evaluation coverage."
user-invocable: true
---

# Evals Create — Deterministic Workflow Framework

## When to Use

After a domain model and workflow configuration are defined. The developer needs:
- **Goal definitions** for `agentState.goal` (Response Generation spec §2)
- **Goal check eval cases** for the `goalChecker` node (§4)
- **Response eval cases** for prompt guidance accuracy (Response Generation spec §3.3 Option A)
- **Decision eval cases** for LLM-based decision nodes (Routing & Execution spec §3.4)
- **Intent classification eval cases** (Intent Classification spec)

## Process

### Step 1: Load Workflow Context

Read the product's domain model YAML and workflow YAML. Understand:
- All entities and their fields
- All states and transitions
- Which nodes use LLM

### Step 2: Generate Goal Definitions

For EACH workflow entry point, generate a goal definition (see Response Generation spec §2.2):

```yaml
goal_definitions:
  get_quote:
    summary: "User wants a home insurance quote"
    intent: "get_quote"
    expected_entities: ["property_info", "coverage_needs"]
    expected_outputs: ["risk_assessment", "premium_calculation", "quote"]
    success_criteria:
      - "property_type is collected and valid"
      - "address is collected"
      - "coverage_type is selected"
      - "annual_premium is calculated"
      - "quote is presented to user"
    priority: "normal"

  file_claim:
    summary: "User wants to file an insurance claim"
    intent: "file_claim"
    expected_entities: ["claim_details"]
    expected_outputs: ["claim_validation", "damage_assessment", "payout"]
    success_criteria:
      - "incident_type is collected"
      - "incident_date is valid"
      - "estimated_loss is provided"
      - "claim is validated and assessed"
    priority: "high"
```

### Step 3: Generate Goal Check Eval Cases

For EACH goal definition, create eval cases that test the `goalChecker` node:

```yaml
goal_check_evals:
  - goal: get_quote
    input_state:
      collectedFields:
        property_type: "house"
        address: "123 Main St"
        building_age: 15
        coverage_type: "building_only"
        building_coverage: 500000
      outcomes:
        annual_premium: 3200
    expected:
      goal_met: true
      completion_percentage: 0.9
      unsatisfied_criteria: ["floor_area is optional, not collected"]

  - goal: get_quote
    input_state:
      collectedFields:
        property_type: "house"
        # address is MISSING
        building_age: 15
    expected:
      goal_met: false
      completion_percentage: 0.3
      unsatisfied_criteria: ["address is collected", "coverage_type is selected", "annual_premium is calculated"]

  - goal: file_claim
    input_state:
      collectedFields:
        incident_type: "water_damage"
        incident_date: "2026-06-15"
        estimated_loss: 50000
      outcomes:
        claim_validated: true
    expected:
      goal_met: true
      completion_percentage: 1.0
```

### Step 4: Generate Response Eval Cases

For each response-generating node (using `pure_message` strategy), create eval cases:

```yaml
response_evals:
  - node: generate_quote_response
    agent_state:
      phase: "present_quote"
      collectedFields:
        property_type: "house"
        address: "123 Main St"
      outcomes:
        annual_premium: 3200
        monthly_premium: 267
        risk_score: 35
    expected_themes:
      - "annual premium ¥3,200"
      - "monthly premium ¥267"
      - "risk score 35/100"
      - "next step suggestion"    # prompt must guide to next action
    forbidden_themes:
      - "fabricated discount"
      - "unknown coverage"
    tone_check: "professional"

  - node: goal_setter
    user_input: "I want a quote for my 5-year-old apartment in Beijing"
    intent: "get_quote"
    expected_themes:
      - "get_quote"
      - "property_info"
      - "coverage_needs"
    check: "expected_entities contains 'property_info'"
```

### Step 5: Generate Intent Classification Eval Cases

```yaml
intent_evals:
  - input: "I want to get a quote for my house"
    agent_state:
      phase: "idle"
    expected:
      intent: "get_quote"
      confidence: { min: 0.7 }

  - input: "what does basic plan cover"
    agent_state:
      phase: "collect_property_info"     # mid-workflow question
    expected:
      intent: "ask_question"              # NOT "get_quote"

  - input: "yes"
    agent_state:
      phase: "confirm_coverage"
    expected:
      intent: "confirm"                   # context-aware

  - input: "never mind, cancel this"
    agent_state:
      phase: "collect_property_info"
    expected:
      intent: "decline"
```

### Step 6: Generate Decision Eval Cases (if applicable)

Only for workflows using LLM-based decision nodes:

```yaml
decision_evals:
  - node: risk_triage
    input:
      risk_score: 25
      property_type: "house"
    expected:
      route: "auto_approve"

  - node: risk_triage
    input:
      risk_score: 85
      property_type: "villa"
    expected:
      route: "manual_review"

  # Safety-critical: must NEVER route high risk to auto_approve
  - node: risk_triage
    input:
      risk_score: 95
      property_type: "house"
    expected:
      route: "manual_review"  # explicitly NOT "auto_approve"
```

### Step 7: Generate Coverage Report

Output a summary:

```markdown
## Eval Coverage Summary

| Category | Count | Coverage |
|----------|-------|----------|
| Goal definitions | 3 | 3/3 workflows covered |
| Goal check evals | 12 | 3 happy paths + 3 partial + 3 empty + 3 edge cases |
| Response evals | 8 | All response nodes covered |
| Intent evals | 15 | 5 standard intents + 5 edge cases + 5 context-aware |
| Decision evals | 5 | 2 low risk + 2 high risk + 1 boundary |

**Safety-critical cases**: 3 (high risk → manual_review must be enforced)
**Edge cases covered**: 8 (empty input, ambiguous phrases, code-switching)
```

## Rules

- Every eval case MUST include both `expected` and `forbidden` criteria where applicable.
- For safety-critical decisions (e.g., high risk → NEVER auto_approve), create explicit "must NOT" test cases.
- Minimum coverage: at least 1 happy path + 1 failure path per workflow.
- Goal completion evals should cover: all required fields present (happy), some fields missing (partial), all fields missing (empty).
- Response evals must check that the prompt guides the LLM to suggest the next step.
- Output format: YAML ready to be loaded by the framework's eval runner.
