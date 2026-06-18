# LLM 网关 — 强制结构化输出接口

> 属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：为每次 LLM 交互强制执行强制结构化 JSON 输出的单一 LLM 入口点。
> **这是 "All LLM output is JSON" (VISION.md §6.3) 的执行机制。**

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-17 | 0.1.0 | 初始 LLM 网关规范 |

---

## 1. 角色

框架中的每次 LLM 调用都经过**一个网关接口**。该网关执行三条规则：

1. **`output_schema` 是强制性的** — 在不声明期望返回的 JSON 结构的情况下，无法调用 LLM
2. **框架在返回前验证响应**是否匹配 schema
3. **如果验证失败，框架会重试**（在重试预算内）— 调用方永远看不到格式错误的响应

这不是"锦上添花"或"按任务可选设置"。它是在接口层面强制执行的**硬性约束**。

```
Layer 1 (Extract)
Layer 2 (Decision)   ──→  [LLM Client Gateway]  ──→  LLM Provider (OpenAI / Anthropic / DeepSeek)
Layer 3 (Response)         ├─ schema enforcement
                            ├─ JSON validation
                            ├─ type coercion
                            └─ retry on violation
```

## 2. 接口契约

### 2.1 调用输入

```
LLMCall {
  prompt:           string | Message[]    // system + user messages
  output_schema:    JSONSchema           // MANDATORY — 响应必须匹配的结构
  temperature:      float                // 提取/决策用 0，响应生成用 0.3
  max_tokens?:      int
  provider?:        string               // "openai" | "anthropic" | "deepseek" | ...
  model?:           string               // "gpt-4o" | "claude-sonnet-4-20250514" | ...
  conversation_id?: string               // 用于追踪 / 审计
}
```

### 2.2 调用输出

```
LLMResult {
  data:       dict              // 已验证的 JSON，匹配 output_schema
  raw:        string            // LLM 原始响应（用于审计追踪）
  model:      string            // 使用了哪个模型
  usage:      TokenUsage        // tokens in / out
  attempts:   int               // 尝试次数（首次即通过则为 1）
  validated:  boolean           // 始终为 true — 网关保证
}
```

### 2.3 TokenUsage

```
TokenUsage {
  prompt_tokens:      int
  completion_tokens:  int
  total_tokens:       int
}
```

## 3. 框架保证

网关保证 **`LLMResult.data` 始终是匹配 `output_schema` 的有效 JSON** — 否则调用彻底失败（errorNode）。调用方永远不会收到部分有效或未验证的响应。

### 3.1 验证管线

```
LLM call
    │
    ├── success ──→ Step 1: Parse JSON
    │                   │
    │                   ├── valid JSON ──→ Step 2: Schema match
    │                   │                      │
    │                   │                      ├── matches schema ──→ return LLMResult
    │                   │                      └── mismatch ──→ retry (with error context)
    │                   │
    │                   └── not JSON ──→ retry (with "must output JSON" instruction)
    │
    └── provider error (timeout, 5xx) ──→ retry (within retry budget) → errorNode
```

### 3.2 验证检查

| 检查 | 内容 | 失败动作 |
|-------|------|---------------|
| **JSON 解析** | 响应是有效的 JSON | 重试，附带 "Output must be valid JSON" |
| **Schema 匹配** | 所有必填字段存在 | 重试，附带缺失字段名称 |
| **类型强制** | `"123"` → `123`，如果 schema 指定 `int` | 在安全时自动强制转换；不明确时重试 |
| **无额外字段** | 没有 schema 之外的字段 | 去除额外字段（可配置：去除 vs 报错） |

### 3.3 违规重试

```
Retry budget per LLM call:
  max_attempts:      3              // 基础重试
  +1 llm_extra:      true           // LLM 获得 +1 = 总共 4 次尝试
  backoff:           exponential    // 500ms → 1s → 2s → 4s
  on_exhausted:      errorNode      // 始终走向 errorNode
```

每次重试将验证错误注入 prompt，以便 LLM 能够自我纠正：

```
Attempt 1 → LLM 响应 {"intent": "get_quote"}    → 缺失 "confidence" 字段
Attempt 2 → LLM 响应 {"intent": "get_quote", "confidence": "high"}  → 类型错误（字符串而非数字）
Attempt 3 → LLM 响应 {"intent": "get_quote", "confidence": 0.92}    → 有效，返回
```

### 3.4 LLM +1 额外重试

根据 VISION.md §6.3，LLM 节点在基础重试预算之上获得 +1 额外重试。这由网关应用：

```
max_attempts = node.retry_budget.max_attempts + 1  // 由网关为 LLM 节点自动注入
```

## 4. 实现选项

### 选项 A：提供商原生结构化输出

将 `output_schema` 作为 `response_format` 传递给支持原生结构化输出的 LLM 提供商（OpenAI JSON 模式、Anthropic 严格模式 tool use）。LLM 自身执行 schema。

| 优势 | 提供商在生成时保证 schema；重试次数更少 |
|-----------|--------------------------------------------------------------|
| 劣势 | 仅部分提供商支持；schema 复杂度限制各有不同 |
| 最适合 | 生产环境，使用 OpenAI / Anthropic 时 |

### 选项 B：后处理验证（提供商无关）

始终不带 `response_format` 调用 LLM。在接收响应后在网关中解析并验证。适用于任何 LLM 提供商。

| 优势 | 适用于任何提供商；无 schema 复杂度限制 |
|-----------|----------------------------------------------------|
| 劣势 | 重试次数更多；LLM 可能频繁产生错误的结构 |
| 最适合 | 本地模型、Ollama、不支持结构化输出的提供商 |

### 选项 C：混合模式（默认推荐）

优先尝试选项 A。如果提供商支持 `response_format`，使用它。如果不支持，回退到选项 B。如果提供商支持 `response_format` 但 LLM 调用未通过 schema 检查（极少情况），附带丰富的错误上下文重试。

```yaml
llm:
  gateway_strategy: hybrid        # hybrid | native_only | post_process_only
  native_providers:               # 支持 response_format 的提供商
    - openai
    - anthropic
  fallback_providers:             # 仅后处理
    - ollama
    - deepseek
```

### 4.4 比较矩阵

| 维度 | 选项 A (Native) | 选项 B (Post-Process) | 选项 C (Hybrid) |
|-----------|-------------------|------------------------|-------------------|
| 提供商支持 | 有限 (OpenAI, Anthropic) | 任意提供商 | 任意，含优化 |
| 重试频率 | 低 | 中-高 | 低 |
| Schema 复杂度限制 | 取决于提供商 | 无限制 | 最佳可用 |
| 延迟 | 通常 1 次调用 | 1-4 次调用 | 通常 1 次调用 |
| 实现方式 | 利用提供商 SDK | 纯 JSON Schema 验证 | 两种 |

## 5. Schema 定义

### 5.1 JSONSchema 格式

网关接受标准 JSON Schema：

```json
{
  "type": "object",
  "properties": {
    "intent": {
      "type": "string",
      "description": "分类后的意图标签"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "置信度分数"
    },
    "reasoning": {
      "type": "string",
      "description": "LLM 对分类的推理"
    }
  },
  "required": ["intent", "confidence"]
}
```

### 5.2 YAML Schema 声明

对于工作流作者，schema 以 YAML 声明并自动转换为 JSON Schema：

```yaml
# 在工作流节点或领域模型中
output_schema:
  intent:
    type: string
    description: "分类后的意图标签"
    required: true
  confidence:
    type: number
    range: { min: 0, max: 1 }
    required: true
  reasoning:
    type: string
    required: false
```

## 6. 各层用法

### 6.1 Layer 1 — 提取

```yaml
extraction_nodes:
  collect_property_info_extract:
    executor: llm
    output_schema:          # MANDATORY — 网关强制执行
      property_type:
        type: string
        required: true
      address:
        type: string
        required: true
      building_age:
        type: number
        required: true
      floor_area:
        type: number
        required: false
```

### 6.2 Layer 2 — 决策

```yaml
decision_nodes:
  risk_triage:
    executor: llm
    output_schema:          # MANDATORY
      route:
        type: string
        enum: [auto_approve, standard_review, manual_review]
        required: true
      reason:
        type: string
        required: true
```

### 6.3 Layer 3 — 响应

```yaml
response_nodes:
  goal_setter:
    executor: llm
    output_schema:          # MANDATORY
      summary:
        type: string
        required: true
      intent:
        type: string
        required: true
      success_criteria:
        type: array
        items: { type: string }
        required: true

  goal_checker:
    executor: llm
    output_schema:          # MANDATORY
      goal_met:
        type: boolean
        required: true
      completion_percentage:
        type: number
        range: { min: 0, max: 1 }
        required: true
      gap_analysis:
        type: string
        required: true

  generate_response:
    executor: llm
    output_schema:          # MANDATORY — 即使是自由文本生成
      text:
        type: string
        required: true
      components:
        type: array
        items: { type: object }
        required: false
```

## 7. 与 errorNode 的集成

当网关耗尽所有重试尝试后仍然得到无效响应时：

```
LLM Client Gateway (retry exhausted)
    │
    ▼
errorNode ──→ strategy: retry_with_context | escalate_to_human | terminate
    │
    ▼
  audit log: { schema_violation: true, attempts: 4, last_error: "missing field 'intent'" }
```

网关在审计追踪中记录每次失败的尝试，包括 schema 违规详情。

## 8. 待解决问题

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | 网关是否应该支持流式传输（token 到达时增量验证 schema），还是仅支持全量响应验证？ | 长响应的延迟 |
| 2 | 网关是否应该缓存相同的 LLM 调用（相同 prompt + schema + model）以在开发期间降低成本？ | 成本、开发中的确定性 |
| 3 | 在不同 LLM 提供商之间具有不同 schema 能力的情况下，如何处理复杂 JSON Schema 中的 `$ref` 和 `$defs`？ | Schema 复杂度支持 |
| 4 | 网关是否应该向 LangSmith/LangFuse 发送详细的 schema 违规追踪以改进 prompt？ | 可调试性 |

---

## 参考

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — §4.3 "LLM Output is JSON — Always"，§4.1 框架原则
- [提取层](./2026-06-17-extraction-layer-design.md) — 提取/验证/转换管线，LLM 使用
- [路由与执行](./2026-06-17-routing-execution-layer-design.md) — 决策节点，errorNode，重试预算
- [响应生成](./2026-06-17-response-generation-layer-design.md) — 目标设定器，目标检查器，响应生成器
- [VISION.md](../VISION.md) — §6.3 LLM 规则，§6.5 错误处理
