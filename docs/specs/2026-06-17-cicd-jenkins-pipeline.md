# CI/CD Pipeline (Jenkins)

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Jenkins declarative pipeline, eval stages, environment promotion, rollback strategy.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial CI/CD pipeline spec: Jenkins stages, mock/real LLM eval, environment promotion, rollback |
| 2026-06-17 | 0.2.0 | Strip all Groovy implementation code; replace with YAML pipeline stage schemas; add declarative deploy descriptions; add Implementation Options comparison (Jenkins, GitHub Actions, GitLab CI) |
| 2026-06-18 | 0.2.1 | Actually remove remaining Groovy code in §7.3 (was missed in v0.2.0); replace with declarative YAML pipeline description |
| 2026-06-24 | 0.3.0 | Add Hetzner Terraform infrastructure, GitHub webhook integration, Tier 1/2/3 testing stages in Jenkinsfile |

---

## 1. Role

The CI/CD pipeline automates validation, evaluation, and deployment of the deterministic workflow framework. Every change flows through **lint → eval → build → deploy** with gated promotion between environments.

```
Git Push / PR
    │
    ▼
┌───────────────────────────────────────────────────────────┐
│                    JENKINS PIPELINE                        │
├─────────┬─────────┬─────────┬─────────┬─────────┬────────┤
│  Lint   │  Eval   │  Eval   │  Build  │  Deploy │ Deploy │
│         │ (Mock   │ (Real   │         │   dev   │  e2e   │
│         │  LLM)   │  LLM)   │         │         │        │
│  All    │  All    │  PR     │  On     │  Auto   │ Manual │
│  pushes │  pushes │  only   │  merge  │  on     │ trigger│
│         │         │         │         │  merge  │        │
└─────────┴─────────┴─────────┴─────────┴─────────┴────────┘
                                                      │
                                                      ▼
                                                ┌─────────┐
                                                │ Deploy  │
                                                │  prod   │
                                                │ Manual  │
                                                │ + approv│
                                                └─────────┘
```

### 1.1 What the Pipeline Covers

- ✅ **Linting** — code style, YAML schema validation, type checking
- ✅ **Evaluation** — mock LLM (fast, all pushes) + real LLM (PR only)
- ✅ **Building** — Docker image build and push to registry
- ✅ **Deployment** — dev, e2e, prod with gated promotion
- ✅ **Rollback** — revert to previous LangGraph checkpoint

### 1.2 What the Pipeline Does NOT Cover

- ❌ **Infrastructure provisioning** — Kubernetes, DNS, networking (handled by Terraform/IaC)
- ❌ **Database migrations** — schema changes to checkpoint store (handled by separate migration pipeline)
- ❌ **Secret rotation** — API key cycling (handled by Vault / cloud secret manager)
- ❌ **Performance testing** — load testing, stress testing (future addition)

---

## 2. Pipeline Stages

### 2.1 Stage Overview

| Stage | Trigger | LLM Mode | Runtime | Gates |
|-------|---------|----------|---------|-------|
| **Lint** | Every push | N/A | ~30s | Must pass |
| **Eval (Mock LLM)** | Every push | Mock (offline) | ~2 min | Must pass |
| **Eval (Real LLM)** | PR only | Real (OpenAI/Anthropic) | ~10 min | Must pass before merge |
| **Build** | Merge to main | N/A | ~3 min | Must pass |
| **Deploy dev** | Merge to main | Real | ~2 min | Auto |
| **Deploy e2e** | Manual trigger | Real | ~2 min | Manual gate |
| **Deploy prod** | Manual trigger | Real | ~2 min | Manual + approval |

### 2.2 Stage Details

#### Stage 1: Lint

```yaml
# Pipeline stage configuration
stages:
  lint:
    name: "Lint"
    trigger: every_push
    parallel: true
    steps:
      - name: "Python lint (ruff)"
        command: "ruff check ."
        timeout_minutes: 2
      
      - name: "YAML validation"
        command: "python scripts/validate_workflows.py"
        description: "Validates all .yaml workflow definitions against schemas"
        timeout_minutes: 2
      
      - name: "Type check (mypy)"
        command: "mypy src/ --strict"
        timeout_minutes: 3
    failure_action: stop_pipeline
```

#### Stage 2: Eval (Mock LLM)

Runs evals against all workflows using mock LLM responses. Fast, deterministic, no API cost.

```yaml
  eval_mock:
    name: "Eval (Mock LLM)"
    trigger: every_push
    parallel: false
    environment:
      ENV: e2e
      LLM_MODE: mock                # offline mock — no LLM API calls
    steps:
      - name: "Run eval suite"
        command: >
          python -m pytest tests/evals/
          --eval-dataset=mortgage-lead-eval
          --mock-llm
          --junitxml=results/eval-mock-results.xml
        timeout_minutes: 5
    
    post:
      - name: "Archive eval results"
        archive:
          artifacts: "results/eval-mock-results.xml"
    
    failure_action: stop_pipeline
```

#### Stage 3: Eval (Real LLM)

Runs evals against the changed workflow using real LLM calls. Triggered only on PR, not on every push (cost + latency).

```yaml
  eval_real:
    name: "Eval (Real LLM)"
    trigger: pull_request            # PR only — skip on regular pushes
    parallel: false
    environment:
      ENV: e2e
      LLM_MODE: real
      OPENAI_API_KEY: "${OPENAI_API_KEY_CREDENTIAL}"
      LANGSMITH_TRACING: "true"
    steps:
      - name: "Detect changed workflows"
        command: |
          CHANGED=$(git diff --name-only origin/main...HEAD -- 'workflows/*.yaml')
          echo "CHANGED_WORKFLOWS=${CHANGED}" > changed_workflows.env
      
      - name: "Run eval on changed workflows"
        command: >
          python -m pytest tests/evals/
          --eval-dataset=mortgage-lead-eval
          --real-llm
          --changed-workflows="${CHANGED_WORKFLOWS}"
          --junitxml=results/eval-real-results.xml
          --langsmith-project="ci-evals"
        timeout_minutes: 15
    
    post:
      always:
        - name: "Archive eval results"
          archive:
            artifacts: "results/eval-real-results.xml"
        - name: "Publish eval report"
          publish_junit: "results/eval-real-results.xml"
    
    failure_action: stop_pipeline
    gates:
      - metric: "intent_accuracy"
        threshold: ">= 0.95"
      - metric: "goal_check_pass_rate"
        threshold: ">= 0.95"
      - metric: "schema_violation_rate"
        threshold: "<= 0.05"
```

#### Stage 4: Build

```yaml
  build:
    name: "Build Docker Image"
    trigger: merge_to_main
    environment:
      DOCKER_REGISTRY: "${DOCKER_REGISTRY_URL}"
    steps:
      - name: "Build Docker image"
        command: |
          docker build \
            --tag "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
            --tag "${DOCKER_REGISTRY}/deterministic-workflow:latest" \
            --build-arg ENV=prod \
            .
        timeout_minutes: 5
      
      - name: "Push to registry"
        command: |
          docker push "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
          docker push "${DOCKER_REGISTRY}/deterministic-workflow:latest"
        timeout_minutes: 5
    
    failure_action: stop_pipeline
```

#### Stage 5-7: Deploy (dev → e2e → prod)

```yaml
  deploy_dev:
    name: "Deploy to dev"
    trigger: merge_to_main
    environment: dev
    steps:
      - deploy:
          type: kubernetes
          namespace: dev
          deployment: deterministic-workflow-dev
          container: workflow
          image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
          timeout_minutes: 3
      - smoke_test:
          environment: dev
          endpoint: "https://dev-api.example.com"
          timeout_minutes: 2

  deploy_e2e:
    name: "Deploy to e2e"
    trigger: manual
    environment: e2e
    gates:
      - type: manual_approval
        message: "Deploy build ${BUILD_NUMBER} to E2E?"
    steps:
      - deploy:
          type: kubernetes
          namespace: e2e
          deployment: deterministic-workflow-e2e
          container: workflow
          image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
      - smoke_test:
          environment: e2e
          endpoint: "https://e2e-api.example.com"
      - integration_test:
          environment: e2e
          suite: "tests/integration/"
          report: "results/integration-results.xml"
          timeout_minutes: 10

  deploy_prod:
    name: "Deploy to prod"
    trigger: manual
    environment: prod
    gates:
      - type: manual_approval
        message: "Deploy build ${BUILD_NUMBER} to production?"
        approvers:
          - release-managers
    steps:
      - deploy_canary:
          type: kubernetes
          namespace: prod
          deployment: deterministic-workflow-prod-canary
          container: workflow
          image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
      - monitor_canary:
          duration_minutes: 10
          error_rate_threshold: 5
          latency_p95_threshold_ms: 5000
          auto_rollback: true
      - deploy_full:
          type: kubernetes
          namespace: prod
          deployment: deterministic-workflow-prod
          container: workflow
          image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
      - smoke_test:
          environment: prod
          endpoint: "https://api.example.com"
```

---

## 3. Pipeline Stage Schema (YAML)

The pipeline is defined as a YAML schema — not as runnable Groovy. Each CI/CD platform consumes this schema and translates it to its native pipeline definition format.

```yaml
# pipeline.yaml — Pipeline Stage Schema (declarative, not implementation code)
pipeline:
  name: "deterministic-workflow-ci-cd"
  version: "0.2.0"

  agent:
    type: container
    image: "python:3.12"
    resources:
      cpu: "2"
      memory: "4Gi"

  environment:
    ENV: ci
    DOCKER_REGISTRY:
      from: credential
      id: "docker-registry"
    OPENAI_API_KEY:
      from: credential
      id: "openai-api-key"
    LANGSMITH_API_KEY:
      from: credential
      id: "langsmith-api-key"

  options:
    timeout_minutes: 60
    build_retention:
      keep_count: 30
    timestamps: true

  triggers:
    - type: push
      branches: ["**"]
    - type: pull_request
      branches: ["main"]
    - type: merge_to_main
      branches: ["main"]
      condition: "not pull_request"

  stages:
    lint:
      name: "Lint"
      trigger: push_or_pr
      agent: container
      parallel:
        - name: "Python lint (ruff)"
          run: "ruff check ."
          timeout_minutes: 2
        - name: "YAML validation"
          run: "python scripts/validate_workflows.py"
          timeout_minutes: 2
        - name: "Type check (mypy)"
          run: "mypy src/ --strict"
          timeout_minutes: 3
      on_failure: stop_pipeline

    eval_mock:
      name: "Eval (Mock LLM)"
      trigger: push_or_pr
      env:
        LLM_MODE: mock
      steps:
        - name: "Install dev dependencies"
          run: "pip install -r requirements-dev.txt"
        - name: "Run mock eval suite"
          run: >
            python -m pytest tests/evals/
            --eval-dataset=mortgage-lead-eval
            --mock-llm
            --junitxml=results/eval-mock-results.xml
          timeout_minutes: 5
      post:
        always:
          - publish_junit: "results/eval-mock-results.xml"
      on_failure: stop_pipeline

    eval_real:
      name: "Eval (Real LLM)"
      trigger: pull_request_only
      env:
        LLM_MODE: real
        OPENAI_API_KEY:
          from: credential
          id: "openai-api-key"
        LANGSMITH_TRACING: "true"
      steps:
        - name: "Detect changed workflows"
          detect_changes:
            pattern: "workflows/*.yaml"
            output_variable: CHANGED_WORKFLOWS
        - name: "Run eval on changed workflows"
          run: >
            python -m pytest tests/evals/
            --eval-dataset=mortgage-lead-eval
            --real-llm
            --changed-workflows="${CHANGED_WORKFLOWS}"
            --junitxml=results/eval-real-results.xml
            --langsmith-project="ci-evals"
          timeout_minutes: 15
      post:
        always:
          - archive_artifacts: "results/eval-real-results.xml"
          - publish_junit: "results/eval-real-results.xml"
      gates:
        - metric: "intent_accuracy"
          threshold: ">= 0.95"
        - metric: "goal_check_pass_rate"
          threshold: ">= 0.95"
        - metric: "schema_violation_rate"
          threshold: "<= 0.05"
      on_failure: stop_pipeline

    build:
      name: "Build Docker Image"
      trigger: merge_to_main
      env:
        DOCKER_REGISTRY:
          from: credential
          id: "docker-registry"
      steps:
        - name: "Build Docker image"
          build_image:
            tags:
              - "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
              - "${DOCKER_REGISTRY}/deterministic-workflow:latest"
            build_args:
              ENV: prod
          timeout_minutes: 5
        - name: "Push to registry"
          push_image:
            tags:
              - "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
              - "${DOCKER_REGISTRY}/deterministic-workflow:latest"
          timeout_minutes: 5
      on_failure: stop_pipeline

    deploy_dev:
      name: "Deploy to Dev"
      trigger: merge_to_main
      env: dev
      steps:
        - name: "Deploy to dev"
          deploy:
            type: kubernetes
            environment: dev
            namespace: dev
            deployment: deterministic-workflow-dev
            container: workflow
            image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
          timeout_minutes: 3
        - name: "Smoke test"
          run: "python scripts/smoke_test.py --env=dev"
          timeout_minutes: 2

    deploy_e2e:
      name: "Deploy to E2E"
      trigger: manual
      env: e2e
      steps:
        - name: "Deploy to e2e"
          deploy:
            type: kubernetes
            environment: e2e
            namespace: e2e
            deployment: deterministic-workflow-e2e
            container: workflow
            image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
        - name: "E2E smoke test"
          run: "python scripts/smoke_test.py --env=e2e"
        - name: "Run integration tests"
          run: >
            python -m pytest tests/integration/
            --env=e2e
            --junitxml=results/integration-results.xml
          timeout_minutes: 10
      gates:
        - type: manual_approval
          message: "Deploy build ${BUILD_NUMBER} to E2E?"

    deploy_prod:
      name: "Deploy to Production"
      trigger: manual
      env: prod
      gates:
        - type: manual_approval
          message: "Deploy build ${BUILD_NUMBER} to production?"
          approvers: [release-managers]
      steps:
        - name: "Deploy to prod (canary)"
          deploy:
            type: kubernetes
            environment: prod
            namespace: prod
            deployment: deterministic-workflow-prod-canary
            container: workflow
            image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
        - name: "Canary monitoring"
          monitor:
            duration_minutes: 10
            error_rate_threshold: 5
            latency_threshold_p95: 5
            auto_rollback: true
        - name: "Full prod rollout"
          deploy:
            type: kubernetes
            environment: prod
            namespace: prod
            deployment: deterministic-workflow-prod
            container: workflow
            image: "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
        - name: "Post-deploy smoke test"
          run: "python scripts/smoke_test.py --env=prod"

  post:
    always:
      - clean_workspace: true
    on_failure:
      - notify:
          channel: "#ci-alerts"
          status: danger
          message: "Pipeline failed: ${JOB_NAME} #${BUILD_NUMBER}"
    on_success:
      - notify:
          channel: "#ci-alerts"
          status: good
          message: "Pipeline succeeded: ${JOB_NAME} #${BUILD_NUMBER}"
```

---

## 4. Evaluation Stage Details

### 4.1 Eval Suites

```yaml
# evals-create test configuration
eval:
  suites:
    mortgage_lead_submission:
      dataset: mortgage-lead-eval
      test_cases:
        - name: "happy_path_full_quote"
          input: "I need mortgage lead for my 3-bedroom house"
          expected:
            intent: submit_lead
            completion_state: completed
          assert:
            - extracted.loan_purpose is not null
            - extracted.loan_amount is not null
            - response_data.goal_met == true
        
        - name: "incomplete_info_graceful"
          input: "I want a mortgage"
          expected:
            intent: submit_lead
            completion_state: active
          assert:
            - extracted.loan_purpose is null
            - response_data.goal_met == false
            - response_data.gap_analysis is not null
        
        - name: "intent_misclassification_resilience"
          input: "Tell me about your mortgage products compared to competitors"
          expected:
            intent: general_inquiry
          assert:
            - intent != submit_lead

  eval_gates:
    global:
      intent_accuracy: ">= 0.95"
      goal_check_pass_rate: ">= 0.95"
      schema_violation_rate: "<= 0.05"
    
    per_workflow:
      mortgage_lead_submission:
        extraction_f1: ">= 0.95"
        routing_accuracy: ">= 0.95"
```

### 4.2 Mock LLM Strategy

```yaml
# Mock LLM for fast eval (no API cost, deterministic)
eval:
  mock_llm:
    strategy: pre_recorded_responses      # pre_recorded_responses | rule_based
    
    pre_recorded_responses:
      # Responses recorded from real LLM runs and checked into the repo
      source: tests/fixtures/mock_responses/
      format: jsonl
    
    # Alternative: rule-based mock that returns fixed JSON based on input
    # strategy: rule_based
    # rules:
    #   - match: "mortgage.*house"
    #     response: { "intent": "submit_lead", "confidence": 0.95 }
```

### 4.3 Real LLM Eval (PR Only)

```yaml
eval:
  real_llm:
    trigger: pull_request                  # PR only
    provider: openai                       # which LLM to use for evals
    model: gpt-4o
    cost_estimate:
      per_run: "$2-5 USD"
      monthly_budget: "$200 USD"
    
    parallelism: 4                         # concurrent eval runs
    retry_on_flaky: true                   # retry flaky LLM runs
    max_retries_per_case: 2
    
    langsmith:
      tracing: true
      project: "ci-evals"
      # Each eval run becomes a LangSmith experiment
```

---

## 5. Real Project Example: mortgage_lead

### 5.1 Overview

**mortgage_lead** is a mortgage lead submission system. The chat version routes users through a mortgage lead submission workflow: collect lead purpose → gather financial profile → run lead scoring → present rate options.

```
User: "I'm looking for the best rate on a $500K mortgage"
    │
    ▼
Layer 1 (Extract): { intent: "submit_mortgage_lead", loan_amount: 500000 }
Layer 2 (Route): mortgage_lead_submission workflow → collect_lead_purpose phase
Layer 3 (Respond): "I'd be happy to help you find competitive rates for $500K. First, let me ask..."
```

### 5.2 Backend Integration

The framework's chat version calls mortgage_lead's backend API for rate calculations:

```yaml
# workflow integration configuration
workflows:
  mortgage_lead_submission:
    backend:
      api: mortgage_lead
      base_url: "https://mortgage-lead-api.${ENV}.example.com"
      auth:
        type: api_key
        key: "${MORTGAGE_LEAD_API_KEY}"
      endpoints:
        submit_lead_application: "POST /v1/lead-applications"
        get_rate:                   "GET  /v1/rate"
        run_lead_scoring:           "POST /v1/lead-scoring"
      timeout_seconds: 10
      retry:
        max_attempts: 2
        backoff: exponential
      circuit_breaker:
        failure_threshold: 5
        recovery_timeout_seconds: 30
```

### 5.3 Eval Dataset for mortgage_lead

```yaml
eval:
  suites:
    mortgage_lead_submission:
      dataset: mortgage-lead-eval
      test_cases:
        - name: "happy_path_mortgage_lead_submission"
          input: "I'm looking for a mortgage for a $500,000 home"
          expected:
            intent: submit_mortgage_lead
          assert:
            - extracted.loan_amount == 500000
            - response_data.offer is not null
        
        - name: "high_lead_score"
          input: "Can I get a mortgage with a credit score of 580?"
          expected:
            intent: submit_mortgage_lead
          assert:
            - extracted.credit_score == 580
            - response_data.outcome == "declined"
            - response_data.reason contains "credit"

        - name: "high_value_lead_routing"
          input: "Need a mortgage for a $1.2M property in California"
          expected:
            intent: submit_mortgage_lead
          assert:
            - extracted.loan_amount == 1200000
            - routing_decision.route == "jumbo_loan_specialist"

        - name: "first_time_buyer_programs"
          input: "I'm a first-time homebuyer, what special programs do you have?"
          expected:
            intent: first_time_buyer_inquiry
          assert:
            - extracted.first_time_buyer == true
```

---

## 6. Environment Promotion Strategy

### 6.1 Promotion Flow

```
dev (auto on merge)
  │
  │  Manual trigger by developer
  ▼
e2e (manual trigger)
  │
  │  Integration tests pass
  │  Manual trigger + approval by release-managers
  ▼
prod (manual trigger + approval)
```

### 6.2 Promotion Rules

```yaml
pipeline:
  promotion:
    dev_to_e2e:
      trigger: manual
      requires:
        - dev_smoke_test_passed
        - docker_image_built
      approver: any_developer
    
    e2e_to_prod:
      trigger: manual
      requires:
        - e2e_smoke_test_passed
        - integration_tests_passed
        - eval_mock_passed
        - eval_real_passed
      approver: release_managers      # requires approval from release-managers group
      canary:
        enabled: true
        duration_minutes: 10
        error_rate_threshold: 5       # max 5% error rate in canary
        auto_rollback: true           # auto-rollback if canary fails
    
    deployment_strategy:
      method: rolling_update          # rolling_update | blue_green | canary
      max_surge: 1
      max_unavailable: 0
```

### 6.3 Static Analysis Gates per Environment

```yaml
pipeline:
  gates:
    dev:
      - lint_passed
      - eval_mock_passed
    
    e2e:
      - lint_passed
      - eval_mock_passed
      - eval_real_passed
      - integration_tests_passed
    
    prod:
      - all_above
      - canary_passed
      - approval_granted
```

---

## 7. Rollback Strategy

### 7.1 LangGraph Checkpoint Rollback

```yaml
# Rollback restores conversations to the last known-good checkpoint
rollback:
  strategy: checkpoint_revert
  
  checkpoint:
    # Before each deploy, the pipeline snapshots the LangGraph checkpoint store
    pre_deploy_snapshot:
      enabled: true
      label: "pre-deploy-${BUILD_NUMBER}"
    
    # Rollback restores from the snapshot
    restore:
      command: "python scripts/rollback_checkpoint.py --label=pre-deploy-${BUILD_NUMBER}"
      # This restores all active conversations to their last checkpoint
      # before the faulty deployment.
    
    # Conversations created during the faulty deployment:
    # - If no messages were sent → deleted (no data loss)
    # - If messages were sent → checkpoint available, can be restored
```

### 7.2 Rollback Procedure

```yaml
rollback:
  steps:
    - name: "Trigger rollback"
      type: manual
      jenkins_job: "rollback-deterministic-workflow"
    
    - name: "Restore previous image"
      command: |
        kubectl set image deployment/deterministic-workflow-prod \
          workflow="${DOCKER_REGISTRY}/deterministic-workflow:${PREVIOUS_BUILD_NUMBER}" \
          --namespace=prod
    
    - name: "Restore checkpoints"
      command: |
        python scripts/rollback_checkpoint.py \
          --label="pre-deploy-${PREVIOUS_BUILD_NUMBER}" \
          --env=prod
    
    - name: "Verify restored state"
      command: |
        python scripts/verify_checkpoint_integrity.py \
          --env=prod \
          --label="pre-deploy-${PREVIOUS_BUILD_NUMBER}"
    
    - name: "Notify on-call"
      notify:
        slack_channel: "#oncall"
        message: "Rollback complete — restored to build ${PREVIOUS_BUILD_NUMBER}"

  rollback_decision:
    # Auto-trigger rollback if:
    auto_triggers:
      - error_rate > 10% for 5 minutes
      - goal_check_422_rate > 30% for 5 minutes
      - critical_alert_fired (P1)
    
    # Manual rollback available at any time
    manual_trigger:
      jenkins_job: "rollback-deterministic-workflow"
      parameters:
        - target_environment
        - target_build_number
        - reason
```

### 7.3 Rollback Pipeline (Declarative)

The rollback pipeline restores a previous deployment and checkpoints to a known-good state:

```yaml
# rollback pipeline — declarative stages
rollback_pipeline:
  trigger: manual | auto
  auto_triggers:
    - error_rate > 10% for 5 minutes
    - goal_check_422_rate > 30% for 5 minutes
    - critical_alert_fired
  stages:
    - name: verify_rollback_target
      action: resolve_previous_build_number
      input:
        target_build: "previous" | <build_number>
    - name: deploy_previous_build
      action: set_container_image
      input:
        build: "{{rollback.build_number}}"
    - name: restore_checkpoints
      action: rollback_checkpoint
      input:
        label: "pre-deploy-{{rollback.build_number}}"
    - name: verify
      action: run_smoke_tests
```

---

## 8. Integration with Other Framework Components

### 8.1 Eval Metrics Feed into Observability

```yaml
# Eval results from CI/CD are pushed to the same Prometheus/Grafana stack
pipeline:
  eval_metrics_export:
    enabled: true
    pushgateway_url: "${PUSHGATEWAY_URL}"
    metrics:
      - eval_intent_accuracy
      - eval_extraction_f1
      - eval_goal_check_pass_rate
      - eval_schema_violation_rate
    labels:
      build_number: "${BUILD_NUMBER}"
      workflow: "{workflow_id}"
      commit_sha: "${GIT_COMMIT}"
```

### 8.2 Notifications via Observability Alerts

```yaml
pipeline:
  notifications:
    slack:
      channel: "#ci-alerts"
      events:
        - build_started
        - build_succeeded
        - build_failed
        - deploy_started
        - deploy_succeeded
        - deploy_failed
        - require_approval
        - rollback_started
        - rollback_completed
```

---

## 9. Open Questions

| # | Question | Impact |
|---|----------|--------|
| 1 | Should eval datasets be stored in the same repository (versioned with workflows) or in a separate eval-data repository? | Auditability vs repo bloat |
| 2 | How should the pipeline handle schema changes to `agentState` that break checkpoint deserialization during rollback? | Rollback safety |
| 3 | Should there be a staging environment between e2e and prod, or is e2e sufficient given canary deployments? | Environment proliferation |
| 4 | Should eval gates be configurable per workflow (mortgage_rate_quote might need different accuracy thresholds than mortgage_lead_submission)? | Flexibility vs consistency |
| 5 | How should the pipeline handle LLM provider outages during real LLM eval? Should it skip the eval stage or fail the build? | CI reliability |
| 6 | Should deployment promote the Docker image tag (e.g., `dev-v1.2.3` → `e2e-v1.2.3` → `prod-v1.2.3`) or use the same tag across environments? | Rollback clarity vs tag proliferation |

---

## References

- [High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md) — §2 Core Architecture, §4.1 Framework Principles
- [Environment Config](./2026-06-17-environment-config.md) — dev, e2e, prod environment settings
- [Observability & Monitoring](./2026-06-17-observability-monitoring.md) — Metrics, alerts, Grafana dashboards
- [LLM Gateway](./2026-06-17-llm-gateway.md) — Schema validation (tested in eval stages)
- [Response Generation](./2026-06-17-response-generation-layer-design.md) — Goal check 422 behavior (eval gate)
- [Extraction Layer](./2026-06-17-extraction-layer-design.md) — Entity extraction (eval F1 metric)
- [Intent Classification](./2026-06-16-intent-classification-design.md) — Intent accuracy (eval gate)
- [Three-Tier Testing Methodology](./2026-06-19-three-tier-agent-testing-methodology.md) — Tier 1/2/3 test stages

---

## 10. Example Infrastructure

See [docs/examples/cicd/hetzner-jenkins.md](../../examples/cicd/hetzner-jenkins.md) for a concrete Hetzner + Jenkins reference implementation including Terraform, cloud-init, and a Jenkinsfile with Tier 1/2/3 test stages + GitHub webhook integration. Copy and adapt for your project.
- [Conversation Lifecycle](./2026-06-17-conversation-lifecycle.md) — Checkpoint rollback integration
- [Jenkins Declarative Pipeline](https://www.jenkins.io/doc/book/pipeline/syntax/)
- [Jenkins Kubernetes Plugin](https://plugins.jenkins.io/kubernetes/)
