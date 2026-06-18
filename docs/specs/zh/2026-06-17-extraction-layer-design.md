# 实体提取层规范

> 隶属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 覆盖范围：Layer 1（UNDERSTAND）中的实体提取、校验和转换。
> **本规范定义接口和备选实现策略 — 而非单一方案。**

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 初始实体提取层规范：提取/校验/转换管线 |
| 2026-06-17 | 0.2.0 | 重构为接口优先：每个接口提供 2+ 种实现选项 |
| 2026-06-17 | 0.3.0 | 将 Python 代码块替换为 YAML schema；在第 2.2 和 2.3 节中添加 errorNode 交叉引用；在第 3.2 节中添加 LLM JSON 守卫备注；在第 3.3 节的 StateContext 中添加 agentState.phase |
| 2026-06-17 | 0.4.0 | 第 2.3 节：为提取/转换节点添加显式 LLM +1 额外重试规则；修复第 35 行的中文文本；第 4.2 节选项 B：将 Python 表达式替换为声明式谓词描述 |

---

## 1. 角色定位

实体提取回答的问题是：*"用户提供了哪些具体数据？"*

意图分类确定的是*用户想要做什么*（例如 `get_quote`）。实体提取则从用户话语中提取结构化数据——财产类型、地址、保额——并在传递到 Layer 2（DECIDE）之前对其进行校验。

实体提取是 Layer 1（UNDERSTAND）的后半部分：

```
User Input
   |
   v
+------------------------------------+
| Layer 1: UNDERSTAND                |
|                                    |
|  Intent Classification (已完成设计)  |
|       ↓                            |
|  Entity Extraction (本文档)         |
|       Extract → Validate ← Transform|
+------------------------------------+
            |
            v
       Layer 2: DECIDE
```

## 2. 核心管线

### 2.1 三个接口

实体提取管线由三个节点接口组成。每个接口定义一份契约；具体实现按部署场景选择。

| 接口 | 职责 |
|-----------|----------------|
| **提取（Extract）** | 从用户话语中提取原始实体 |
| **校验（Validate）** | 按规则检查实体；生成通过/失败 + 错误信息 |
| **转换（Transform）** | 类型强制转换、规范化、数据补全/修正 |

### 2.2 流程

```
User Input ──→ [Extract] ──→ entities_raw
                   │
                   ↓
              [Validate] ──(all pass)──→ 输出结果到 Layer 2
                   │
                (fail)
                   │
                   ↓
              [Transform] ──(success)──→ 循环回到 [Validate]
                   │
                (fail: 已达到最大尝试次数 或 不可恢复的错误)
                   │
                   ↓
              on_transform_failure 节点 → 最终路由到 errorNode（参见路由与执行规范第 6 节）
```

### 2.3 重试门控

每个提取节点声明 `max_transform_attempts`（默认值：2）。校验→转换→校验循环最多运行该次数。**基于 LLM 的提取和转换节点在 `max_transform_attempts` 之外额外获得 +1 重试机会**（以补偿 LLM 的非确定性），这符合框架范围内的规则：所有 LLM 节点均获得 +1 重试。非 LLM 节点严格重试 `max_transform_attempts` 次。在最后一次尝试中，如果校验仍然失败，管线将路由到配置的 `on_transform_failure` 节点，该节点最终路由到 `errorNode`（参见路由与执行规范第 6 节）。

### 2.4 图拓扑

三个接口是 LangGraph 中的**独立节点** —— 而非隐藏的宏节点。

```yaml
nodes:
  - {step}_extract
  - {step}_validate
  - {step}_transform
  - {next_step}
  - {on_failure}

edges:
  {step}_extract    → {step}_validate
  {step}_validate   → {next_step}              (所有规则通过)
  {step}_validate   → {step}_transform         (任一规则失败)
  {step}_transform  → {step}_validate           (转换成功)
  {step}_transform  → {on_failure}              (转换失败)
```

### 2.5 接口定义

框架通过基于策略的工厂模式暴露节点。每个提取节点（提取/校验/转换）遵循统一的契约：

```yaml
# 提取节点协议（接口契约）
# 每个节点接收完整的 GraphState，返回更新后的 GraphState。
# 节点是无状态的 — 所有上下文存在于状态图中。
extraction_node_protocol:
  signature: (GraphState) → GraphState
  description: >
    针对当前 LangGraph 状态执行此节点。
    节点从状态图中读取并向其中写入。
    除状态变更外无任何副作用。
```

框架通过配置工作在 YAML 中按节点安装的工厂将节点接入图中：

```yaml
# 提取工厂配置（工作流 YAML 中按节点配置）
extraction_factory:
  # 策略选择决定实例化哪种实现
  extract_strategy: hybrid        # llm_primary | deterministic | hybrid
  validate_strategy: native       # durable_rules | business_rules | pyknow | native | pydantic
  transform_strategy: deterministic  # deterministic | llm_assisted | hybrid

  # 每个工厂方法签名：
  #   create_extract(strategy: string, config: dict) → ExtractionNode
  #   create_validate(strategy: string, config: dict) → ExtractionNode
  #   create_transform(strategy: string, config: dict) → ExtractionNode
  #
  # 工厂读取策略名称并实例化对应的实现类，
  # 将 YAML `config` 作为构造函数参数传入。
```

---

## 3. 提取（Extract）接口

### 3.1 契约

```
Input:
  user_input:           string              // 原始用户话语
  conversation_context: ContextWindow        // 最近 N 条消息
  extraction_rules:     ExtractionRuleSchema[] // 要查找哪些字段
  state_context:        StateContext          // FSM 状态名称 + 提示语

Output:
  entities:   Map<string, string>  // 字段名 → 原始提取值
  source:     string               // 哪个策略生成了结果
  confidence: float                // 0.0 - 1.0
  reasoning?: string               // 提取推理过程（审计追踪）
```

### 3.2 实现选项

#### 选项 A：LLM 优先 — 结构化输出（zelkim 模式）

使用 LLM 的结构化输出（JSON 模式 / 函数调用）一次性提取所有字段。依赖 LLM 的自然语言理解能力来处理多样化的表述、多轮上下文和隐式指代。

| 方面 | 详情 |
|--------|--------|
| 优势 | 处理多样化表述；理解隐式指代；多轮感知 |
| 劣势 | LLM 成本/延迟；非确定性；可能产生幻觉值 |
| 适用场景 | 开放式表单、自由文本字段、歧义输入 |
| 依赖 | LLM 提供商（OpenAI、Anthropic、本地） |
| 降级方案 | LLM 失败时 → 以较低置信度返回部分结果 |

**提示词构建：**
- 系统提示词：`extraction_rules` 描述 + `state_context.state_hint`
- 上下文：来自 `conversation_context` 的最近 N 条消息
- 输出格式：JSON，包含 field_name → value，以及 `reasoning`
- Temperature：0
- **守卫机制**：所有基于 LLM 的提取输出均为 JSON。框架在结果进入提取管线之前强制执行输出校验守卫（schema 检查、字段存在性检查、类型强制转换）。

#### 选项 B：关键字/正则 — 纯确定性（无 LLM）

仅使用确定性模式匹配提取实体。不调用 LLM。每个字段具有 `fallback_pattern`（正则）或 `fallback_keywords`（字符串列表）。

| 方面 | 详情 |
|--------|--------|
| 优势 | LLM 零成本；确定性；快速；可审计 |
| 劣势 | 在表述变化时脆弱；无法处理隐式指代 |
| 适用场景 | 结构化字段（邮编、电话、账户 ID）；合规关键用例 |
| 依赖 | 无（纯 Python `re`） |
| 降级方案 | 若无正则匹配 → 字段保持为 null |

#### 选项 C：混合 — LLM 优先 + 确定性降级（Prodigal 模式）

LLM 先提取。然后对每个具有 `fallback_pattern` 或 `fallback_keywords` 的字段执行确定性提取并合并结果。

| 方面 | 详情 |
|--------|--------|
| 优势 | 兼顾两者：LLM 处理歧义，正则保证结构化字段的精度 |
| 劣势 | LLM 成本；合并冲突解决复杂度 |
| 适用场景 | 具有混合字段类型的受监管行业 |
| 依赖 | LLM 提供商 + 规则引擎 |
| 冲突解决 | 按字段可配置：`llm_wins` / `regex_wins` / `llm_unless_confidence_below` |

**合并策略（按节点可配置）：**

```
1. 尝试 LLM 提取 → entities_llm
2. 对每个具有确定性降级方案的字段：
     运行正则/关键字 → entities_regex
3. 合并：
     complement:      entities_llm[field] ?? entities_regex[field]
     llm_wins:        entities_llm[field]   （忽略正则）
     regex_wins:      entities_regex[field] （忽略 LLM）
```

### 3.3 状态感知提示

无论选择哪种实现选项，提取节点都会接收 `StateContext`：

```
StateContext {
  state_name:        string    // 例如 "collect_property_info"
  state_description: string    // 此状态期望获取什么
  state_hint:        string    // 来自节点元数据的消歧提示
  required_fields:   string[]  // 字段名称列表
  phase:             string    // 当前 agentState.phase（例如 "collecting", "validating", "confirming"）
}
```

选项 B 和 C 使用状态上下文来限定降级规则的范围。选项 A 将其注入 LLM 提示词。

### 3.4 对比矩阵

| 维度 | 选项 A（LLM 优先） | 选项 B（确定性） | 选项 C（混合） |
|-----------|----------------------|--------------------------|-------------------|
| 成本 | $$$（每次调用 LLM） | $（免费） | $$（LLM + 计算） |
| 延迟 | ~1-3s | <1ms | ~1-3s |
| 确定性 | 低 | 高 | 中 |
| 自由文本准确度 | 高 | 低 | 高 |
| 结构化字段准确度 | 中 | 高 | 高 |
| 维护成本 | 提示词调优 | 正则维护 | 两者兼具 |
| 审计能力 | 部分（LLM 推理过程） | 完全 | 部分 |
| 部署复杂度 | 低（LLM SDK） | 极低（标准库） | 中 |

---

## 4. 校验（Validate）接口

### 4.1 契约

```
Input:
  entities:         Map<string, any>     // 来自提取（字符串）或转换（已类型化）的值
  validation_rules: ValidationRuleSchema[] // 来自节点元数据的逐字段规则

Output:
  passed:       boolean       // 所有规则均通过时为 true
  field_errors: FieldError[]  // 失败列表
```

```
FieldError {
  field:   string    // 哪个字段失败
  rule:    string    // 哪条规则失败（例如 "required", "type", "regex"）
  message: string    // 人类可读的错误信息
  value:   any       // 导致失败的值（供审计）
}
```

### 4.2 规则类型（声明式 Schema）

这些规则类型在 YAML 声明（第 6 节）中定义，与引擎无关。每种实现选项解释相同的 schema。

| 规则 | 签名 | 描述 |
|------|-----------|-------------|
| `required` | `{ required: true }` | 字段必须非空且非空字符串 |
| `type` | `{ type: "int" \| "float" \| "string" \| "date" \| "boolean" \| "enum" }` | 值必须匹配给定类型 |
| `enum` | `{ enum: [val1, val2, ...] }` | 值必须是列出的选项之一 |
| `range` | `{ range: { min?: number, max?: number } }` | 数值必须在范围内 |
| `regex` | `{ regex: "pattern" }` | 字符串值必须匹配模式 |
| `length` | `{ length: { min?: int, max?: int } }` | 字符串长度上限/下限 |
| `custom` | `{ custom: "function_name" }` | 用户提供的校验函数 |

### 4.3 实现选项

#### 选项 A：规则引擎 — 前向链式推理（durable_rules / business-rules / pyknow）

将声明式 YAML 规则编译为规则引擎的原生格式。作为前向链式规则集针对实体事实执行。

| 引擎 | 包 | 适用场景 |
|--------|---------|----------|
| `durable_rules` | `pip install durable-rules` | 前向链式、跨字段规则、when/then 推理 |
| `business_rules` | `pip install business-rules` | 轻量级、JSON/YAML 原生、简单逐字段规则 |
| `pyknow` | `pip install pyknow` | 专家系统，具有 Fact/KnowledgeEngine 模型 |

| 方面 | 详情 |
|--------|--------|
| 优势 | 跨字段规则；状态依赖规则；规则组合 |
| 劣势 | 额外依赖；学习曲线 |
| 适用场景 | 具有字段间相互依赖的复杂校验 |
| 配置 | 节点元数据中 `rule_engine: durable_rules` |

#### 选项 B：纯 Python 谓词函数

每个规则类型映射到一个简单函数。无需外部规则引擎依赖。规则在 YAML 中声明，由框架的原生谓词引擎求值：

```yaml
# 原生谓词规则定义（引擎按字段针对这些规则求值）
validation_rules:
  required:
    predicate: "value is non-null and non-empty"
  type:
    predicate: "Type match (int/float/string/date/boolean/enum)"
  enum:
    predicate: "value is one of the listed options"
  range:
    predicate: "value is within numeric range (min <= value <= max)"
  regex:
    predicate: "value matches the given regex pattern"
  length:
    predicate: "string length is within bounds (min <= length <= max)"
  custom:
    predicate: "user-provided validation function passes"
```

| 方面 | 详情 |
|--------|--------|
| 优势 | 零依赖；简单；可调试 |
| 劣势 | 无跨字段规则；无推理；组合能力有限 |
| 适用场景 | 简单逐字段检查；最小化部署 |
| 配置 | 节点元数据中 `rule_engine: native` |

#### 选项 C：Schema 校验器 — Pydantic / dataclass

将实体定义为具有内置校验器的结构化 schema。框架在运行时将 YAML 声明映射到类型安全的校验模型：

```yaml
# Schema 声明（在运行时映射到类型安全的校验器）
# 框架从此声明生成校验逻辑。
schema:
  PropertyInfo:
    fields:
      property_type:
        type: enum
        allowed: [apartment, house, villa]
      address:
        type: string
        min_length: 5
      postal_code:
        type: string
        pattern: "^[0-9]{6}$"
      building_age:
        type: int
        range: { min: 0, max: 200 }
      floor_area:
        type: float
        range: { min: 1, max: 100000 }
        required: false
```

| 方面 | 详情 |
|--------|--------|
| 优势 | 类型安全；IDE 支持；内置序列化 |
| 劣势 | Schema 是代码（非 YAML）；跨字段校验器冗长；动态 schema 较难 |
| 适用场景 | Python 原生项目，在开发时已知 schema |
| 配置 | 节点元数据中 `rule_engine: pydantic` |

### 4.4 对比矩阵

| 维度 | 选项 A（规则引擎） | 选项 B（谓词） | 选项 C（Pydantic） |
|-----------|----------------------|---------------------|---------------------|
| 跨字段规则 | 是（when/then） | 否（手动） | 是（root_validator） |
| 状态依赖规则 | 是 | 否 | 否 |
| 外部依赖 | 1 个 pip 包 | 0 | 1 个 pip 包 |
| Schema 在 YAML 中 | 是 | 是 | 否（仅代码） |
| 动态 schema | 是 | 是 | 有限 |
| 学习曲线 | 中 | 低 | 低 |
| 推理速度 | 中 | 快 | 快 |

---

## 5. 转换（Transform）接口

### 5.1 契约

```
Input:
  entities:          Map<string, string>  // 来自提取的原始值
  validation_errors: FieldError[]         // 哪些字段校验失败
  transform_rules:   TransformRuleSchema[] // 逐字段转换规则

Output:
  entities:         Map<string, any>     // 转换后的值
  success:          boolean              // 若有字段不可恢复则为 false
  transform_errors: TransformError[]     // 不可恢复的错误
```

### 5.2 转换操作类型

| 操作 | 描述 | 示例 |
|-----------|-------------|---------|
| `cast` | 类型强制转换 | `"12/27" → Date(2027-12-01)` |
| `normalize` | 字符串清理 | `trim`、`lowercase`、`strip_symbols` |
| `parse` | 命名解析器 | `parse_date`、`parse_currency`、`parse_phone` |
| `lookup` | 值映射 | `"BJ" → "Beijing"` |
| `default` | 为空时的回退值 | `null → 0.0` |
| `llm_correct` | LLM 辅助修正近乎有效的值 | `"Nisaan" → "Nissan"` |
| `llm_complete` | LLM 辅助推断缺失字段 | 从地址推断邮编 |
| `external` | 调用外部 API/服务 | 邮编 → 城市查询 |

### 5.3 实现选项

#### 选项 A：声明式规则管线

转换规则作为有序管线逐字段执行。纯确定性（无 LLM）。操作包括 `cast`、`normalize`、`parse`、`lookup`、`default`、`external`。

| 方面 | 详情 |
|--------|--------|
| 优势 | 确定性；可审计；无 LLM 成本 |
| 劣势 | 无法处理歧义或隐式数据 |
| 适用场景 | 类型强制转换、规范化、查找表 |
| 依赖 | 无（或针对 `external` 操作的外部 API） |

#### 选项 B：LLM 辅助转换

转换对 `llm_correct` 和 `llm_complete` 操作使用 LLM。Temperature = 0。

- **`llm_correct`**：原始值接近但无效（例如 "Nisaan" → "Nissan"）。LLM 接收原始值 + 校验错误 + 预期格式。
- **`llm_complete`**：字段为空但可从其他字段 + 会话上下文推断（例如 街道 + 城市 → 邮编）。

| 方面 | 详情 |
|--------|--------|
| 优势 | 处理近似错误；可推断隐式数据 |
| 劣势 | LLM 成本/延迟；非确定性 |
| 适用场景 | 自由文本修正、智能补全 |
| 依赖 | LLM 提供商 |

#### 选项 C：混合 — 规则管线 + LLM 降级

确定性规则先执行。若失败（不可恢复），则调用 LLM 作为最后手段。

执行顺序：

```
1. cast → normalize → parse → lookup → default → external
2. 若仍无效 → llm_correct
3. 若仍为空且必填 → llm_complete
```

| 方面 | 详情 |
|--------|--------|
| 优势 | 结合确定性与 LLM 灵活性；仅在需要时调用 LLM |
| 劣势 | 管线更复杂；LLM 仍有延迟 |
| 适用场景 | 大多数生产用例 |
| 依赖 | 规则引擎 + LLM 提供商 |

### 5.4 对比矩阵

| 维度 | 选项 A（确定性） | 选项 B（LLM 辅助） | 选项 C（混合） |
|-----------|------------------------|------------------------|-------------------|
| 成本 | $ | $$$ | $$ |
| 延迟 | <10ms | ~1-3s（LLM 调用） | <10ms 典型，~1-3s 降级 |
| 确定性 | 高 | 低 | 中 |
| 处理近似错误 | 有限 | 良好 | 良好 |
| 处理缺失数据 | 仅默认值 | 推断 | 默认值 → 推断 |
| 复杂度 | 低 | 低 | 中 |
| 审计能力 | 完全 | 部分 | 部分 |

---

## 6. 节点元数据 Schema

YAML 中的每个提取节点携带自身的 `extraction_rules`、`validation_rules` 和 `transform_rules`。这些 schema 是所有实现选项所消费的**接口契约**。

### 6.1 提取规则 Schema

```
ExtractionRuleSchema {
  field:              string              // 字段名称
  description:        string              // 指导 LLM 提取
  type:               string              // 转换后的预期类型
  required:           boolean             // 若为 null 则触发校验
  fallback_pattern?:  string              // 确定性降级正则
  fallback_keywords?: string[]            // 关键字触发的降级方案
  examples?:          string[]            // LLM 提示词的少样本示例
}
```

### 6.2 校验规则 Schema

```
ValidationRuleSchema {
  field:     string                // 字段名称
  required?: boolean
  type?:     "int" | "float" | "string" | "date" | "boolean" | "enum"
  enum?:     string[]
  range?:    { min?: number, max?: number }
  regex?:    string
  length?:   { min?: int, max?: int }
  custom?:   string                // 已注册的函数名称
}
```

### 6.3 转换规则 Schema

```
TransformRuleSchema {
  field:  string              // 字段名称
  rules:  TransformOperation[] // 有序操作列表
}

TransformOperation {
  type:   "cast" | "normalize" | "parse" | "lookup" | "default" | "llm_correct" | "llm_complete" | "external"
  config: Record<string, any>  // 类型特定的配置
}
```

### 6.4 完整节点示例（YAML）

```yaml
extraction_nodes:
  collect_property_info_extract:
    extract_strategy: hybrid      # 选项 A: llm_primary | 选项 B: deterministic | 选项 C: hybrid
    validate_strategy: durable_rules  # 选项 A: durable_rules | business_rules | pyknow
                                       # 选项 B: native | 选项 C: pydantic
    transform_strategy: hybrid    # 选项 A: deterministic | 选项 B: llm_assisted | 选项 C: hybrid
    state_hint: >
      用户正在提供房屋保险报价所需的财产信息。
      地址可能包含街道、城市、省份、邮编。
      建筑年龄以年为单位。
    context_window_size: 6
    max_transform_attempts: 2
    on_transform_failure: ask_missing_property_info

    extraction_rules:
      - field: property_type
        description: "Type of property (apartment, house, villa)"
        type: enum
        required: true
        fallback_keywords: [apartment, house, villa, condo, flat]
        examples: ["I live in a house", "a 3-bedroom apartment"]
      - field: postal_code
        description: "6-digit postal code"
        type: string
        required: true
        fallback_pattern: "\\b[0-9]{6}\\b"
      - field: building_age
        description: "Age of the building in years"
        type: int
        required: true
        examples: ["built in 2010", "15 years old"]
      - field: floor_area
        description: "Floor area in square meters"
        type: float
        required: false
        fallback_pattern: "\\b([0-9]+(?:\\.[0-9]+)?)\\s*(?:sqm|m2|square\\s*meters?)"

    validation_rules:
      property_type:
        required: true
        enum: [apartment, house, villa]
      postal_code:
        required: true
        regex: "^[0-9]{6}$"
      building_age:
        required: true
        type: int
        range: { min: 0, max: 200 }
      floor_area:
        type: float
        range: { min: 1, max: 100000 }

    transform_rules:
      property_type:
        - type: normalize
          config: { op: lowercase }
        - type: lookup
          config:
            mapping:
              condo: apartment
              flat: apartment
              "single family": house
      building_age:
        - type: cast
          config: { to: int }
        - type: llm_correct
          config:
            prompt: >
              将建筑年龄转换为整数年。"built in 2010" → current_year - 2010。
              "new" → 0。当前值：{value}
      floor_area:
        - type: cast
          config: { to: float }
```

### 6.5 策略配置参考

```yaml
# 节点级策略选择
extract_strategy:    llm_primary | deterministic | hybrid
validate_strategy:   durable_rules | business_rules | pyknow | native | pydantic
transform_strategy:  deterministic | llm_assisted | hybrid

# 若选择规则引擎，指定哪一个
rule_engine:   durable_rules | business_rules | pyknow   # 仅在 validate_strategy 为其中之一时

# 自定义实现
custom_engine:   my_package.MyEngine                      # 用户提供的 RuleEngine 实现
```

---

## 7. 与意图分类的集成

### 7.1 Layer 1 数据流

```
User Input
   |
   v
[Intent Classification]  →  intent_label, confidence, source
   |
   v
[State Machine]           →  决定激活哪个提取节点
   |
   v
[Extract]                 →  entities_raw
   |
   v
[Validate]                →  entities_validated OR field_errors
   |
   v
[Transform] (条件执行)     →  entities_transformed（循环回到校验）
   |
   v
Layer 2: DECIDE
```

### 7.2 意图 → 提取路由

1. **意图门控提取节点**：状态机使用意图标签选择激活哪个提取节点。`get_quote` 路由到 `collect_property_info_extract`；`file_claim` 路由到 `file_claim_extract`。

2. **意图可能跳过提取**：若意图为 `unrecognized_intent` 或 `ask_question`，完全跳过提取，直接路由到澄清或问答节点。

---

## 8. 模式：两阶段提取

用于提取 schema 依赖于前置决策的场景（例如 车险 vs 房屋保险）：

```
阶段 1：
  [Extract(type_classifier)] → [Validate] → 状态机选择提取 schema

阶段 2：
  [Extract(type_specific_fields)] → [Validate] → [Transform] → [Validate]
```

这镜像了 zelkim 的两阶段动态 schema 模式。阶段 1 使用最小提取 schema（仅类型）。阶段 2 使用按分类类型限定的 schema。

每个阶段是一个独立的提取/校验/转换管线，具有各自的策略配置。

---

## 9. 边界情况

### 9.1 部分提取

提取返回部分而非全部必填字段 → 校验捕获缺失字段 → 转换的 `llm_complete`（选项 B/C）可能推断它们。若不可恢复 → `on_transform_failure`。

### 9.2 冗余信息

用户提供的信息包含当前节点未请求的字段。提取仍然可能捕获它们。框架将额外数据存储在状态图中，供下游节点潜在使用。

### 9.3 工作流中途的字段值修正

用户修正先前填写的字段（"等等，地址不是 X，是 Y"）。提取中的会话上下文捕获新值。累积的 `collectedFields` 被覆盖。

### 9.4 歧义值

当原始值可能映射到多个有效选项时（例如 "basic" = `coverage_level` 或 `deductible`），`state_hint` 进行消歧。若歧义持续存在，校验报告错误 → 转换修正 或 失败节点要求澄清。

---

## 10. 未决问题

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | 转换是否应为基于 LLM 的操作维护独立于 `max_transform_attempts` 的重试预算？ | 成本控制 |
| 2 | 提取结果是否应按会话轮次缓存，以避免重放/恢复时重新提取？ | 确定性、成本 |
| 3 | `llm_complete` 可接受的推断边界是什么？是否应调用外部 API 来填补空白？ | 数据准确性、延迟 |
| 4 | 跨字段校验（例如 `end_date > start_date`）— 在 YAML schema 中表达还是仅通过规则引擎？ | 规则表达能力 |
| 5 | 提取和校验后的实体是否应在 Layer 2 消费之前持久化？ | 审计能力、重放 |
| 6 | LLM 提供商在提取中途不可用 — 降级到选项 B（确定性）还是排队？ | 可用性 |
| 7 | `ExtractionFactory` 是否应支持降级链？（例如 尝试选项 C → 若 LLM 超时，降级到选项 B） | 韧性 |

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 父级架构文档
- [意图分类设计](./2026-06-16-intent-classification-design.md) — Layer 1 意图分类
- [状态机设计](./2026-06-16-state-machine-design.md) — 状态上下文注入、意图+状态解析
- [房屋保险工作流](../../examples/home-insurance/workflow.yaml) — 参考提取规则
- zelkim/langgraph-insurance-chatbot — 两阶段动态 schema + LLM 结构化输出模式
- Prodigal Payment Collection Agent — 混合 LLM + 逐槽正则降级模式
