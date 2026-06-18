# 响应生成层规范

> 隶属于[确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：目标设定、响应生成、目标完成验证、模板、敏感字段处理。
> **本规范定义接口和备选实现策略 — 非单一方案。**

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 初始响应生成规范：目标设定、响应生成、目标完成检查、并行执行 |
| 2026-06-17 | 0.2.0 | 重构响应模式：纯文本消息（LLM+eval）vs Widget（确定性）；添加节点循环回退 |
| 2026-06-17 | 0.3.0 | 将 Python 代码块替换为 YAML schema/配置；在第 4.4 节添加 errorNode 交叉引用；在第 2 节和第 4 节声明"所有 LLM 输出 = JSON" |
| 2026-06-17 | 0.4.0 | 第 4.3 节：移除重复的 JSON guardrail 声明；第 2.4 节：添加默认 goal 后备的 YAML 示例；第 6 节图表：将"error handler"修正为"errorNode" |

---

## 1. 角色定位

响应生成层（Layer 3）回答：*"我们应该如何回复用户？"*

它消费来自 Layer 2（Routing & Execution）的结构化结果，并产出用户可见的响应。它还验证工作流是否确实达成了其声明的目标。响应生成和目标验证并行运行。

```
Layer 2 → structured outcomes
              ↓
+-----------------------------+
| Layer 3: RESPOND            |
|                             |
|  [目标设定器]  ←──────── 工作流开始 (async)
|                             |
|  [生成响应]   ──┐          |
|                 ├── 并行扇出
|  [目标检查器]  ──┘          |
|                             |
|  如果差距 > 阈值: 422      |
+-----------------------------+
              ↓
          user response
```

### 1.1 Layer 3 不涵盖的内容

- **实体提取** → Layer 1
- **意图分类** → Layer 1
- **业务逻辑** → Layer 2
- **路由决策** → Layer 2
- **重试 / 错误处理** → Layer 2（第 6 节）
- **权限执行** → Layer 2（第 7 节）

---

## 2. 目标设定

> **所有 LLM 输出均为 JSON。** 框架对每次 LLM 交互强制执行结构化 JSON 输出，配合 schema 验证 guardrail。自由文本生成仅限于 Layer 3（Response）。

### 2.1 概念

每个工作流都从一个**目标**开始 — 对工作流意图达成内容的结构化描述，从用户的初始话语和意图中推导出来。

目标在**工作流启动时由 LLM 异步设定**，存储在 `agentState.goal` 中。工作流立即继续执行；它不会因目标设定而阻塞。

### 2.2 目标 Schema

```
WorkflowGoal {
  summary:          string    // 用户想要什么的可读摘要
  intent:           string    // 分类后的意图 (例如 "get_quote")
  expected_entities: string[] // 应收集哪些实体
  expected_outputs: string[]  // 应生成哪些输出
  success_criteria: string[]  // "完成"的可衡量标准
  priority:          "normal" | "high" | "critical"
}

# 示例
goal: {
  summary: "用户想要为其公寓获取家庭保险报价",
  intent: "get_quote",
  expected_entities: ["property_info", "coverage_needs"],
  expected_outputs: ["risk_assessment", "premium_calculation", "quote"],
  success_criteria: [
    "property_type 已知",
    "address 已收集",
    "annual_premium 已计算",
    "quote 已呈现给用户"
  ],
  priority: "normal"
}
```

### 2.3 异步执行

目标设定在工作流启动时异步分发。工作流立即继续执行，不阻塞 LLM 调用。当 LLM 完成时，目标写入 `agentState.goal`。如果目标设定器在目标检查节点运行时尚未完成，框架等待（最多 1 秒超时）。

**所有 LLM 输出均为 JSON。** 框架对每次 LLM 交互强制执行结构化 JSON 输出，配合 schema 验证 guardrail。

```yaml
# 每个工作流的配置
goal_setting:
  executor: llm
  output_schema: WorkflowGoal
  temperature: 0
  prompt_template: goal_setter_prompt
  async: true                 # 立即分发，不阻塞工作流
  timeout_ms: 1000            # 目标检查前未完成时的最大等待时间
  fallback_on_failure: derive_from_intent  # 从意图 + 实体推导默认目标
```

### 2.4 目标可用性保证

保证目标在目标检查节点运行之前（工作流结束时）可用。如果异步目标设定器届时尚未完成，框架等待（最多 1 秒超时）。如果目标设定器失败 → 从意图 + 已收集的实体推导默认目标。

```yaml
# 默认目标后备示例：
# intent=get_quote + entities=[property_info] → goal: "提供家庭保险报价"
default_goal_fallback:
  strategy: derive_from_intent     # 后备从意图 + 已收集实体推导目标
  mapping:
    get_quote:
      summary_template: "用户想要 {product_type} 保险报价"
      expected_outputs: ["risk_assessment", "premium_calculation", "quote"]
    file_claim:
      summary_template: "用户想要为 {claim_type} 提交理赔"
      expected_outputs: ["claim_validation", "claim_status"]
    ask_question:
      summary_template: "用户询问了关于 {topic} 的问题"
      expected_outputs: ["answer"]
```

---

## 3. 响应生成

### 3.1 契约

```
Input:
  outcome:       Map<string, any>   // 来自 Layer 2 的结构化结果
  entities:      Map<string, any>   // 已收集的实体
  goal:          WorkflowGoal       // 工作流的目标
  conversation:  ContextWindow      // 对话历史

Output:
  response:      ResponseMessage    // 用户可见的响应
```

### 3.2 ResponseMessage Schema

```
ResponseMessage {
  text:           string            // 主要文本内容（支持 markdown）
  components?:    UIComponent[]     // 结构化 UI 元素
  actions?:       SuggestedAction[] // 快捷回复按钮、后续建议
  sensitive_data_scrubbed: boolean  // 框架标志: PII 已从自由文本中移除
}
```

### 3.3 实现选项

两种模式服务于同一目的：**提供正确的答案并引导用户进入下一步。**

#### 选项 A：纯文本消息（LLM）

LLM 根据当前 `agentState` 生成自然语言消息。框架注入提示指导 LLM 说什么以及怎么说。

| 方面 | 详情 |
|--------|--------|
| 优势 | 自然语言；适应任何结果形态 |
| 劣势 | 非确定性；LLM 成本；需要 prompt 评估测试 |
| 提示词 | 框架注入：包含 goal、outcomes、entities、conversation 上下文 |
| 温度 | 0.3（足够自然表达，不足以产生创意偏移） |
| Guardrail | 框架后处理：与 entities 交叉校验值、编辑 PII |
| 评估要求 | Prompt 指导准确性必须通过评估套件测试 |

```yaml
# 纯文本消息生成的工作流级 prompt 配置
response_generation:
  mode: pure_message
  prompt_template: response_generator_prompt
  prompt_variables:
    - goal
    - outcomes
    - entities
    - conversation
    - next_step_suggestion     # 始终为 true: 引导用户进入下一个操作
  output_schema: ResponseMessage
  temperature: 0.3
  guardrails:
    - schema_validation        # 强制执行 ResponseMessage schema
    - cross_check_entities     # 验证引用的值与已收集实体匹配
    - redact_pii               # 交付前剥离敏感数据
```

**提示词引导评估：** 提示词必须可靠地生成满足以下条件的响应：
1. 准确引用实体值（不虚构数字）
2. 包含清晰的下一步建议
3. 匹配为工作流配置的语气
4. 不编造未产生的输出结果

```yaml
# 提示词评估的评估用例定义
eval_cases:
  - id: "prod_default"
    description: "标准保险报价完成"
    given_state:
      goal:
        summary: "用户想要家庭保险报价"
        intent: "get_quote"
      entities:
        property_address: "123 Main St"
        property_type: "apartment"
      outcomes:
        premium_calculation:
          annual_premium: 1200
    expected:
      themes: ["地址已确认", "保费已计算", "下一步"]
      forbidden_themes: ["未知数据", "虚构输出"]
      tone: "professional"
    threshold_pct: 95

  - id: "incomplete_flow"
    description: "工作流以缺失实体结束"
    given_state:
      goal:
        summary: "用户想要报价"
        intent: "get_quote"
      entities:
        property_address: "456 Oak Ave"
        # property_type 有意缺失
      outcomes:
        error: "property_type 未收集"
    expected:
      themes: ["我们需要更多信息", "房产类型"]
      forbidden_themes: ["保费已计算", "报价已就绪"]
      tone: "professional"

# 评估套件在每次 prompt 变更时运行。必须通过 ≥95%。
```

#### 选项 B：组件/Widget（确定性逻辑）

纯逻辑生成结构化 UI 组件。不调用 LLM。Widget 包含答案 + 下一步引导，采用前端可以渲染的机器可读格式。

| 方面 | 详情 |
|--------|--------|
| 优势 | 确定性；零 LLM 成本；渲染一致；即时 |
| 劣势 | 无法适应意外结果；前端必须支持组件类型 |
| 最适合 | 结构化数据呈现（保费卡片、理赔状态、风险仪表盘） |
| 生成方式 | 纯代码：映射 outcomes → widget 模板 → 用实体数据填充 |

```yaml
# 工作流级 widget 映射：outcomes → 组件
widget_mapping:
  premium:
    outcome_key: "premium"
    condition: "outcomes.premium 存在"
    component: premium_breakdown_card
    required_fields: [annual_premium, monthly_premium, coverage_type]

  risk_score:
    outcome_key: "risk_score"
    condition: "outcomes.risk_score 存在"
    component: risk_score_gauge
    required_fields: [score, factors]

  requires_approval:
    outcome_key: "requires_approval"
    condition: "outcomes.requires_approval == true"
    component: approval_buttons

  default_next_step:
    component: next_step_actions
    always: true
```

Widget 定义为已注册组件：

```yaml
components:
  premium_breakdown:
    type: widget
    fields:
      annual_premium:   { type: float, required: true }
      monthly_premium:  { type: float, required: true }
      coverage_type:    { type: string, required: true }
      risk_score:       { type: int, range: [0, 100] }
    render:
      template: premium_breakdown_card_template
  risk_gauge:
    type: widget
    fields:
      score:    { type: int, range: [0, 100] }
      factors:  { type: list }
```

#### 选项 C：混合 — Widget + 消息后备

主要响应通过 widget（确定性）。自动生成纯文本消息作为不支持富组件通道的后备。

```yaml
response_strategy:
  primary: widget          # widget | pure_message
  fallback: auto_message   # auto_message | none
```

### 3.4 对比矩阵

| 维度 | 纯文本消息（LLM） | Widget（确定性） | 混合 |
|-----------|-------------------|----------------------|-------|
| 响应生成 | LLM | 纯代码 | Widget + LLM 后备 |
| 成本 | $$$ | $ | $$ |
| 确定性 | 低 | 高 | 高（主体是确定性的） |
| 下一步引导 | LLM prompt 引导 | 在 widget 逻辑中编码 | Widget 逻辑 |
| 富 UI | 仅文本 | 结构化组件 | 结构化组件 |
| 需要 prompt 评估 | 是 | 否 | 仅后备 |
| 最适合 | 文本为主通道、简单响应 | 富客户端、结构化数据 | 生产默认 |

---

## 4. 目标完成检查

> **所有 LLM 输出均为 JSON。** 目标检查器是一个 LLM 节点，产生结构化 `GoalCheckResult` JSON，配合 schema 验证 guardrail。

### 4.1 概念

在工作流结束时，一个 LLM 节点**与响应生成并行运行**，验证工作流是否确实达成了其目标。这就是 `goalChecker` 节点。

```
Workflow End
     │
     ├──→ [generateResponse] ──→ response_text
     │
     └──→ [goalChecker] ──→ goal_check_result
                │
                ├── 差距 ≤ 阈值 → 交付响应
                └── 差距 > 阈值 → HTTP 422 Unprocessable Content
```

### 4.2 GoalCheckResult Schema

```
GoalCheckResult {
  goal_met:          boolean           // 目标是否已达成
  completion_percentage: float        // 0.0 - 1.0
  satisfied_criteria: string[]        // 哪些 success_criteria 已满足
  unsatisfied_criteria: string[]      // 哪些 success_criteria 未满足
  gap_analysis:      string           // LLM 推理：缺少什么
  missing_entities:  string[]         // 未收集的实体
  missing_outputs:   string[]         // 未产生的输出
}
```

### 4.3 差距阈值 & Error 422

目标检查器与响应生成并行运行。

```yaml
# 每个工作流的配置
goal_check:
  executor: llm
  output_schema: GoalCheckResult
  temperature: 0
  prompt_template: goal_checker_prompt
  prompt_variables:
    - goal
    - entities
    - outcomes
    - conversation

  gap_threshold: 0.3          # completion < (1 - threshold) → 422
  # 示例: threshold = 0.3 意味着 completion ≥ 70% 为必需

  on_gap:
    strategy: error_422       # error_422 | loop_back | escalate
    response:
      status: 422
      body:
        error: "goal_not_met"
        goal_summary: "{{ goal.summary }}"
        completion: "{{ result.completion_percentage }}"
        unsatisfied: "{{ result.unsatisfied_criteria }}"
        gap_analysis: "{{ result.gap_analysis }}"
```

### 4.4 目标检查失败处理

当引发 422 时：

1. 响应**不会**交付给用户
2. 错误传播到调用系统
3. 对话状态被记录检查点（可被人工代理恢复）
4. 审计日志记录：目标、完成百分比、差距分析、未满足标准
5. 422 错误最终通过 `errorNode`（见 Layer 2，第 6 节 — 重试与错误处理）进行统一错误日志记录、检查点和升级

调用方可以选择：
- 显示 `"我们无法完成您的请求。客服人员将跟进处理。"`
- 自动使用丰富上下文重试工作流
- 升级到人工审核

### 4.5 非事务流程中的目标检查

对于对话式/FAQ 流程（无事务性目标），`goal_checker` 仍然运行但使用放宽的阈值：

```yaml
goal_check:
  transactional_threshold: 0.7    # 事务型工作流需要 70% 完成度
  conversational_threshold: 0.3   # FAQ 只需 30% — 回答一个问题就"够好"
  enabled: true                   # 可按工作流禁用
```

---

## 5. 节点循环回退（自我纠正）

### 5.1 概念

一个完成其任务的节点仍然可以检测到某些内容不完整，并**循环回退以重新运行之前的节点。** 这实现了自我纠正工作流 — 例如：

```
[code] → [test] → (fails) → [debug] → [code] → [test] → (passes) → [respond]
```

这不特定于 Layer 3 — 它适用于任何层的任何节点。但它通过目标检查器与响应生成集成：如果目标检查器发现差距，它可以触发循环回退，而不仅仅是返回 422。

### 5.2 循环回退触发器

节点可以声明执行后检查。如果检查失败 → 循环回退到指定状态：

```yaml
states:
  run_tests:
    executor: code
    execute: run_test_suite
    post_check:
      condition: "all_tests_passed == false"
      on_fail: debug_and_fix      # 循环回退到此状态
      max_loops: 3                # 防止无限循环

  deploy:
    executor: code
    execute: deploy_to_staging
    post_check:
      condition: "deployment_healthy == false"
      on_fail: rollback_and_retry
      max_loops: 2
```

### 5.3 与目标检查器的集成

当目标检查器检测到差距（completion < threshold）时，工作流可以配置为循环回退，而不是抛出 422：

```yaml
# 每个工作流的配置
goal_check:
  on_gap:
    strategy: loop_back        # loop_back | error_422 | escalate
    loop_back_to: start_phase  # 返回到哪个阶段
    max_loop_backs: 2          # 每个工作流执行的最大总循环回退次数
```

### 5.4 循环回退状态

循环回退保留已收集的数据（目前为止已填写的实体）。重新启动的节点接收：
- 到目前为止已收集的所有实体
- 来自目标检查器的差距分析（缺少什么）
- 循环回退计数器（剩余尝试次数）

```
[collect] → [validate] → [calculate] → [goalChecker]
                    ↑                        │
                    │                  (gap: address missing)
                    │                        │
                    └── loop_back ───────────┘
                    (address asked, filled)
                         │
                         ↓
              [validate] → [calculate] → [goalChecker] → (passes)
```

### 5.5 循环回退 vs 重试

| 机制 | 重试（Layer 2，第 6 节） | 循环回退（本节） |
|-----------|--------------------------|-------------------------|
| 触发条件 | 节点执行失败（超时、错误） | 任务不完整（结果不对） |
| 重复内容 | 相同节点以相同输入 | 不同节点（工作流中较早的节点）以丰富后的状态 |
| 目的 | 瞬时错误恢复 | 自我纠正不完整工作 |
| 预算 | `max_attempts` 按节点 | `max_loops` 每次循环回退 + `max_loop_backs` 每工作流 |

---

## 6. 并行执行模式（响应 + 目标检查器）

### 6.1 工作流结束时的扇出

```
[Last Layer 2 Node] → conditional edge
                            │
                    ┌───────┴───────┐
                    │               │
              [generateResponse]  [goalChecker]
                    │               │
                    └───────┬───────┘
                            │
                     [responseRouter]
                            │
                    ┌───────┴───────┐
            (goal met)          (422: goal not met)
                │                      │
           deliver response      errorNode
```

### 6.2 实现方式

并行扇出使用 LangGraph 的 `Send` API 从最后一个 Layer 2 节点通过条件边将状态同时分发给 `generateResponse` 和 `goalChecker`。两个节点并发执行，然后汇聚到 `responseRouter` 节点，该节点检查 `goal_check.passed` 来决定：交付响应（路由到 `END`）或处理目标未达成（路由到 `errorNode` 进行统一的 422 处理）。

图结构：

- **节点：** `generateResponse`、`goalChecker`、`responseRouter`、`errorNode`
- **扇出：** `lastLayer2Node` → 条件边 → `Send` 到 `generateResponse` 和 `goalChecker` 两者
- **汇聚：** `generateResponse` 和 `goalChecker` 两者 → 边 → `responseRouter`
- **路由：** `responseRouter` → 条件边 → `END`（交付）或 `errorNode`（422）

---

## 7. 前置元数据组件协议

对于确定性结构化 UI 渲染（例如，聊天界面中的格式化卡片），框架采用受 zelkim 启发的前置元数据协议：

```
ResponseMessage {
  text: "这是您的报价..."
  components: [
    {
      type: "premium_breakdown_card",
      metadata: { ... },
      data: { ... }           // 结构化、机器可读
    }
  ]
}
```

`text` 字段是仅支持纯文本的通道（SMS、电子邮件）的后备方案。`components` 数组为富客户端（Web、移动端）提供结构化渲染。

### 7.1 组件类型（可扩展）

| 组件类型 | 描述 |
|---------------|-------------|
| `premium_breakdown_card` | 带分项列出的保险保费详情 |
| `risk_score_gauge` | 可视化风险评分（0-100） |
| `coverage_comparison_table` | 并列承保范围选项对比 |
| `claim_status_tracker` | 理赔生命周期进度 |
| `payment_confirmation` | 带交易 ID 的支付回执 |
| `document_upload_prompt` | 带类型约束的文件上传 |
| `approval_buttons` | 确认 / 拒绝 / 修改操作 |

自定义组件通过插件注册。

---

## 8. 敏感字段处理

### 8.1 生成后个人隐私信息清洗

框架对每个生成的响应运行后处理。PII 规则（在领域模型中定义，见第 8.2 节）同时应用于响应 `text` 和组件 `data` 字段。

```yaml
# PII scrubbing 配置（按工作流或全局）
pii_scrubbing:
  enabled: true
  scope:
    - response_text             # 将 regex + 字段掩码应用于 ResponseMessage.text
    - component_data            # 在 UI 组件中掩码敏感字段值
  rule_source: domain.pii_rules # 领域模型中定义的规则（第 8.2 节）
  on_complete:
    set_flag: sensitive_data_scrubbed  # = true
```

### 8.2 PII 规则（在领域模型中定义）

```yaml
pii_rules:
  - pattern: "\\b[0-9]{16}\\b"         # 信用卡号
    replacement: "****-****-****-{last4}"
  - pattern: "\\b[0-9]{18}\\b"         # 中国身份证号
    replacement: "******{last4}"
  - fields: [phone, email, id_number]   # 需要掩码的实体字段
    strategy: partial_mask              # 显示前 3 位，掩码其余
```

### 8.3 LLM Prompt 中的敏感数据

在构建用于响应生成的 LLM prompt 时，仅传递已收集实体的**非敏感子集**。PII 规则（来自第 8.2 节）在**prompt 构建之前**应用。

```yaml
# 每个工作流的配置
prompt_entity_filter:
  enabled: true
  rule_source: domain.pii_rules      # 匹配第 8.2 节
  strategy: partial_mask             # partial_mask | exclude | redact
  # partial_mask: 显示前 3 个字符，掩码其余 (例如 "Joh***")
  # exclude: 从 prompt 中完全省略该字段
  # redact: 替换为 "[REDACTED]"
```

框架在将实体注入任何 LLM prompt 模板之前，将此过滤器应用于 `state.collectedFields`。生成的 `safe_entities` map 是 prompt 模板通过 `entities` 变量接收的内容。

---

## 9. 待决问题

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | 目标检查器是否应在工作流中途运行（每个阶段转移时），还是仅在工作流结束时？ | 提前失败检测 |
| 2 | 422 错误 — 框架应支持自动重试整个工作流，还是始终升级？ | 恢复策略 |
| 3 | 对于异步目标设定：如果用户在目标设定完成前重新表述或更改请求，会发生什么？ | 目标准确性 |
| 4 | 模板编写 — 模板应使用 YAML、Jinja2 还是自定义 DSL 编写？ | 开发者体验 |
| 5 | 组件协议 — 组件应定义为标准 schema（如 JSON Schema）以实现跨平台互操作性吗？ | 富客户端支持 |
| 6 | PII scrubbing — 是否应具有语言感知能力（例如，中国身份证号 vs 美国 SSN 模式）？ | 国际化 |

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 父架构、框架原则（JSON guardrails）
- [领域模型设计](./2026-06-17-domain-model-design.md) — 实体 schema、领域模型中的 PII 规则
- [路由与执行层设计](./2026-06-17-routing-execution-layer-design.md) — Layer 2 输出被响应生成消费
- zelkim/langgraph-insurance-chatbot — 前置元数据组件协议、混合模板模式
- Prodigal Payment Collection Agent — 发送前 API 响应清洗（卡片数据从内存中擦除）
