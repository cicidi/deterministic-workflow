# 状态机层设计 — transitions + LangGraph 融合

> 另见：[高层设计](./2026-06-16-deterministic-workflow-framework-design.md) 了解整体架构和非 FSM 关注点。
> 所有具体的工作流示例已提取到 [examples/home-insurance/](../../examples/home-insurance/)。

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | 初始设计：transitions 作为唯一真相来源，LangGraph 作为基础设施层 |
| 2026-06-16 | 0.2.0 | 添加状态元数据（前置条件、后置条件、守卫、不变量） |
| 2026-06-16 | 0.3.0 | 添加发票和支付用例；完整英文翻译 |
| 2026-06-16 | 0.4.0 | 添加第8节：意图+状态解析（按状态意图策略、确认流程） |
| 2026-06-16 | 0.5.0 | 将所有示例提取到 examples/home-insurance/；移除发票/支付附录；统一使用家庭保险领域 |
| 2026-06-17 | 0.6.0 | 术语一致性（errorNode、agentState.phase）；添加参考资料部分 |
| 2026-06-17 | 0.7.0 | 添加第1.1节：实现方法（纯 YAML vs 代码优先 vs 混合） |

---

## 1. 核心原则

> **transitions 定义 WHAT（业务正确性）。LangGraph 执行 HOW（对话基础设施）。**
>
> 开发者只需维护 transitions 定义。LangGraph 图、LLM 节点、检查点和中断全部自动生成。

---

## 1.1 实现方法

实现状态机层的三种架构选项。三者共享相同的 `transitions` 心智模型；区别在于定义如何编写和消费。

### 方案A：纯 YAML 声明式（当前方法）

状态和转换完全用 YAML 定义。没有代码直接接触状态图 —— 框架在启动时自动生成 LangGraph 图。

```yaml
# transitions.yaml
states:
  - name: collect_info
    executor: llm
    intent_policy:
      accept: [provide_information, ask_question]
      on_unlisted: ask_confirm
  - name: calculate_premium
    executor: code
    action: compute_premium

transitions:
  - from: collect_info
    to: calculate_premium
    guard: "context_complete"
```

**优点：** 完全可审计（YAML 人类可读），无需代码生成步骤，整个工作流作为单个 YAML 构件进行版本控制。

**缺点：** 复杂的守卫逻辑在字符串表达式中很繁琐。运行时控制流完全位于框架生成器内部。

### 方案B：代码优先 LangGraph

状态用 Python 编程定义。开发者直接构建 LangGraph 节点；框架提供辅助装饰器和基类，但不会从 YAML 生成图。

```python
from framework import StateNode, Transition, build_graph

collect_info = StateNode(
    name="collect_info",
    executor="llm",
    intent_policy={"accept": ["provide_information"], "on_unlisted": "ask_confirm"},
)

calculate_premium = StateNode(
    name="calculate_premium",
    executor="code",
    action=compute_premium,
)

collect_info >> Transition(to=calculate_premium, guard="context_complete")

graph = build_graph([collect_info, calculate_premium])
```

**优点：** 守卫可以是任意 Python 函数（`guard=lambda ctx: ctx.risk_score > 80 and ctx.amount > 5000`）。完整的 IDE 支持（自动补全、类型检查、重构）。更容易对单个节点进行单元测试。

**缺点：** 可审计性较差 —— 非技术利益相关者无法阅读状态机。图定义分散在多个 Python 文件中，而非单个声明式构件。存在命令式泄露的风险（业务逻辑与图构建混合）。

### 方案C：混合（YAML 基础 + 代码覆盖）

YAML 文件定义基础结构（状态、转换、元数据）。复杂的守卫函数、自定义验证器和工具绑定用 Python 实现，并通过名称在 YAML 中引用。

```yaml
# transitions.yaml
states:
  - name: assess_risk
    executor: code
    action: assess_risk
    exit_guard: high_risk_override  # 引用一个 Python 函数
```

```python
# guards.py
def high_risk_override(ctx: AgentState) -> bool:
    return ctx.risk_score > 80 and ctx.total_claims > 3
```

**优点：** 两全其美 —— YAML 用于结构/可审计性，Python 用于复杂逻辑。守卫保持可读性的同时支持任意复杂度。

**缺点：** 每个工作流需要维护两个构件。YAML 声明和代码实现之间存在漂移风险。

### 对比矩阵

| 维度 | 方案A：纯 YAML | 方案B：代码优先 | 方案C：混合 |
|-----------|--------------------|----------------------|------------------|
| **确定性** | 高 — 纯数据驱动 | 高 — 代码是确定性的 | 中-高 — 代码覆盖引入灵活性 |
| **开发者友好性** | 中 — YAML 简单但守卫受限 | 高 — 完整 IDE 支持、类型安全 | 中 — YAML 基础简单，代码覆盖需要纪律 |
| **可审计性** | 高 — 单个 YAML 文件，非技术人员可读 | 低 — 分散在 Python 文件中 | 中 — YAML 用于结构，Python 用于细节 |
| **灵活性** | 低 — 守卫表达式语言极简 | 高 — 守卫/验证器可用任意 Python | 中 — 受 YAML 结构约束，细节灵活 |
| **版本控制** | 优秀 — 单个 YAML diff 说明一切 | 好 — 但状态机逻辑分散在文件间 | 好 — YAML diff + 代码 diff 必须一起审查 |

**默认推荐：大多数用例使用方案A（纯 YAML）。** 当守卫逻辑对表达式语言守卫来说过于复杂时，使用方案C（混合）。方案B（代码优先）适用于偏好 Python 原生工作流且不需要非技术可审计性的团队。

---

## 2. transitions 定义格式（唯一真相来源）

> **开发者只需维护 transitions 定义。** LangGraph 图、LLM 节点、检查点和中断全部从这个单一 YAML 文件自动生成。

完整的定义格式和具体的家庭保险工作流见 [workflow.yaml](../../examples/home-insurance/workflow.yaml)。该格式支持：

- **states**：带 schema、守卫、元数据和工具允许列表的类型化节点（`executor: llm | code`）
- **transitions**：带守卫表达式和自循环的命名边
- **元变量**：框架生成的标志（`context_incomplete`、`exit_guard_pass`、`all_approved` 等），可在守卫表达式中使用

---

## 3. 状态元数据 — 前置条件 / 后置条件 / 守卫 / 不变量

每个状态可以携带5种元数据，在状态生命周期的不同节点强制执行：

```
                  +---------------------------------------+
                  |  前置条件                               |
                  |  "进入前必须为真的条件"                   |
                  |  （设计契约 — 静态验证）                  |
                  +------------------+--------------------+
                                     |
                  +------------------v--------------------+
                  |  入口守卫                                |
                  |  "门口的最终检查"                         |
                  |  （运行时 — 失败时拒绝）                   |
                  +------------------+--------------------+
                                     | 通过
              +----------------------v------------------------+
              |            状态：calculate                    |
              |                                                |
              |   +----------------------------------------+  |
              |   |  数据不变量                              |  |
              |   |  "处于此状态时必须保持的条件"              |  |
              |   |  （运行时 — 违反时断言错误）               |  |
              |   +----------------------------------------+  |
              |                                                |
              |   action: compute_premium(data)                 |
              |                                                |
              |   +----------------------------------------+  |
              |   |  出口守卫                                |  |
              |   |  "离开前的再一次检查"                     |  |
              |   |  （运行时 — 阻止转移，路由到其他地方）      |  |
              |   +------------------+---------------------+  |
              +----------------------+------------------------+
                                     | 通过
                  +------------------v--------------------+
                  |  后置条件                                |
                  |  "退出后必须为真的条件"                    |
                  |  （设计契约 — 静态验证）                   |
                  +---------------------------------------+
```

### 3.1 定义

| 概念 | 触发时机 | 失败行为 | 用途 |
|---------|---------------|------------------|---------|
| **前置条件** | 进入前 | 不阻止运行时；静态分析报告契约违反 | 用于测试生成的设计契约 |
| **入口守卫** | 进入时 | 运行时拒绝；路由到 errorNode | 运行时安全门 |
| **数据不变量** | 整个状态生命周期 | 运行时 AssertionError；中断工作流 | 运行时数据完整性保护 |
| **出口守卫** | 退出时 | 运行时阻止；路由到备用分支 | 基于计算结果的分支路由 |
| **后置条件** | 退出后 | 不阻止运行时；验证工具报告违反 | 确保动作函数输出契约 |

> **关于静态验证的说明：** 上文提到的"静态分析"和"验证工具"指计划中的 YAML linter 和测试生成器（设计待定），它读取前置条件、后置条件和不变量，在部署前捕获契约违反。此工具不在本文档范围内；相关待解决问题见附录 C.7。
>
> **关于 errorNode 的说明：** errorNode 提供统一错误处理，在路由与执行规范第6节中定义。

### 3.2 示例模式

> 关于带全部5种元数据字段的完整状态标注，见 [workflow.yaml](../../examples/home-insurance/workflow.yaml) 中的 `assess_risk` 和 `calculate_premium` 状态。以下是关键行为模式。

**守卫 vs 契约：**

```
                      守卫                            契约
                      (入口守卫 / 出口守卫)            (前置条件 / 后置条件)

  时机                运行时                            离线（静态分析 / 测试生成）
     失败行为           路由到 errorNode              标记为"契约违反"，不阻止执行
  典型用途            "age < 18 -> 直接拒绝"            "此状态声明需要 age；生成 age<18 的测试"
  表达式要求           必须可运行时求值                   可以是描述性注释或形式化公式
```

### 3.3 完整状态字段参考

```yaml
states:
  - name: <state_name>
    executor: llm | code

    # --- 状态元数据（全部可选） ---
    precondition:     "表达式或注释"
    entry_guard:      "运行时求值的布尔表达式"
    data_invariant:   "状态生命周期内监控的约束"
    exit_guard:       "退出时求值的布尔表达式"
    postcondition:    "表达式或注释"

    # --- 数据 Schema（可选，推荐） ---
    input_schema:     {field: type, ...}     # 上游状态需要的数据
    context_schema:   {field: type, ...}     # 处于此状态时的工作内存
    output_schema:    {field: type, ...}     # 为下游状态生成的数据

    # --- 执行 ---
    action:           "函数名（code executor 必需）"
    prompt:           "系统提示词（llm executor 必需）"
    tool_allowlist:   [...]                  # LLM 在此状态中可调用的工具
    human_review:     true | false           # 是否中断等待人工审批
    review_prompt:    "审批者看到的内容"
    stream:           true | false           # 是否流式输出 LLM 内容
    on_exit:          "状态完成后执行的回调函数"
     on_error: errorNode            # 未处理错误时进入的状态
    description:      "关于此状态功能的人类可读注释"

    # --- 守卫元变量（框架生成，可在守卫表达式中使用） ---
    # 这些不是用户定义的字段。框架自动设置它们：
    #   exit_guard_pass    — 所有出口守卫约束通过时为 true
    #   exit_guard_blocked — 任意出口守卫约束失败时为 true
    #   context_complete   — LLM 确认拥有所有需要的数据时为 true
    #   context_incomplete — LLM 需要更多信息时为 true（驱动自循环）
    #   all_approved       — 所有必需的人工审批已收到时为 true
    #   any_rejected       — 任意人工审批被拒绝时为 true
    #   any_field_missing  — output_schema 有必需的 null 字段时为 true
    #   retries_exhausted  — LLM 或代码节点已超过最大重试次数时为 true
```

### 3.4 守卫表达式语法

守卫表达式支持：
- **状态字段访问：** `field_name`、`schema.field_name`（例如 `amount`、`collected_data.age`）
- **布尔运算符：** `AND`、`OR`、`NOT`、`and`、`or`、`not`
- **比较运算符：** `==`、`!=`、`>`、`<`、`>=`、`<=`
- **列表成员判断：** `field in [a, b, c]`、`field in ['a', 'b', 'c']`
- **空值检查：** `field != null`、`field == null`
- **元变量：** §3.4 中列出的框架生成标志
- **自然语言散文：** 当条件无法机械求值时允许作为回退（视为"静态分析不可验证，始终产生警告"）

完整的形式化语法推迟到实现规划阶段（见附录 C.2）。

---

## 4. 自动生成的 LangGraph 图

框架从 YAML transitions 定义自动生成 LangGraph StateGraph。每个状态成为一个 LangGraph 节点；每个转换成为一条条件边。

关于完整工作流的生成图，见 [README.md](../../examples/home-insurance/README.md) 中的图示和 [e2e-scenarios.md](../../examples/home-insurance/e2e-scenarios.md) 中的逐状态演练。

**每个状态 -> 一个 LangGraph 节点。Executor 决定节点行为：**

| executor | LangGraph 节点行为 |
|----------|------------------------|
| `llm` | 自动注入对话历史 -> 调用 LLM -> 流式输出 -> 检查点 |
| `code` | 执行确定性动作函数；输入/输出可审计 |

图结构精确镜像 transitions 定义：节点是状态，边是带有守卫条件的转换。自循环（例如 `guard: context_incomplete`）保持对话停留在某状态直到数据完整。

---

## 5. 五项能力集成矩阵

| 能力 | 机制 | 集成点 |
|------------|-----------|-------------------|
| **LLM 调用** | executor=llm 节点自动附加 ChatOpenAI | 自动生成 |
| **流式输出** | executor=llm + stream:true 节点自动启用 .astream_events() | 自动生成 |
| **对话持久化** | SqliteSaver.put() 在每个节点退出后自动调用 | Checkpointer 注入 |
| **人机协作（中断）** | executor=llm + human_review:true 节点在 LLM 生成后自动 interrupt()，审批后恢复 | LangGraph interrupt |
| **工具调用** | tool_allowlist 工具自动注入到 ToolNode | LangGraph ToolExecutor |

---

## 6. 端到端演练

> 关于完整的端到端对话示例（报价流程、理赔流程、高风险路由），见 [e2e-scenarios.md](../../examples/home-insurance/e2e-scenarios.md)。演练涵盖：
> - 带工具调用的 LLM 驱动数据收集
> - 确定性代码执行（风险评分、保费计算）
> - 基于守卫的路由和自循环
> - 人机协作中断 + 审批
> - 审计日志自动生成


---

## 7. 为什么此架构有效

| 关注点 | 解决方案 |
|---------|------------|
| 维护两份图 | 只维护一份 YAML；LangGraph 图是生成产物，永不手动编辑 |
| 两个状态机冲突 | transitions 是状态的唯一权威；LangGraph 是纯执行引擎 |
| 过于复杂 | 开发者只需面对 YAML + 动作函数；生成器隐藏 LangGraph 细节 |
| 生成器难以维护 | 生成器本身是确定性组件（YAML 入 -> 图出），可单元测试 |

---

## 8. 意图 + 状态解析

### 8.1 原则

意图分类（第1层）和状态机（第2层）不是相互独立的。同一意图在不同当前状态下有不同的含义。**（意图, 当前状态）** 的组合决定了转换是有效、需要确认还是被拒绝。

### 8.2 按状态意图策略

每个状态声明它接受哪些意图，以及如何处理未接受的意图：

```yaml
states:
  - name: collect_info
    intent_policy:
      accept:
        - provide_information    # 用户提供数据 → 继续表单
        - ask_question           # 用户询问覆盖范围 → 在流程中回答
        - decline                # 用户想取消 → 确认后退出
      on_unlisted: ask_confirm   # 未识别的意图 → 要求用户确认
```

**策略行为：**

| 行为 | 描述 |
|----------|-------------|
| `accept` | 意图在此状态中有效；继续进行转换 |
| `on_unlisted: ask_confirm` | 未列出的意图触发确认："你正在 [当前任务] 中。是否取消并 [新意图]？" |
| `on_unlisted: reject` | 未列出的意图被静默阻止；agent 提示用户继续当前任务 |

### 8.3 解析流程

```
用户话语
      │
      ▼
┌─────────────────┐
│ 第1层：意图      │
│ 分类             │ → intent: make_payment, confidence: 0.92
└────────┬────────┘
         ▼
┌─────────────────┐
│ 第2层：检查      │
│ 意图 vs 状态     │
│                  │
│ state=filling_form
│ intent_policy:   │
│   accept:        │
│     - provide_information
│     - ask_question
│     - decline
│   on_unlisted: ask_confirm
│                  │
│ make_payment ∉ accept
└────────┬────────┘
         ▼
┌─────────────────┐
│ ask_confirm:     │
│ "你正在填写      │
│  报价表单。      │
│  取消并付款？"   │
└────────┬────────┘
         ▼
    用户响应
         │
    ┌────┴────┐
    ▼         ▼
  "yes"     "no"
    │         │
    ▼         ▼
  state     stay in
  → idle   filling_form
  intent    (re-classify
  → make_   next input)
  payment
```

### 8.4 示例场景

关于家庭保险工作流中的具体意图+状态解析示例，见 [intent-definitions.md](../../examples/home-insurance/intent-definitions.md) 和 [workflow.yaml](../../examples/home-insurance/workflow.yaml) 中的 `intent_policy` 部分。

### 8.5 与其他状态机关注点的关系

- **重试计数器** 独立于意图解析。触发 `ask_confirm` 的用户不消耗重试次数 —— 只有无效数据输入（错误姓名、错误代码）才增加重试次数。
- **敏感字段清理** 在状态退出时发生，无论退出是由正常转换、`decline` 还是确认的意图切换触发的。

> **关于阶段路由的说明：** 解析后的意图+状态映射到 `agentState.phase`，驱动带返回栈的阶段感知路由（在路由与执行规范第4节中定义）。

## 参考资料

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
- [领域模型](./2026-06-17-domain-model-design.md)
- [路由与执行](./2026-06-17-routing-execution-layer-design.md)
- [提取层](./2026-06-17-extraction-layer-design.md)
- [意图分类](./2026-06-16-intent-classification-design.md)
- [transitions Library](https://github.com/pytransitions/transitions)
- [LangGraph](https://github.com/langchain-ai/langgraph)

## 附录 C：实现规划 — 待解决问题（状态机）

> 设计中识别但推迟到实现规划阶段的问题。
> 非 FSM 问题见 [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) 附录。

### C.1 状态设计

> **子工作流：** 其内部逻辑本身是一个完整工作流的状态（嵌套 YAML 定义）。父状态将执行委托给子工作流，子工作流完成后恢复。

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | 如何定义状态数据 schema？`input_schema` / `context_schema` / `output_schema` 三层隔离 vs 扁平 dict | 审计追踪粒度、数据隔离安全性 |
| 2 | 子工作流最大嵌套深度？深度嵌套是否损害可读性 | 工作流可复用性、可维护性 |
| 3 | 是否需要历史状态（恢复到上一个活跃子状态）？实现策略 | 复杂流程断点恢复 |
| 4 | 父状态统一进入/退出行为 — 离开父状态时所有子状态是否应运行清理/验证 | 资源管理、泄漏防止 |
| 5 | 动态 vs 静态工作流 — 图结构是否可在运行时修改 | 灵活性与确定性冲突 |

### C.2 转换与守卫

> **历史状态：** 一种伪状态，记住退出父状态时哪个子状态是活跃的，从而能够在同一点重新进入。标准 UML 状态图概念。

| # | 问题 | 影响 |
|---|----------|--------|
| 6 | 守卫表达能力边界：仅纯函数？是否允许外部服务调用（DB/API） | 性能、确定性、可测试性 |
| 7 | 守卫冲突解决 — 多个守卫同时为真时怎么办 | 运行时行为确定性 |
| 8 | 守卫完整性强制 — 如何静态检测未覆盖的出口守卫情况 | 防止状态中运行时死锁 |
| 9 | 隐式 errorNode（无匹配）设计：显式 catch-all vs 框架注入的 errorNode | 合规性 — 系统不能"冻结" |
| 10 | 完整守卫表达式语法（当前语法见 §3.5） | 开发者体验、安全性 |

### C.3 并行状态

> **正交区域：** 父状态内多个并发活跃的子状态。例如，处于"onboarding"时，同时并行运行"verify_identity"和"collect_preferences"。标准 UML 状态图概念。

| # | 问题 | 影响 |
|---|----------|--------|
| 11 | 正交区域是否可以通信（共享数据/事件） | 并行分支耦合 |
| 12 | 并行分支如何收敛：全部完成 vs 任一完成 vs 超时 | 复杂工作流编排灵活性 |

### C.4 错误与恢复

| # | 问题 | 影响 |
|---|----------|--------|
| 13 | 当代码节点遇到外部 API 故障或 DB 不可用时，状态机如何触发重试/补偿/回滚转换 | 状态转换可靠性 |
| 14 | 全局错误工作流设计 — 为所有未捕获异常设计统一的 errorNode | 合规性 — 状态机不得冻结或静默失败 |

### C.5 版本迁移

| # | 问题 | 影响 |
|---|----------|--------|
| 15 | 如何将进行中的对话状态平滑迁移到新的工作流 YAML 版本 | 零停机生产更新 |
| 16 | 如何将旧状态映射到新状态 — 自动推断 vs 手动映射表；状态创建/删除/修改的策略 | 迁移准确性 |

### C.6 代码生成器

| # | 问题 | 影响 |
|---|----------|--------|
| 17 | 如何保证 YAML 定义 -> LangGraph 图等价性 | 系统信任基础 |
| 18 | 生成器可测试性 — 给定 YAML 输入，断言输出图结构正确 | 回归保护 |

### C.7 静态验证

| # | 问题 | 影响 |
|---|----------|--------|
| 19 | 死状态检测 — 定义了但任何转换都无法到达的状态 | 代码质量 |
| 20 | 缺失转换检测 — 存在未覆盖事件/条件分支的状态 | 运行时完整性 |
| 21 | 不可达状态检测 — 有入边转换但入口不可达的状态 | 代码质量 |
| 22 | 守卫冲突检测 — 两个守卫可能同时为真且指向不同目标 | 运行时非确定性 |
| 23 | 后置条件可满足性 — 声明的后置条件在正常路径上是否必然成立 | 契约有效性 |
| 24 | YAML schema 严格性 — 部署前能捕获多少错误（字段拼写错误、类型不匹配） | 开发者体验 |
