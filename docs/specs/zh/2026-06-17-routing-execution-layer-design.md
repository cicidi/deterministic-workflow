# 路由与执行层规范

> 隶属于[确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：业务逻辑执行、决策路由、阶段感知路由 + 返回栈、子工作流复用、重试预算、权限模型、工具系统。
> **本规范定义接口和备选实现策略 — 非单一方案。**

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 初始路由与执行规范：executor、决策节点、阶段感知路由 + 返回栈、子工作流、重试、权限、工具系统 |
| 2026-06-17 | 0.2.0 | 将所有 Python 代码块替换为 YAML schema/结构化描述；将 errorNode 配置（§8）合并到重试章节（§6）；为 AbstractState、代码执行器、决策规则、阶段路由、errorNode、权限执行、工具接口、转移执行添加 YAML schema |
| 2026-06-17 | 0.3.0 | 第 2.3 节：从 YAML 注释中移除 ≤50 行约束；删除第 8 节存根（现已合并到第 6 节）；修复第 6.7 节 ASCII 流程图缺失的结尾 ``` 标记 |
| 2026-06-18 | 0.4.0 | 添加 §5 A2A 协议交叉引用（子工作流作为 A2A 定义语言） |
| 2026-06-18 | 0.5.0 | 将 `Tool.type` 枚举从 `api \| mcp \| command \| llm` 扩展为 `api \| mcp \| command \| llm \| a2a \| sdk`；添加 `a2a` 工具类型用于 agent-to-agent 作为工具；添加 `sdk` 工具类型用于 OpenCode/Claude SDK 作为工具 |

---

## 1. 角色定位

路由与执行层（Layer 2）回答：*"我们应该如何处理提取出来的数据？"*

它消费来自 Layer 1（Extraction）的已验证实体，产出来自 Layer 3（Response）的结构化结果。这是**核心业务逻辑层** — 规则被执行、决策被做出、副作用（API 调用、数据库写入）在此发生。

```
Layer 1 → validated entities
              ↓
+-----------------------------+
| Layer 2: DECIDE             |
|                             |
|  [代码执行器]                 |  → 业务计算
|  [决策节点]                   |  → 规则引擎路由
|  [子工作流调用器]              |  → 共享能力复用
|  [阶段感知路由]                |  → 通过返回栈进行状态锁定
|  [重试管理器]                 |  → 重试 + 升级
|  [权限执行器]                 |  → 工具 + 转移访问
+-----------------------------+
              ↓
Layer 3 ← structured outcomes
```

### 1.1 Layer 2 不涵盖的内容

- **实体提取** → Layer 1（Extraction 规范）
- **意图分类** → Layer 1（Intent Classification 规范）
- **字段验证** → Layer 1（Extraction 规范中的 Validate 节点）
- **响应生成** → Layer 3（Response Generation 规范）
- **状态机机制** → State Machine Design 规范（转移、守卫、元数据）
- **领域模型定义** → Domain Model 规范（实体、状态、转移）

---

## 2. 代码执行器节点

### 2.1 契约

代码执行器是**纯业务逻辑**函数。它们接收已验证的数据，计算结果，并返回结果。它们是小巧的、可组合的、确定性的。

```
Input:
  entities:   Map<string, any>   // 来自 Layer 1 的已验证实体
  state_context: StateContext     // 当前状态信息
  previous_results: Map<string, any> // 此工作流中之前节点的结果

Output:
  results:    Map<string, any>   // 计算出的业务结果
  decisions:  DecisionResult[]   // 给下游节点的路由提示
  side_effects: SideEffect[]     // API 调用结果、数据库写入（记录用于审计）
```

### 2.2 设计约定

- 每个执行器方法 ≤ **50 行**
- 每个执行器文件 ≤ **1000 行**
- 复杂计算拆分为子函数或子工作流
- 执行器是纯函数：相同输入 → 相同输出（无隐藏状态）
- 副作用（API 调用、数据库写入）在 `side_effects` 中显式声明

### 2.3 抽象父级数据模型

每个状态共享一个通用抽象父级，提供元数据。框架管理下面的元数据字段；开发者实现单个 `execute(input: StateInput) → StateOutput` 函数（≤ 50 行），包含该状态的业务逻辑。

```yaml
# 抽象父级数据模型 — 每个状态共享此结构
abstract_state:
  # --- 框架管理（在 workflow YAML 中配置，运行时填充）---
  state_name: string              # 唯一节点标识符
  state_entity: string            # 绑定的领域模型实体名称
  state_hint: string              # 给下游节点的消歧提示
  permission: NodePermission      # 工具 + 转移白名单（见 §7）
  retry_budget: RetryBudget       # 重试配置（见 §6.2）

  # --- 开发者实现 ---
  # execute: (input: StateInput) -> StateOutput
  #   该状态的业务逻辑。将复杂逻辑委托给子函数。
```

### 2.4 实现选项

#### 选项 A：纯函数（推荐）

代码执行器在 workflow YAML 中以模块+函数引用的方式注册。框架在加载时解析引用，并使用已验证的输入调用该函数。该函数为纯函数、无状态计算 — 无副作用、无框架依赖。

```yaml
# 代码执行器配置为纯函数引用
executor: code
execute: premium.calculate                  # 模块.函数 引用
input_mapping:
  property_info: "{{entities.property_info}}"
  coverage_needs: "{{entities.coverage_needs}}"
output:
  risk_score: number
  annual_premium: number
  monthly_premium: number
  rate_multiplier: number
```

| 优势 | 可隔离测试；零框架依赖；IDE 友好 |
|-----------|---------------------|
| 劣势 | 无内置生命周期钩子；需手动处理审计追踪 |
| 最适合 | 无状态计算；风险评分；保费计算 |

#### 选项 B：StateHandler 类

当需要更丰富的生命周期钩子（执行前/后、审计、错误处理）时，执行器可以配置类级别的元数据以及处理类引用：

```yaml
# StateHandler 配置了生命周期元数据
executor: code
execute: premium.CalculatePremiumHandler    # 类引用
state_name: calculate_premium
state_entity: premium_result
lifecycle:
  pre_execute: premium.validate_inputs       # 可选钩子
  post_execute: premium.audit_calculation    # 可选钩子
  on_error: premium.log_calculation_error    # 可选钩子
audit: true                                  # 框架自动记录审计追踪
```

| 优势 | 生命周期钩子（pre/post execute）；框架管理的审计；可复用基类 |
|-----------|---------------------|
| 劣势 | 更多样板代码；难以纯隔离方式单元测试 |
| 最适合 | 复杂多步计算；需要丰富生命周期的节点 |

### 2.5 对比矩阵

| 维度 | 选项 A（纯函数） | 选项 B（类处理程序） |
|-----------|------------------------|------------------------|
| 可测试性 | 优秀（无框架依赖） | 良好（需要 fixtures） |
| 代码行数 | ~10-30 每执行器 | ~20-50 每执行器 |
| 审计追踪 | 手动 | 框架自动 |
| 生命周期钩子 | 无 | pre/post_execute, on_error |
| 适用场景 | 简单计算 | 复杂编排 |

---

## 3. 决策节点

### 3.1 角色定位

决策节点回答：*"工作流下一步应该走哪个路径？"* — 超越简单的字段完成守卫（这些由状态机的转移守卫处理）。

> **所有 LLM 输出均为 JSON。** 使用 LLM 的决策节点产生结构化 JSON 输出，并受到框架强制的 guardrail（schema 验证、字段存在性、类型强制转换）。详见 HLD 第 4.3 节。

示例：
- 风险分诊：`risk_score > 80 → manual_review` / `risk_score ≤ 80 → auto_approve`
- 欺诈检测：异常模式触发 `fraud_review` 分支
- 产品路由：`product_type == "auto"` 路由到车险专属提取

### 3.2 实现选项

#### 选项 A：100% 规则引擎 — 确定性（强制性基线）

所有决策必须首先通过规则引擎。不涉及 LLM。规则在 YAML 中以声明方式定义：

```yaml
# 决策规则集 — 从上到下评估，首次匹配即胜出
decision_rules:
  risk_triage:
    input: entities.premium_calculation.risk_score
    rules:
      - condition: "risk_score >= 0 AND risk_score <= 30"
        decision:
          route: auto_approve
          reason: "低风险: {{risk_score}}"
      - condition: "risk_score > 30 AND risk_score <= 80"
        decision:
          route: standard_review
          reason: "中风险: {{risk_score}}"
      - condition: "risk_score > 80"
        decision:
          route: manual_review
          reason: "高风险: {{risk_score}}"
    on_unmatched: escalate               # 无规则匹配时的默认操作
```

| 方面 | 详情 |
|--------|--------|
| 优势 | 确定性；可审计；可解释；快速 |
| 劣势 | 规则维护成本高；无法处理新颖模式 |
| 依赖 | 规则引擎（durable_rules / business-rules / 原生） |
| 未处理情况 | 默认路由或错误升级 |

#### 选项 B：规则引擎 + LLM 后备（未来）

当规则引擎无法解决某个情况（例如，新颖的欺诈模式）时，框架**可选地**委托给 LLM 做出决策。LLM 接收：
- 完整的工作流上下文（当前状态、实体数据、对话历史）
- 来自规则引擎的决策条件（哪些无法解决）
- 预期输出 schema（JSON）

**此选项推迟到未来讨论。** LLM 如何理解工作流并做出正确决策的机制（例如，通过 skill 或 prompt 构建）需要单独设计。

#### 选项 C：仅规则引擎 — 无后备，直接报错（严格模式）

安全关键型部署完全禁用了 LLM 后备。如果规则引擎无法解决 → 升级到 `on_unresolved_decision` 节点（通常为人工审核或终止）。

### 3.3 决策输出契约

每个决策节点产生一个结构化结果：

```yaml
# DecisionResult schema
DecisionResult:
  route: string                                  # 目标节点名称
  reason: string                                 # 选择此路由的原因（审计追踪）
  confidence: number                             # 可选，规则引擎为 1.0；LLM 后备为可变值
  source: rule_engine | llm_fallback | default   # 决策来源
```

### 3.4 决策评估

基于 LLM 的决策（选项 B）需要评估框架：

```
EvalCase {
  input:    dict         # 输入决策节点的实体状态
  expected: DecisionResult   # 预期路由决策
  tolerance: float       # 可接受的置信度阈值（默认：0.7）
}
```

框架在每次 LLM 决策模型变更时运行评估。部署前必须通过 ≥ 95% 的评估用例。评估用例涵盖：
- 边界情况（边界风险分数）
- 模糊输入（缺失可选字段）
- 安全关键用例（绝不可路由 `high_risk → auto_approve`）

### 3.5 对比矩阵

| 维度 | 选项 A（规则引擎） | 选项 C（严格模式） |
|-----------|----------------------|-------------------|
| 确定性 | 100% | 100% |
| 覆盖范围 | 封闭世界规则 | 封闭世界规则 |
| 未处理情况 | 默认路由 | 错误 → 升级 |
| 可审计性 | 完整 | 完整 |
| 适用场景 | 大多数生产环境 | 高安全性（支付、医疗） |

---

## 4. 阶段感知路由 + 返回栈

### 4.1 概念

每个节点在完成时，基于以下因素决定**下一个节点**：

```
next_node = resolve(agentState.phase, intent)
```

关键行为：

1. **正常流程**：`phase=collect_property_info` + `intent=provide_information` → 路由到 `validate_property_info`
2. **中途提问**：`phase=collect_property_info` + `intent=ask_question` → 路由到 `rag_faq` 子工作流
3. **提问后返回**：`rag_faq` 完成后 → 返回到**之前所处的阶段**（`collect_property_info`）

框架维护一个**阶段返回栈**来支持此功能。当中途提问发生绕道时，当前阶段被压入栈中。当提问被回答后，栈被弹出，工作流在之前的阶段继续执行。

### 4.2 阶段返回栈

```
agentState = {
    phase:          "collect_property_info",   // 当前阶段
    phase_stack:    [],                         // 用于中途绕道的 push/pop
    collectedFields: { ... },                   // 累积的实体数据
    ...
}
```

**流程示例：**

```
1. 用户: "我想为我的公寓获取报价"
   phase = "collect_property_info"
   
2. Agent: "您的地址是什么？"
   (等待用户输入)
   
3. 用户: "基础计划涵盖什么？"
   intent = ask_question
   → phase_stack.push("collect_property_info")    // 保存当前阶段
   → 路由到 rag_faq 子工作流                        // 回答问题
   
4. Agent: "基础计划涵盖火灾、盗窃和水渍..."
   rag_faq 完成
   → phase = phase_stack.pop()                    // 恢复: "collect_property_info"
   → agent 继续: "那么，您的地址是什么？"
```

### 4.3 节点下一步解析

框架通过在阶段路由表中查询 `(current_phase, detected_intent)` 来解析下一个节点：

```yaml
# 阶段路由表 — 通过 (phase, intent) 解析下一个节点
phase_routing:
  collect_property_info:
    provide_information: validate_property_info     # 正常流程
    ask_question: rag_faq                            # 绕道 (push phase → answer → pop → resume)
    cancel: terminate                                # 退出 (栈非空时 pop，否则 terminate)
  validate_property_info:
    provide_information: assess_risk
    ask_question: rag_faq
    cancel: terminate
  # ... 各领域按需添加更多阶段
```

### 4.4 阶段连续性

zelkim 中的"一旦进入事务模式，始终处于事务模式"模式被重构为：**阶段决定路由，而非二元模式标志。** 当 `phase` 是事务阶段时（例如 `collect_property_info`），路由始终保持在事务分支内 — 提问会绕道但会返回，阶段栈确保连续性。

```yaml
# 阶段定义包含路由映射
phases:
  collect_property_info:
    entity: property_info
    transitions:
      provide_information: validate_property_info
      ask_question: rag_faq                    # 绕道 → 稍后返回
      cancel: terminate
```

---

## 5. 子工作流

### 5.1 概念

子工作流是**完整的、独立的工作流**，具有与父工作流相同的结构 — 拥有自己的领域模型（实体、状态、转移）、权限模型、重试预算和路由。共享能力（RAG FAQ、身份验证、支付处理）定义一次，可从任何父工作流中的任何状态进行调用。

这避免了 zelkim 中将 RAG 逻辑在对话和事务分支中重复的反模式。

### 5.2 完整工作流结构

子工作流具有与父工作流**完全相同的结构**。不是精简子集：

```yaml
# sub-workflows/rag_faq.yaml — 完整工作流
domain: rag_faq
version: 1.0.0
description: "使用 RAG 知识库回答用户问题"

entities:
  question_input:
    fields:
      question:
        type: string
        required: true
      conversation_context:
        type: string
        required: false
  answer_output:
    fields:
      answer:
        type: string
        required: true
      sources:
        type: list
        required: false

states:
  search_knowledge_base:
    entity: question_input
    executor: code
    execute: search_vector_db
    permission:
      allowed_tools: [vector_search_mcp]
      allowed_transitions: [generate_answer]
    retry_budget:
      max_attempts: 2
      timeout_ms: 10000

  generate_answer:
    entity: answer_output
    executor: llm
    output_schema: { answer: string, sources: string[] }
    retry_budget:
      max_attempts: 4    # 3 基础 + 1 LLM 额外

  return_to_caller:
    executor: code

transitions:
  - from: search_knowledge_base
    to: generate_answer
    guard: "question != null"
  - from: generate_answer
    to: return_to_caller
    guard: "answer != null"
```

### 5.3 子工作流内的节点编排

子工作流内的节点支持三种编排模式。**LangGraph 原生支持这三种**，通过其 `Send` API、条件边和子图组合实现。

#### 模式 A：串行（顺序）

```
[A] → [B] → [C] → [D]
```

标准边路由。每个节点完成后下一个才开始。

```yaml
transitions:
  - from: search_kb
    to: filter_results
  - from: filter_results
    to: generate_answer
  - from: generate_answer
    to: return_to_caller
```

#### 模式 B：并行（扇出 / 扇入）

```
         ┌→ [B1] ─┐
[A] ──→  ├→ [B2] ─┼──→ [C]
         └→ [B3] ─┘
```

LangGraph `Send` API 同时扇出到多个节点。全部必须完成后在 C 处汇聚。

```yaml
# 从 A 扇出到多个 B 节点
parallel_nodes:
  from: search_kb
  fan_out:
    - search_policy_db       # 搜索保单知识库
    - search_claims_db       # 搜索理赔知识库
    - search_faq_db          # 搜索 FAQ 数据库
  fan_in: merge_results      # 3 个全部完成后在此汇聚
```

#### 模式 C：混合（DAG）

```
         ┌→ [B] ─→ [C] ─┐
[A] ──→  │               ├──→ [E]
         └→ [D] ─────────┘
```

串行和并行结合。LangGraph 通过条件边 + `Send` 支持任意 DAG 拓扑。

```yaml
# DAG: 串行链 B→C 与 D 并行运行
parallel_nodes:
  from: classify_query
  fan_out:
    - chain:                    # 串行子链
        - extract_entities
        - validate_entities
    - search_knowledge_base     # 单个并行节点
  fan_in: synthesize_response
```

### 5.4 同步与异步调用

| 模式 | 行为 | 适用场景 |
|------|----------|---------|
| **同步** | 父工作流等待子工作流完成，然后继续 | RAG FAQ（必须先获取答案才能继续） |
| **异步** | 父工作流触发子工作流后立即继续；结果通过回调或轮询交付 | 审计日志、通知、后台验证 |

```yaml
# 同步调用（默认）
handle_question_in_quote:
  executor: sub_workflow
  sub_workflow: rag_faq
  mode: sync
  on_return: collect_property_info

# 异步调用
background_kyc_check:
  executor: sub_workflow
  sub_workflow: identity_verification
  mode: async
  on_complete: kyc_result_received     # 异步子工作流完成时的回调
```

### 5.5 子工作流嵌套

子工作流可以递归定义子工作流。`rag_faq` 子工作流本身可以调用 `translate_query` 子工作流，后者可以进一步调用更多子工作流。每一层都有自己隔离的状态、阶段栈和重试预算。

```yaml
# rag_faq 调用 translate_query 作为子-子工作流
states:
  translate_query:
    executor: sub_workflow
    sub_workflow: translate_query
    mode: sync
    on_return: search_knowledge_base
```

### 5.6 从父工作流调用

```yaml
# 在父工作流中
states:
  handle_question_in_quote:
    executor: sub_workflow
    sub_workflow: rag_faq                              # 已注册的子工作流
    mode: sync                                          # sync | async
    input_mapping:
      question: "{{state.last_user_message}}"
      conversation_context: "{{state.conversation_history}}"
    on_return: collect_property_info                    # 返回后恢复父阶段
```

### 5.7 LangGraph 支持摘要

| 功能 | LangGraph API | 支持 |
|---------|--------------|-----------|
| 串行节点链 | `add_edge("A", "B")` | ✅ |
| 并行扇出/扇入 | `Send()` API | ✅ (v0.2+) |
| 条件路由 | `add_conditional_edges()` | ✅ |
| 子图组合 | `StateGraph` 嵌套 | ✅ |
| 检查点/恢复（同步） | `checkpointer` | ✅ |
| 异步执行 | `ainvoke()` / `astream()` | ✅ (v0.2+) |
| 混合 DAG | Send + 条件边组合 | ✅ |

---

## 6. 重试与错误处理

### 6.1 核心原则：所有错误 → errorNode

不分类型分发。不设多环节升级链。**所有错误、所有超时、所有重试耗尽的失败 — 统一路由到单个 `errorNode` 进行统一处理。** `errorNode` 是存放错误恢复逻辑的唯一位置。

### 6.2 重试预算

每个节点都有重试配置：

```yaml
retry_budget:
  max_attempts: 3
  backoff: exponential            # linear | exponential | fixed
  base_delay_ms: 500
  max_delay_ms: 10000
  timeout_ms: 30000               # 每次尝试的超时
  on_exhausted: errorNode          # 始终是 errorNode
```

**LLM 节点获得 +1 额外重试。** 如果 `max_attempts` 是 3，LLM 节点重试 4 次。这弥补了 LLM 的非确定性（瞬时幻觉、格式错误的 JSON）。

LLM 节点的有效重试次数为 `max_attempts + 1`（弥补非确定性），其他所有节点类型为 `max_attempts`。

### 6.3 超时处理

所有超时（LLM 超时、API 超时、工具超时）在重试预算中均视为瞬时故障处理。耗尽重试后 → `errorNode`。

### 6.4 错误分类（用于日志记录，不用于路由）

错误分类用于**审计日志**，而非用于不同的路由路径。`errorNode` 接收分类并决定如何处理：

| 分类 | 示例 |
|----------|---------|
| `llm_error` | LLM 超时、格式错误的 JSON、幻觉 guardrail 触发 |
| `api_error` | 外部 API 超时、5xx 响应、连接拒绝 |
| `tool_error` | MCP 服务器不可用、命令非零退出 |
| `validation_error` | 数据不变性违例、类型不匹配 |
| `business_rule_error` | 保额超出限制、重复理赔 |
| `permission_error` | 未授权的工具调用、禁止的转移 |
| `unrecoverable_error` | 损坏的状态、缺失必需实体 |

### 6.5 errorNode 接口

`errorNode` 是一个统一的错误处理节点，接收来自所有节点的所有错误。其契约：

```yaml
# errorNode 契约
errorNode_input:
  source: string                  # 哪个节点失败
  category: error_category        # 7 种分类之一（见 §6.4）
  attempts: integer               # 耗尽前尝试的重试次数
  message: string                 # 人类可读的错误详情

errorNode_output:
  action: ask_clarify | escalate_to_human | terminate | fallback_value | retry_with_context
  correction: object              # 应用于失败节点的修正指令
  message: string                 # 面向用户或日志消息
```

**内置 errorNode 实现（用户可选）：**

| 策略 | 行为 |
|----------|---------|
| `ask_clarify` | 用澄清问题重新提示用户，恢复失败的节点 |
| `escalate_to_human` | 加入人工审核队列，挂起对话 |
| `terminate` | 优雅退出并附带道歉消息 + 审计日志 |
| `fallback_value` | 使用配置的默认值，记录警告，继续 |
| `retry_with_context` | 使用丰富上下文重新调用失败的节点（针对特定错误） |

### 6.6 与提取层的关系

提取层的 `max_transform_attempts` 与 Layer 2 的节点级 `retry_budget` 是分开的。提取重试处理字段级修正；Layer 2 重试处理节点级执行失败。两者耗尽后均路由到 `errorNode`。

### 6.7 流程图

```
Node execution
    │
    ├── success ──→ next node
    │
    └── failure
          │
          ├── retry (within budget) ──→ back to Node execution
          │     LLM nodes: +1 extra retry
          │
          └── retry exhausted ──→ errorNode
                                      │
                                      ├── ask_clarify (re-prompt user)
                                      ├── escalate_to_human
                                      ├── terminate
                                      ├── fallback_value
                                       └── retry_with_context
```
### 6.8 errorNode 配置

```yaml
# 全局默认
error_handling:
  default_error_node: ask_clarify
  max_total_errors: 5           # 对话级：总共 5 次错误后 → terminate
  errorNode_config:
    ask_clarify:
      max_clarifications: 3     # 升级前最大重新提示次数
    escalate_to_human:
      queue: "agent_review"
      timeout_minutes: 15
    terminate:
      message_template: "抱歉，我遇到了错误。我们的团队已收到通知。"
    fallback_value:
      default_values: {}        # 每个字段的默认值

# 每个节点的覆写
nodes:
  process_payment:
    error_node: escalate_to_human  # 支付错误总是转到人工
  calculate_premium:
    error_node: fallback_value     # 计算失败时使用默认费率
```

### 6.9 errorNode → 对话连续性

在 `errorNode` 处理错误后，对话从触发错误的状态恢复。`errorNode` 不会改变工作流状态 — 它返回一个**修正指令**，框架将其应用于失败的节点。

---

## 7. 权限模型

### 7.1 两级执行

| 级别 | 执行时机 | 方式 |
|-------|------|-----|
| **配置级** | 工作流加载时（静态） | YAML 白名单：`allowed_tools`、`allowed_transitions` |
| **OAuth / 基于角色** | 运行时（动态） | 用户上下文：已验证用户被授权做什么？ |

### 7.2 NodePermission Schema

```yaml
# 在 workflow YAML 中按节点定义
permission:
  allowed_tools:
    - calculate_premium_api        # read: 可调用保费计算
    - payment_gateway_api          # dangerous_operation_write: 可处理支付
    - vector_search_mcp            # read: 可查询知识库
  allowed_transitions:
    - assess_risk
    - manual_review
    - generate_quote               # 可路由到这些状态
  # deny_all_transitions_except: true   # 严格模式
```

### 7.3 工具分类

每个工具（API、MCP 服务器、命令、LLM 调用）都有元数据：

```yaml
tools:
  calculate_premium_api:
    type: api
    access_level: read
    description: "基于房产 + 承保范围数据计算保险费"
    endpoint: POST /api/v1/premium/calculate
    timeout_ms: 5000

  payment_gateway_api:
    type: api
    access_level: dangerous_operation_write
    description: "通过支付网关处理支付"
    endpoint: POST /api/v1/payment/charge
    timeout_ms: 15000
    requires_approval: true       # 人机协同关闸

  vector_search_mcp:
    type: mcp
    access_level: read
    description: "对保险知识库进行语义搜索"
    server: knowledge_base_mcp
    tool_name: search_documents

  run_risk_model_cmd:
    type: command
    access_level: read
    description: "执行风险评估模型"
    command: "python /opt/models/risk_assessment.py"
    timeout_ms: 30000
```

### 7.4 工具接口

每个工具遵循标准契约。框架在调用工具的执行函数之前检查权限。

```yaml
# 工具契约（接口）
Tool:
  name: string                                        # 唯一工具标识符
  type: api | mcp | command | llm | a2a | sdk
  access_level: read | write | sensitive_data_read | dangerous_operation_write
  metadata: ToolMeta                                  # endpoint、timeout、approval（见 §7.3）
  # execute: (params: object, context: ExecutionContext) → ToolResult
  #   框架在权限检查通过后调用此方法。

# ToolResult schema
ToolResult:
  success: boolean
  data: object
  error: string                                       # 成功时为 null
  duration_ms: integer
  audit_entry: AuditEntry                             # 框架自动生成
```

### 7.5 访问级别矩阵

| 访问级别 | 示例 | 额外控制 |
|-------------|----------|---------------|
| `read` | 向量搜索、保费计算、保单查询 | 无 |
| `write` | 保存报价、更新档案、记录事件 | 审计追踪 |
| `sensitive_data_read` | 查看 PII、医疗记录、信用评分 | OAuth scope + 审计 |
| `dangerous_operation_write` | 处理支付、取消保单、删除数据 | 人工审批关闸 + OAuth + 审计 |

### 7.6 OAuth / 基于角色的执行

在运行时，框架对每次工具调用执行两级权限检查：

1. **配置级：** 工具必须在节点的 `allowed_tools` 列表中（见 §7.2）。
2. **角色级：** 已验证用户的 OAuth scope 必须满足工具的 `access_level`。

```yaml
# 权限执行规则（每次工具调用时评估）
permission_enforcement:
  # 级别 1：静态配置 — 工具必须在节点的白名单中
  config_check:
    rule: "tool.name in node.permission.allowed_tools"
    on_violation: deny

  # 级别 2：OAuth scope 检查（运行时，按已验证用户）
  scope_requirements:
    read: []                                          # 无需 scope
    write: []                                         # 仅审计追踪，无需 scope
    sensitive_data_read: ["sensitive_data:read"]
    dangerous_operation_write: ["dangerous_operation:write"]

  # 危险操作的人机协同关闸
  approval_gate:
    condition: "tool.metadata.requires_approval == true"
    action: await_human_approval                      # 阻塞直到审批通过
```

### 7.7 转移权限

节点也限制它们可以转移到哪些其他节点。框架在每次状态转移时强制执行此规则：

```yaml
# 转移权限执行（每次转移时评估）
transition_enforcement:
  rule: "to_node in from_node.permission.allowed_transitions"
  on_violation:
    error: TRANSITION_DENIED
    message: "节点 '{{from_node}}' 无法转移到 '{{to_node}}'。允许的转移: {{allowed_transitions}}"
```

---

## 8. 待决问题

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | LLM（在选项 B 决策节点中）如何理解完整工作流上下文以做出正确决策？Prompt 构建？基于 Skill 的注入？ | LLM 决策可靠性 |
| 2 | 子工作流是否应支持递归（子工作流调用另一个子工作流）？ | 工作流复杂度 |
| 3 | 重试预算应是累积的还是按节点的？（即全局对话级重试预算 + 按节点分配） | 资源管理 |
| 4 | 对于 OAuth 执行，框架应集成特定提供方（Auth0、Okta）还是暴露通用接口？ | 集成面 |
| 5 | 如何处理敏感数据工具结果 — 自动编辑？单独的审计通道？ | PII 合规 |
| 6 | 框架是否应支持挂起/恢复子工作流（在子工作流边界检查点）？ | 长时间运行的工作流 |
| 7 | LLM 决策评估 — 自动化 CI 管道还是每次变更手动审核？ | 质量保障流程 |
| 8 | `errorNode` — 应是单个全局节点还是可按工作流配置？ | 错误处理灵活性 |

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 父架构、框架原则、权限模型概述
- [状态机设计](./2026-06-16-state-machine-design.md) — 转移机制、状态元数据、守卫表达式
- [领域模型设计](./2026-06-17-domain-model-design.md) — 实体/状态/转移 schema
- [提取层设计](./2026-06-17-extraction-layer-design.md) — Extract/Validate/Transform 接口
- zelkim/langgraph-insurance-chatbot — 阶段感知路由模式、子工作流反模式
- Prodigal Payment Collection Agent — 按阶段重试预算、工具执行模式
