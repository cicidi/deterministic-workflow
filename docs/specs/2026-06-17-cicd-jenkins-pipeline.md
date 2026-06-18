# CI/CD Pipeline (Jenkins)

> Part of [Deterministic Workflow Framework — High-Level Design](./2026-06-16-deterministic-workflow-framework-design.md)
> Covers: Jenkins declarative pipeline, eval stages, environment promotion, rollback strategy.

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | Initial CI/CD pipeline spec: Jenkins stages, mock/real LLM eval, environment promotion, rollback |

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
          --eval-dataset=home-insurance-eval
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
          --eval-dataset=home-insurance-eval
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
        threshold: ">= 0.90"
      - metric: "goal_check_pass_rate"
        threshold: ">= 0.85"
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
      - name: "Deploy to dev"
        command: |
          kubectl set image deployment/deterministic-workflow-dev \
            workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
            --namespace=dev
        timeout_minutes: 3
      - name: "Smoke test"
        command: |
          python scripts/smoke_test.py \
            --env=dev \
            --endpoint="https://dev-api.example.com"
        timeout_minutes: 2

  deploy_e2e:
    name: "Deploy to e2e"
    trigger: manual                    # manual trigger from Jenkins UI
    environment: e2e
    steps:
      - name: "Deploy to e2e"
        command: |
          kubectl set image deployment/deterministic-workflow-e2e \
            workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
            --namespace=e2e
      - name: "E2E smoke test"
        command: |
          python scripts/smoke_test.py \
            --env=e2e \
            --endpoint="https://e2e-api.example.com"
      - name: "Run integration tests"
        command: |
          python -m pytest tests/integration/ \
            --env=e2e \
            --junitxml=results/integration-results.xml
        timeout_minutes: 10

  deploy_prod:
    name: "Deploy to prod"
    trigger: manual                    # manual + approval gate
    environment: prod
    approval:
      type: input                      # Jenkins input step
      message: "Deploy build ${BUILD_NUMBER} to production?"
      approvers:
        - release-managers
    steps:
      - name: "Deploy to prod (canary)"
        command: |
          kubectl set image deployment/deterministic-workflow-prod-canary \
            workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
            --namespace=prod
      - name: "Canary monitoring (10 min)"
        command: |
          python scripts/monitor_canary.py \
            --env=prod \
            --duration-minutes=10 \
            --error-rate-threshold=5 \
            --latency-threshold-p95=5
      - name: "Full prod rollout"
        command: |
          kubectl set image deployment/deterministic-workflow-prod \
            workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
            --namespace=prod
      - name: "Post-deploy smoke test"
        command: |
          python scripts/smoke_test.py \
            --env=prod \
            --endpoint="https://api.example.com"
```

---

## 3. Jenkinsfile Example (Declarative)

```groovy
// Jenkinsfile — Deterministic Workflow Framework
pipeline {
    agent {
        kubernetes {
            yaml '''
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: python
      image: python:3.12
      command: ['sleep', 'infinity']
      resources:
        requests:
          cpu: '2'
          memory: '4Gi'
'''
        }
    }

    environment {
        ENV = 'ci'
        DOCKER_REGISTRY = credentials('docker-registry')
        OPENAI_API_KEY_CREDENTIAL = credentials('openai-api-key')
        LANGSMITH_API_KEY = credentials('langsmith-api-key')
    }

    options {
        timeout(time: 60, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timestamps()
    }

    stages {
        stage('Lint') {
            when {
                anyOf { branch '**'; changeRequest() }
            }
            steps {
                sh 'pip install ruff'
                sh 'ruff check .'
                sh 'pip install mypy'
                sh 'mypy src/ --strict'
            }
        }

        stage('Eval — Mock LLM') {
            when {
                anyOf { branch '**'; changeRequest() }
            }
            steps {
                sh '''
                    pip install -r requirements-dev.txt
                    python -m pytest tests/evals/ \
                        --eval-dataset=home-insurance-eval \
                        --mock-llm \
                        --junitxml=results/eval-mock-results.xml
                '''
            }
            post {
                always {
                    junit 'results/eval-mock-results.xml'
                }
            }
        }

        stage('Eval — Real LLM') {
            when {
                changeRequest()
                beforeAgent true
            }
            steps {
                script {
                    def changedWorkflows = sh(
                        script: '''
                            git diff --name-only origin/main...HEAD -- workflows/ |
                            xargs -I {} basename {} .yaml |
                            tr '\\n' ',' | sed 's/,$//'
                        ''',
                        returnStdout: true
                    ).trim()

                    echo "Changed workflows: ${changedWorkflows}"
                }
                sh """
                    python -m pytest tests/evals/ \
                        --eval-dataset=home-insurance-eval \
                        --real-llm \
                        --changed-workflows="${changedWorkflows}" \
                        --junitxml=results/eval-real-results.xml \
                        --langsmith-project="ci-evals"
                """
            }
            post {
                always {
                    junit 'results/eval-real-results.xml'
                }
            }
        }

        stage('Build') {
            when {
                branch 'main'
                not { changeRequest() }
            }
            steps {
                sh """
                    docker build \
                        --tag "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
                        --tag "${DOCKER_REGISTRY}/deterministic-workflow:latest" \
                        --build-arg ENV=prod \
                        .
                    docker push "${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}"
                """
            }
        }

        stage('Deploy — dev') {
            when {
                branch 'main'
                not { changeRequest() }
            }
            steps {
                sh """
                    kubectl set image deployment/deterministic-workflow-dev \
                        workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
                        --namespace=dev
                """
                sh 'python scripts/smoke_test.py --env=dev'
            }
        }

        stage('Deploy — e2e') {
            when {
                branch 'main'
                not { changeRequest() }
            }
            input {
                message "Deploy build ${BUILD_NUMBER} to e2e?"
                ok "Deploy to e2e"
            }
            steps {
                sh """
                    kubectl set image deployment/deterministic-workflow-e2e \
                        workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
                        --namespace=e2e
                """
                sh 'python scripts/smoke_test.py --env=e2e'
                sh 'python -m pytest tests/integration/ --env=e2e --junitxml=results/integration-results.xml'
                junit 'results/integration-results.xml'
            }
        }

        stage('Deploy — prod') {
            when {
                branch 'main'
                not { changeRequest() }
            }
            input {
                message "Deploy build ${BUILD_NUMBER} to PRODUCTION?"
                ok "Deploy to production"
                submitter "release-managers"
            }
            steps {
                sh """
                    kubectl set image deployment/deterministic-workflow-prod-canary \
                        workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
                        --namespace=prod
                """
                sh 'python scripts/monitor_canary.py --env=prod --duration-minutes=10'
                sh """
                    kubectl set image deployment/deterministic-workflow-prod \
                        workflow="${DOCKER_REGISTRY}/deterministic-workflow:${BUILD_NUMBER}" \
                        --namespace=prod
                """
                sh 'python scripts/smoke_test.py --env=prod'
            }
        }
    }

    post {
        always {
            cleanWs()
        }
        failure {
            slackSend(
                channel: '#ci-alerts',
                color: 'danger',
                message: "Pipeline failed: ${env.JOB_NAME} #${env.BUILD_NUMBER} — <${env.BUILD_URL}|View>"
            )
        }
        success {
            slackSend(
                channel: '#ci-alerts',
                color: 'good',
                message: "Pipeline succeeded: ${env.JOB_NAME} #${env.BUILD_NUMBER} — <${env.BUILD_URL}|View>"
            )
        }
    }
}
```

---

## 4. Evaluation Stage Details

### 4.1 Eval Suites

```yaml
# evals-create test configuration
eval:
  suites:
    home_insurance_quote:
      dataset: home-insurance-eval
      test_cases:
        - name: "happy_path_full_quote"
          input: "I need home insurance for my 3-bedroom house"
          expected:
            intent: get_quote
            completion_state: completed
          assert:
            - extracted.property_type is not null
            - extracted.address is not null
            - response_data.goal_met == true
        
        - name: "incomplete_info_graceful"
          input: "I want insurance"
          expected:
            intent: get_quote
            completion_state: active
          assert:
            - extracted.property_type is null
            - response_data.goal_met == false
            - response_data.gap_analysis is not null
        
        - name: "intent_misclassification_resilience"
          input: "Tell me about your insurance products compared to competitors"
          expected:
            intent: general_inquiry
          assert:
            - intent != get_quote

  eval_gates:
    global:
      intent_accuracy: ">= 0.90"
      goal_check_pass_rate: ">= 0.85"
      schema_violation_rate: "<= 0.05"
    
    per_workflow:
      home_insurance_quote:
        extraction_f1: ">= 0.88"
        routing_accuracy: ">= 0.92"
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
    #   - match: "insurance.*house"
    #     response: { "intent": "get_quote", "confidence": 0.95 }
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

## 5. Real Project Example: mrratequote

### 5.1 Overview

**mrratequote** is a mortgage rate quote system. The chat version routes users through a mortgage quote workflow: collect property details → gather financial info → run credit check → present rate options.

```
User: "What's the best rate for a $500K mortgage?"
    │
    ▼
Layer 1 (Extract): { intent: "get_mortgage_rate", loan_amount: 500000 }
Layer 2 (Route): mortgage_rate_quote workflow → collect_financial_info phase
Layer 3 (Respond): "I'd be happy to find rates for a $500K loan. First, let me ask..."
```

### 5.2 Backend Integration

The framework's chat version calls mrratequote's backend API for rate calculations:

```yaml
# workflow integration configuration
workflows:
  mortgage_rate_quote:
    backend:
      api: mrratequote
      base_url: "https://mrratequote-api.${ENV}.example.com"
      auth:
        type: api_key
        key: "${MRRATEQUOTE_API_KEY}"
      endpoints:
        submit_application: "POST /v1/applications"
        get_rates:            "GET  /v1/rates"
        run_credit_check:     "POST /v1/credit-check"
      timeout_seconds: 10
      retry:
        max_attempts: 2
        backoff: exponential
      circuit_breaker:
        failure_threshold: 5
        recovery_timeout_seconds: 30
```

### 5.3 Eval Dataset for mrratequote

```yaml
eval:
  suites:
    mortgage_rate_quote:
      dataset: mortgage-rate-quote-eval
      test_cases:
        - name: "happy_path_full_rate_quote"
          input: "I'm looking for a mortgage rate on a $500,000 home with 20% down"
          expected:
            intent: get_mortgage_rate
          assert:
            - extracted.loan_amount == 500000
            - extracted.down_payment_percent == 20
            - response_data.rates is not null
        
        - name: "insufficient_credit_score"
          input: "What rate can I get with a 580 credit score?"
          expected:
            intent: get_mortgage_rate
          assert:
            - extracted.credit_score == 580
            - response_data.outcome == "declined"
            - response_data.reason contains "credit"
        
        - name: "jumbo_loan_routing"
          input: "Need a rate for a $1.2M property in California"
          expected:
            intent: get_mortgage_rate
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

### 7.3 Rollback Jenkinfile

```groovy
// Jenkinsfile.rollback
pipeline {
    agent any

    parameters {
        choice(
            name: 'ENVIRONMENT',
            choices: ['dev', 'e2e', 'prod'],
            description: 'Target environment to rollback'
        )
        string(
            name: 'TARGET_BUILD',
            defaultValue: 'previous',
            description: 'Build number to rollback to (or "previous" for last known good)'
        )
    }

    stages {
        stage('Verify Rollback') {
            steps {
                script {
                    def buildNum = params.TARGET_BUILD
                    if (buildNum == 'previous') {
                        buildNum = sh(
                            script: 'kubectl get deployment -n prod deterministic-workflow-prod -o jsonpath="{.metadata.annotations.deployment\\.kubernetes\\.io/revision}"',
                            returnStdout: true
                        ).trim().toInteger() - 1
                    }
                    env.ROLLBACK_BUILD = buildNum
                }
            }
        }

        stage('Deploy Previous Build') {
            steps {
                sh """
                    kubectl set image deployment/deterministic-workflow-${params.ENVIRONMENT} \
                        workflow="${DOCKER_REGISTRY}/deterministic-workflow:${ROLLBACK_BUILD}" \
                        --namespace=${params.ENVIRONMENT}
                """
            }
        }

        stage('Restore Checkpoints') {
            steps {
                sh """
                    python scripts/rollback_checkpoint.py \
                        --label="pre-deploy-${params.TARGET_BUILD}" \
                        --env=${params.ENVIRONMENT}
                """
            }
        }

        stage('Verify') {
            steps {
                sh "python scripts/smoke_test.py --env=${params.ENVIRONMENT}"
            }
        }
    }
}
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
| 4 | Should eval gates be configurable per workflow (mortgage_rate_quote might need different accuracy thresholds than home_insurance_quote)? | Flexibility vs consistency |
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
- [Conversation Lifecycle](./2026-06-17-conversation-lifecycle.md) — Checkpoint rollback integration
- [Jenkins Declarative Pipeline](https://www.jenkins.io/doc/book/pipeline/syntax/)
- [Jenkins Kubernetes Plugin](https://plugins.jenkins.io/kubernetes/)
