# 领域模型规范

> 隶属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 覆盖范围：作为实体、状态和转换的单一事实来源的领域模型。
> **本规范定义 schema 和接口 — 而非单一方案。**

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 初始领域模型规范：实体 + 状态 + 转换 schema |
| 2026-06-17 | 0.2.0 | 添加实现选项（扁平 vs 嵌套 vs 代码优先）；agentState.phase 映射；errorNode 作为标准转换目标 |
| 2026-06-17 | 0.3.0 | 添加第 1.1 节：实现方案（扁平 YAML vs 嵌套/层次化 vs 代码优先） |
| 2026-06-18 | 0.4.0 | 将 §6（重复的守卫表达式语法）替换为交叉引用至权威的 [State Machine Design §3.4](./2026-06-16-state-machine-design.md)；守卫表达式关注点委托给状态机规范 |

---

## 1. 角色定位

领域模型是确定性工作流的**单一事实来源**。它定义了工作流操作*什么*——数据实体、有效状态和转换规则——独立于框架*如何*执行提取、校验或路由。

```
领域模型 (WHAT)                   工作流配置 (HOW)
────────────────────────          ──────────────────────
实体 + 字段 + 类型                extraction_strategy
状态 + state_hint                  validate_strategy
转换 + 守卫条件                   transform_strategy
                                    context_window_size
                                    max_transform_attempts
                                    on_transform_failure
```

**分离原则：** 领域模型可跨工作流和产品重用。工作流配置在此基础上添加运行时策略选择。这种分离使得：

1. **跨工作流重用** — `property_info` 实体可同时在 `home_insurance_quote` 和 `home_insurance_refinance` 中使用
2. **产品无关模型** — 同一领域模型可跨不同实现使用
3. **技能驱动的生成** — 下游技能可通过访谈开发者来填充领域模型，然后框架为"如何"部分提供合理的默认值

### 1.1 实现方案

编写领域模型的三种架构选项。三者共享相同的实体/状态/转换 schema；区别在于定义*如何*组织和维护。

#### 选项 A：扁平 YAML 领域模型（当前方案）

实体定义为扁平的字段列表。每个字段是实体下的顶级键。不支持嵌套或复合字段。

```yaml
entities:
  property_info:
    fields:
      property_type: { type: enum, values: [apartment, house, villa] }
      address:       { type: string, required: true }
      postal_code:   { type: string, pattern: "^[0-9]{6}$" }
      building_age:  { type: int, range: { min: 0, max: 200 } }
```

**优点：** 读写简单。工具化直接——每个字段是单个键。LLM 提取提示词与字段描述一一映射。

**缺点：** 无法表示复合数据（例如 `address` 为 `{street, city, province, postal_code}`）。实体 schema 随规模增长会变得扁平且难以管理。

#### 选项 B：嵌套/层次化领域模型

实体支持复合字段。一个字段可包含子字段，从而实现结构化的嵌套数据。

```yaml
entities:
  property_info:
    fields:
      property_type: { type: enum, values: [apartment, house, villa] }
      address:
        type: object
        required: true
        fields:
          street:      { type: string, required: true }
          city:        { type: string, required: true }
          province:    { type: string, required: true }
          postal_code: { type: string, pattern: "^[0-9]{6}$" }
      building_age: { type: int, range: { min: 0, max: 200 } }
```

**优点：** 自然地对结构化数据建模（地址、具有 first_name/last_name 的个人信息、带有嵌套覆盖范围的保单详情）。LLM 提取可独立针对子字段。校验规则按子字段应用。

**缺点：** YAML 结构更复杂。工具必须处理递归字段展开。守卫表达式变得更冗长（`address.city` vs 扁平的 `city`）。

#### 选项 C：代码优先生成模型

实体定义为 Python dataclass 或 Pydantic 模型。YAML 领域模型从代码定义自动生成。

```python
from pydantic import BaseModel, Field

class PropertyInfo(BaseModel):
    property_type: Literal["apartment", "house", "villa"]
    address: str = Field(min_length=5)
    postal_code: str = Field(pattern=r"^\d{6}$")
    building_age: int = Field(ge=0, le=200)
```

```yaml
# 自动生成的领域模型 YAML
entities:
  property_info:
    fields:
      property_type: { type: enum, values: [apartment, house, villa], required: true }
      address:       { type: string, required: true, min_length: 5 }
      postal_code:   { type: string, required: true, pattern: "^\\d{6}$" }
      building_age:  { type: int, required: true, range: { min: 0, max: 200 } }
```

**优点：** 完整的 IDE 支持（自动补全、类型检查、重构）。校验逻辑是原生 Python。Pydantic 的内置序列化生成适合 LangGraph 状态的结构化输出。

**缺点：** 需要代码生成步骤。非 Python 开发者无法编写或审阅领域模型。生成的 YAML 可能不如手工编写的 YAML 可读。

### 对比矩阵

| 维度 | 选项 A：扁平 YAML | 选项 B：嵌套 YAML | 选项 C：代码优先 |
|-----------|-------------------|----------------------|----------------------|
| **复杂度** | 低 — 扁平的键值对 | 中 — 递归字段结构 | 中高 — 需要 Python + 代码生成 |
| **可读性** | 高 — 简单、扁平的结构 | 中 — 嵌套增加了深度，但对复合数据更清晰 | 低 — 事实来源是 Python，非 YAML |
| **工具支持** | 高 — 简单 YAML 解析 | 中 — 需要递归处理 | 高 — Pydantic 生态、IDE 支持 |
| **动态 Schema 支持** | 低 — 仅扁平 | 高 — 嵌套字段匹配真实数据 | 中 — Pydantic 支持嵌套模型 |
| **IDE 支持** | 低 — 原始 YAML | 低 — 原始 YAML | 高 — 完整 Python 类型检查、自动补全 |

**默认推荐：选项 A（扁平 YAML）适用于大多数用例。当实体包含复合字段（如地址或带有子字段的个人信息）时使用选项 B（嵌套 YAML）。选项 C（代码优先）适用于偏好 Python 原生开发且不需要非开发者利益相关者审阅领域模型的团队。**

## 2. 领域模型 Schema

领域模型定义在独立的 YAML 文件中：

```
DomainModel {
  domain:      string              // 唯一标识符（例如 "home_insurance"）
  version:     string              // 语义化版本
  description: string              // 人类可读的领域描述
  entities:    Map<string, EntityDef>  // 此领域中的数据实体
  states:      Map<string, StateDef>   // 工作流状态
  transitions: TransitionDef[]         // 允许的状态转换
}
```

### 2.1 文件位置

```
docs/domain-models/
  home-insurance.yaml
  banking-kYC.yaml
  healthcare-intake.yaml
```

### 2.2 注册

领域模型全局注册。工作流通过 `domain` 名称引用它们：

```yaml
# workflow.yaml
workflow: home_insurance_quote
domain_model: home-insurance          # 引用 docs/domain-models/home-insurance.yaml
```

---

## 3. 实体定义

### 3.1 EntityDef Schema

```
EntityDef {
  name:        string              // 实体名称（例如 "property_info"）
  description: string              // 指导 LLM 提取 + 文档
  fields:      Map<string, FieldDef> // 有序字段定义
}
```

### 3.2 FieldDef Schema

```
FieldDef {
  type:        string              // "string" | "int" | "float" | "date" | "boolean" | "enum" | "list"
  required:    boolean             // true → null 会触发校验错误
  description: string              // 指导 LLM 提取
  values?:     string[]            // 有效值（针对 type: enum）
  range?:      { min?: number, max?: number }  // （针对 type: int, float）
  pattern?:    string              // 正则模式（针对 type: string）
  min_length?: int                 // 最小字符串长度
  deterministic_fallback?: {       // 确定性提取降级方案
    keywords?: string[]
    regex?:    string
    priority?: "llm_wins" | "regex_wins"
  }
  transform?:  TransformOp[]       // 类型强制转换 / 规范化管线
  examples?:   string[]            // LLM 提示词的少样本示例
}

TransformOp {
  type:   "cast" | "normalize" | "parse" | "lookup" | "default" | "external"
  config: Record<string, any>      // 类型特定的配置
}
```

### 3.3 类型系统

| 类型 | 校验规则 | 转换（默认） |
|------|-----------|---------------------|
| `string` | 若必填则非空 | `trim` |
| `int` | 整数，可选范围 | `cast: int` |
| `float` | 数值，可选范围 | `cast: float` |
| `date` | ISO 8601 格式 | `parse: date` |
| `boolean` | true/false/yes/no/1/0 | `cast: boolean` |
| `enum` | 必须在 `values[]` 中 | `normalize: lowercase` + `lookup` |
| `list` | 数组项 | `split: ","` |

### 3.4 示例：home-insurance 领域

```yaml
domain: home_insurance
version: 1.0.0
description: "Home insurance quote, claim, and policy management"

entities:
  property_info:
    description: "Property information for home insurance"
    fields:
      property_type:
        type: enum
        values: [apartment, house, villa]
        required: true
        description: "Type of property being insured"
        examples: ["I live in a house", "3-bedroom apartment", "my villa"]
        deterministic_fallback:
          keywords: [apartment, house, villa, condo, flat]
        transform:
          - type: normalize
            config: { op: lowercase }
          - type: lookup
            config:
              mapping:
                condo: apartment
                flat: apartment
                "single family": house

      address:
        type: string
        required: true
        description: "Full address including street, city, province, postal code"
        min_length: 5

      postal_code:
        type: string
        required: true
        description: "6-digit postal code"
        pattern: "^[0-9]{6}$"
        deterministic_fallback:
          regex: "\\b[0-9]{6}\\b"
          priority: regex_wins

      building_age:
        type: int
        required: true
        description: "Age of the building in years"
        range: { min: 0, max: 200 }
        examples: ["built in 2010", "15 years old", "brand new"]
        transform:
          - type: cast
            config: { to: int }

      floor_area:
        type: float
        required: false
        description: "Floor area in square meters"
        range: { min: 1, max: 100000 }
        transform:
          - type: cast
            config: { to: float }

      construction_material:
        type: enum
        values: [brick, concrete, wood_frame, steel]
        required: false
        description: "Primary construction material"

  coverage_needs:
    description: "Coverage requirements for a quote"
    fields:
      coverage_type:
        type: enum
        values: [building_only, contents_only, both]
        required: true
        description: "What type of coverage the user wants"

      building_coverage:
        type: float
        required: true
        description: "Coverage amount for building (CNY)"
        range: { min: 0 }

      contents_coverage:
        type: float
        required: false
        description: "Coverage amount for contents (CNY)"
        range: { min: 0 }

      deductible:
        type: enum
        values: [low, standard, high]
        required: true
        description: "Deductible preference"

      riders:
        type: list
        required: false
        description: "Additional rider coverage (fire, theft, water_damage, earthquake, liability)"

  claim_details:
    description: "Claim filing information"
    fields:
      incident_type:
        type: enum
        values: [fire, water_damage, theft, natural_disaster, other]
        required: true
        description: "Type of incident being claimed"

      incident_date:
        type: date
        required: true
        description: "Date the incident occurred"

      damage_description:
        type: string
        required: true
        description: "Description of the damage"

      estimated_loss:
        type: float
        required: true
        description: "Estimated loss amount (CNY)"
        range: { min: 0 }
```

---

## 4. 状态定义

### 4.1 StateDef Schema

```
StateDef {
  name:         string    // 状态名称（例如 "collect_property_info"）
  description:  string    // 人类可读的描述，说明此状态期望获取什么
  entity:       string    // 此状态提取哪个实体（引用 EntityDef.name）
  state_hint:   string    // 注入 LLM 提取提示词的消歧提示
  max_retries?: int       // 升级前的最大重试次数（默认值：来自框架配置）
}
```

### 4.2 状态 → 实体绑定

每个状态恰好绑定到一个实体。框架使用此绑定来：

1. 从实体的 `FieldDef[]` 生成 `ExtractionRule[]`
2. 从字段类型、必填标志、模式和范围生成 `ValidationRule[]`
3. 从字段 `transform` 声明生成 `TransformRule[]`
4. 在此状态下提取数据时将 `state_hint` 注入 LLM 提示词

### 4.3 示例

```yaml
states:
  collect_property_info:
    description: "Collect property details from the user"
    entity: property_info
    state_hint: >
      用户正在提供房屋保险报价所需的财产信息。
      地址可能包含街道、城市、省份、邮编。
      建筑年龄以年为单位。"全新" 或 "新建" 表示年龄为 0。

  collect_coverage_needs:
    description: "Collect coverage preferences"
    entity: coverage_needs
    state_hint: >
      用户正在选择保障类型和金额。
      免赔额选项：low（500 CNY）、standard（2000 CNY）、high（5000 CNY）。

  file_claim:
    description: "File a new claim"
    entity: claim_details
    state_hint: >
      用户正在报告理赔事件。
      事件类型必须是以下之一：fire、water_damage、theft、natural_disaster、other。
      日期应为 YYYY-MM-DD 格式。
```

### 4.4 StateDef.name → agentState.phase 映射

在运行时，框架将每个 `StateDef.name` 映射到共享状态对象上的 `agentState.phase` 字段。此映射是直接且自动的：

```
# 领域模型状态定义
states:
  collect_property_info:
    ...

# 运行时行为
agentState.phase = "collect_property_info"
```

`agentState.phase` 值用于以下方面：
- **LangGraph 条件边** — 根据当前阶段路由到正确的节点
- **子工作流调度** — 将当前阶段匹配到子工作流处理器
- **审计/日志记录** — 记录每个步骤中会话所处的阶段
- **恢复** — 恢复会话时，存储的阶段决定重新进入哪个状态

无需显式的映射配置。框架在领域模型加载期间（框架消费流程的第 3 步）从 `StateDef.name` 推导出阶段值。

---

## 5. 转换定义

### 5.1 TransitionDef Schema

```
TransitionDef {
  from:      string    // 源状态名称
  to:        string    // 目标状态名称
  guard:     string    // 守卫表达式（参见第 6 节）
  priority?: int       // 值越高越先检查（用于冲突解决）
  label?:    string    // 可选的文档标签 / 条件边命名
}
```

### 5.2 转换语义

- **自循环**：`from: collect_property_info, to: collect_property_info, guard: "context_incomplete"` — 保持在当前状态直到所有必填字段均已填写
- **前进**：`from: collect_property_info, to: assess_risk, guard: "property_type != null AND address != null AND building_age != null"` — 当实体字段完成时向前移动
- **条件分支**：来自同一状态且守卫不重叠的多个转换决定下一个状态

### 5.3 冲突解决

当来自同一状态的多个转换的守卫条件可能同时为真时：

1. **优先级排序** — 较高 `priority` 值优先检查
2. **首次匹配胜出** — 第一个求值为真的守卫决定转换
3. **不可达回退** — 若所有守卫均失败，框架使用 `on_nomatch` 转换（需显式定义，或使用 `on_transform_failure` 节点）

### 5.4 示例

```yaml
transitions:
  # 报价流程
  - from: collect_property_info
    to: collect_coverage_needs
    guard: "property_type != null AND address != null AND building_age != null"
    label: "property_info_complete"
    priority: 10

  - from: collect_property_info
    to: collect_property_info
    guard: "context_incomplete"
    label: "still_collecting"
    priority: 5

  - from: collect_coverage_needs
    to: assess_risk
    guard: "coverage_type != null AND building_coverage != null"
    label: "coverage_needs_complete"

  - from: collect_coverage_needs
    to: collect_coverage_needs
    guard: "context_incomplete"

  # 理赔流程
  - from: file_claim
    to: validate_claim
    guard: "incident_type != null AND incident_date != null AND estimated_loss != null"

  - from: file_claim
    to: file_claim
    guard: "context_incomplete"
```

### 5.5 保留的转换目标：`errorNode`

转换目标名称 `errorNode` 是为错误处理保留的。行为如下：

- **始终可达**：任何状态都可以转换到 `errorNode`，无论其显式转换允许列表如何。无需在领域模型中声明 `to: errorNode` 的转换规则。
- **自动路由**：当提取、校验或转换失败且重试次数用尽时，框架自动将会话路由到 `errorNode`。
- **升级路径**：`errorNode` 作为兜底的升级路径。可按工作流配置（例如 转接给人工客服、记录失败、优雅终止）。
- **请勿声明**：请勿在领域模型中声明 `errorNode` 为状态。它是框架级的原语，而非领域状态。

```yaml
# 无需在转换中声明此项：
# transitions:
#   - from: collect_property_info
#     to: errorNode       # ← 不需要；errorNode 始终可达
```

`errorNode` 由框架解析（消费流程的第 6 步），并注入到 LangGraph 状态机中，与领域定义的状态并列。

---

## 6. 守卫表达式语法

守卫是针对当前实体状态求值的布尔表达式。**权威的守卫表达式语法** — 包括布尔运算符、比较运算符、列表成员检查、空值检查、框架生成的元变量以及自然语言回退 — 定义在 [State Machine Design §3.4 守卫表达式语法](./2026-06-16-state-machine-design.md)。

领域模型在 `TransitionDef` 条目中使用守卫来确定工作流进入的下一个状态。框架在运行时使用状态机的表达式求值器来求值守卫。对于复杂的业务规则，守卫可以委托给自定义守卫函数或规则引擎（参见 State Machine Design §3.4）。

---

## 7. 与工作流 YAML 的关系

### 7.1 合并策略

在框架启动时，领域模型和工作流配置被合并：

```
领域模型（实体/状态/转换 schema）
         +
工作流配置（策略选择、运行时参数）
         ↓
框架解析为具体的 ExtractionNode / ValidateNode / TransformNode 实例
```

### 7.2 工作流配置新增的内容

| 由谁配置 | 领域模型 | 工作流配置 |
|---------------|-------------|-----------------|
| 实体字段 schema | ✅ | — |
| 状态定义 | ✅ | — |
| 转换守卫 | ✅ | — |
| 状态提示 | ✅ | — |
| 提取策略 | — | ✅ |
| 校验策略 | — | ✅ |
| 转换策略 | — | ✅ |
| 规则引擎选择 | — | ✅ |
| 上下文窗口大小 | — | ✅ |
| 最大转换尝试次数 | — | ✅ |
| 失败时路由 | — | ✅ |

### 7.3 示例：引用领域模型

```yaml
# workflow_home_insurance_quote.yaml
workflow: home_insurance_quote
domain_model: home-insurance        # 加载 docs/domain-models/home-insurance.yaml

nodes:
  collect_property_info_extract:
    entity: property_info
    extract_strategy: hybrid
    validate_strategy: durable_rules
    transform_strategy: hybrid
    context_window_size: 6
    max_transform_attempts: 2
    on_transform_failure: ask_missing_property_info

  collect_coverage_needs_extract:
    entity: coverage_needs
    extract_strategy: hybrid
    validate_strategy: durable_rules
    transform_strategy: hybrid
    on_transform_failure: ask_missing_coverage
```

---

## 8. 跨工作流重用

领域模型全局注册。多个工作流可以以不同的策略配置引用它。

```
domain-models/home-insurance.yaml
    ├── workflow_home_insurance_quote.yaml     (extract_strategy: hybrid)
    ├── workflow_home_insurance_refinance.yaml  (extract_strategy: llm_primary)
    └── workflow_home_insurance_renewal.yaml    (extract_strategy: deterministic)
```

### 8.1 版本控制

领域模型使用语义化版本控制。工作流固定到某个版本：

```yaml
domain_model: home-insurance@1.2.0
```

对实体 schema 的破坏性更改（字段删除、类型变更）需要主版本号升级。

### 8.2 命名空间

当两个领域模型定义了同名的实体时，框架通过领域前缀进行消歧：

```yaml
entity: home_insurance.property_info
```

---

## 9. 框架消费流程

当框架加载引用领域模型的工作流时：

```
1. 加载领域模型 YAML → 解析实体、状态、转换
2. 加载工作流 YAML → 解析节点、策略配置
3. 对于每个状态 → 查找绑定的实体 → 将 FieldDef[] 展开为：
   a. ExtractionRule[]  （来自字段名、类型、描述、deterministic_fallback、examples）
   b. ValidationRule[]  （来自字段 required、type、pattern、range、min_length）
   c. TransformRule[]   （来自字段 transform）
4. 合并节点级覆盖（context_window_size、max_transform_attempts 等）
5. 通过 ExtractionFactory(strategy) 实例化提取/校验/转换节点
6. 从转换定义生成 LangGraph 节点 + 条件边
```

### 9.1 实体 → 规则展开

框架执行自动展开。例如，给定 `property_type` 字段：

```yaml
# 领域模型实体字段
property_type:
  type: enum
  values: [apartment, house, villa]
  required: true
  description: "Type of property"
  deterministic_fallback:
    keywords: [apartment, house, villa, condo, flat]
  transform:
    - type: normalize
      config: { op: lowercase }
    - type: lookup
      config: { mapping: { condo: apartment, flat: apartment, "single family": house } }
```

框架自动生成：

```
ExtractionRule {
  field: "property_type"
  description: "Type of property (apartment, house, villa)"
  type: "enum"
  required: true
  fallback_keywords: ["apartment", "house", "villa", "condo", "flat"]
}

ValidationRule {
  field: "property_type"
  required: true
  enum: ["apartment", "house", "villa"]
}

TransformRule {
  field: "property_type"
  rules: [
    { type: "normalize", config: { op: "lowercase" } },
    { type: "lookup", config: { mapping: { condo: "apartment", flat: "apartment", "single family": "house" } } }
  ]
}
```

---

## 10. 边界情况

### 10.1 可选字段 vs 必填字段

标记为 `required: false` 的字段在存在时被提取和校验，但 `context_complete` 即使在它们为 null 时也求值为 true。可选字段不阻塞状态转换。

### 10.2 跨实体数据

当状态收集 `coverage_needs`，但转换守卫引用了来自 `property_info`（在先前状态中收集）的字段时，框架会针对所有实体的累积 `collectedFields` 求值守卫。这使得类似 `"building_age > 10 AND building_coverage > 500000"` 的守卫成为可能。

### 10.3 动态实体选择

对于实体 schema 依赖于前置决策的场景（例如 车险 vs 房屋保险），使用两阶段领域模型：

```yaml
# 阶段 1 实体
insurance_type:
  fields:
    product_type:
      type: enum
      values: [auto, home, life]
      required: true

# 阶段 2 — 动态实体绑定
states:
  classify_product:
    entity: insurance_type  # 阶段 1

  collect_auto_details:
    entity: auto_info        # 仅在 product_type == "auto" 时选择

  collect_home_details:
    entity: property_info    # 仅在 product_type == "home" 时选择
```

分类状态上的转换守卫决定使用哪个实体：

```yaml
transitions:
  - from: classify_product
    to: collect_home_details
    guard: "product_type == 'home'"
  - from: classify_product
    to: collect_auto_details
    guard: "product_type == 'auto'"
```

---

## 11. 未决问题

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | 实体是否应支持嵌套/复合字段（例如 `address: { street, city, postal_code }`）？ | Schema 复杂度 |
| 2 | 领域模型是否应支持继承（例如 `auto_info extends base_insurance_info`）？ | 重用粒度 |
| 3 | 守卫表达式 — 在委托给规则引擎之前允许多大程度的表达能力？ | 语言复杂度 vs 能力 |
| 4 | 领域模型是否应包含计算字段（由代码填充，而非用户提取）？ | 实体纯度 |
| 5 | 跨领域模型引用 — `banking` 中的实体是否应引用 `kyc` 中的实体？ | 模块化 |
| 6 | 当领域模型版本变更时，正处于进行中的会话的迁移策略是什么？ | 部署安全 |

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 父级架构文档
- [实体提取层设计](./2026-06-17-extraction-layer-design.md) — 提取/校验/转换接口
- [状态机设计](./2026-06-16-state-machine-design.md) — 守卫表达式基础、意图+状态解析
- [房屋保险工作流](../../examples/home-insurance/workflow.yaml) — 参考领域模型实例化
- zelkim/langgraph-insurance-chatbot — 两阶段动态实体选择（auto vs home vs life）
