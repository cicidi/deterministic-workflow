# 第1层：意图分类

> 属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 重点关注：UNDERSTAND 层中的意图分类。
> 所有具体的意图示例已提取到 [examples/home-insurance/](../../examples/home-insurance/)。

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | 初始意图分类规范 |
| 2026-06-16 | 0.2.0 | 将自定义意图示例提取到 examples/；修正章节编号 |
| 2026-06-17 | 0.3.0 | 添加实现方案对比、YAML schema、待解决问题、errorNode 交叉引用、agentState.phase 提及 |

---

## 1. 角色

意图分类回答的问题是：*"用户想要做什么？"*

它将自由形式的用户话语映射到预定义的意图标签，可选地附带置信度分数。输出结果由状态机（第2层）消费，用于确定有效的状态转换。

## 2. 意图模型

### 2.1 系统意图（内置）

| Intent | 描述 |
|--------|-------------|
| `ask_question` | 用户询问信息或解释 |
| `provide_information` | 用户响应提示提供数据 |
| `start_conversation` | 用户发起新对话 |
| `resume_conversation` | 用户返回之前的对话 |
| `finish_conversation` | 用户希望结束对话 |
| `unrecognized_intent` | 无法确定意图（低置信度回退） |
| `confirm` | 用户同意或确认 |
| `decline` | 用户不同意、取消或拒绝 |

### 2.2 自定义意图（按工作流）

每个工作流可以定义额外的领域特定意图。关于家庭保险意图及其关键词和示例的完整目录，请参见 [intent-definitions.md](../../examples/home-insurance/intent-definitions.md)。框架对系统意图和自定义意图使用相同的 `IntentDef` schema。

### 2.3 意图定义 Schema

```yaml
# Schema: IntentDef
#   name:        string      # 唯一标识符
#   description: string      # 指导 LLM 分类
#   keywords:    string[]    # 确定性回退模式
#   examples:    string[]    # LLM 提示的 few-shot 示例

intents:
  - name: "ask_question"
    description: "用户询问信息或解释"
    keywords:
      - "what is"
      - "how does"
      - "tell me about"
      - "explain"
    examples:
      - "What is my deductible?"
      - "How does the claims process work?"
      - "Tell me about coverage options"

  - name: "get_quote"
    description: "用户请求新的保险报价"
    keywords:
      - "quote"
      - "get a price"
      - "how much"
      - "estimate"
    examples:
      - "I want a quote for home insurance"
      - "How much would it cost to insure my house?"
      - "Give me a price estimate"
```

### 2.4 实现方案

框架支持三种分类策略。项目根据其延迟、成本和确定性需求，在配置时选择其中一种。

| 维度 | 方案A：纯 LLM | 方案B：纯关键词/正则 | 方案C：LLM + 关键词回退 |
|-----------|-------------------|------------------------------|----------------------------------|
| **准确性** | 高（能理解细微差别） | 低–中（仅字面匹配） | 高（LLM 为主，关键词安全网） |
| **确定性** | 低（本质上非确定性） | 高（100% 可预测） | 中（关键词保证已知模式） |
| **延迟** | 200–800ms（API 调用） | <1ms | 200–800ms（LLM）；LLM 失败时 <1ms |
| **成本** | 每次分类的 API 成本 | 免费 | 每次分类的 API 成本（仅关键词命中时无成本） |
| **优雅降级** | 无（LLM 失败 = unrecognized） | 仅裸关键词匹配 | LLM 失败时回退到关键词 |
| **可扩展性** | 仅调整提示词 | 添加关键词/正则模式 | 添加关键词 + 调整提示词 |
| **最适合** | 原型开发、简单领域 | 高吞吐量、窄领域机器人 | 受监管行业的生产系统 |

**方案A：纯 LLM** — 每次分类都经过 LLM。无关键词回退。简单但没有安全网。
**方案B：纯关键词/正则** — 纯模式匹配。快速且确定性，但无法处理模糊或新颖的话语。
**方案C：LLM + 关键词回退**（默认） — LLM 优先，带关键词安全网。推荐用于生产环境。

本文档的其余部分详细描述方案C。

## 3. 分类策略：LLM优先 + 关键词回退

> **所有 LLM 输出均为 JSON。** 框架通过输出守卫（见 HLD 第4.3节）对每个分类结果强制执行 schema 验证、字段存在性检查和类型强制转换。如果 JSON 格式错误，守卫会在重试预算内自动重试。

### 3.1 对话上下文

意图分类不是单条消息的操作。LLM 提示必须包含对话历史以消歧模糊话语。例如，如果 agent 刚刚问"我应该继续吗？"，"yes" 意味着 `confirm`；但如果 agent 问"你叫什么名字？"，"yes" 则意味着 `provide_information`。

框架在每次分类调用中包含 **最近3条用户消息 + 最近3条 agent 消息** 作为上下文。这提供了足够的对话历史来消歧短回复，同时不会使提示词膨胀。

> **注意：** 意图分类的输入还包含 `agentState.phase`（例如 `quoting`、`claims`、`onboarding`）。当前工作流阶段提供状态感知的上下文，帮助分类器消歧意图 —— 例如，在 `quoting` 阶段说"我想改一下"很可能是指修改报价，而在 `claims` 阶段则很可能是指更新理赔。

### 3.2 边界情况覆盖

意图分类是系统应对意外用户行为的安全网。它必须处理的边界情况：

- 工作流中突然切换话题（"算了，我想给别人付款"）
- 模糊的单字回复（"ok"、"sure"、"no"）
- 工作流中的离题问题
- 部分或不完整的话语
- 代码切换或混合语言输入

当分类器无法自信地解决边界情况时，返回 `unrecognized_intent`，触发澄清回复。

### 3.3 LLM 提示词构建

框架根据用户的意图定义和对话上下文构建系统提示词。提示词包括：

1. 最近3条用户消息 + 最近3条 agent 消息（上下文窗口）
2. 所有意图及其描述的列表
3. 每个意图的 few-shot 示例
4. 结构化输出指令：`{ intent: string, confidence: number, reasoning: string }`

Temperature 设置为 0 以实现确定性分类。

### 3.4 回退：关键词匹配

如果 LLM 调用失败或返回 `confidence < threshold`，框架对用户输入执行关键词匹配：

```
For each intent:
  if any keyword matches user_input (case-insensitive):
    return that intent with confidence=1.0
```

系统意图具有内置关键词模式。自定义意图使用用户提供的 `keywords`。

### 3.5 置信度阈值

可配置的阈值（默认 `0.7`）。当 LLM 返回 `confidence < threshold` 时，结果被视为 `unrecognized_intent`，触发第3层的澄清回复。

### 3.6 合并策略

```
1. 尝试 LLM 分类
2. 如果 LLM 失败 → 回退到关键词匹配
3. 如果 LLM 成功但 confidence < threshold → 使用回退结果（如有）
4. 如果两者都未产生结果 → unrecognized_intent
```

LLM 结果 + 回退结果可能不一致。当两者不一致且 LLM 置信度高于阈值时，LLM 胜出。当两者都低于阈值时，关键词回退胜出（它是确定性的）。

> **注意：** 如果 LLM 和关键词都未产生结果（`unrecognized_intent`），框架路由到 `errorNode` 进行统一错误处理（见路由与执行规范第6节）。

## 4. 输出契约

```
ClassificationResult {
  intent:     string      // 解析后的意图标签
  confidence: number      // 0.0 - 1.0
  source:     "llm" | "keyword" | "unrecognized"
  reasoning?: string      // LLM 的推理（用于审计追踪）
}
```

`source` 字段指示哪个分类器产生了结果，使下游节点能够调整行为（例如，"关键词匹配 → 立即继续；LLM 匹配 → 考虑再次确认"）。

---

## 5. 待解决问题

### 5.1 多意图检测

分类器是否应支持检测单条话语中的多个意图（例如，"我想取消保单并退款"）？目前框架返回单个意图。多意图需要多标签分类器或后续消歧步骤。

### 5.2 置信度阈值校准

默认阈值 `0.7` 是起点。实践中，最优阈值因领域、意图复杂度和 LLM 模型选择而异。团队应如何校准阈值？选项包括：按意图的历史准确率分析、A/B 测试，或基于对话阶段的自适应阈值。

### 5.3 长对话中的意图漂移

在长时间对话中（例如 20+ 轮次），用户意图可能逐渐变化而非突然切换话题。框架应通过窗口化置信度趋势检测意图漂移，还是依赖第2层状态机检测阶段不匹配？

### 5.4 跨语言意图分类

框架应如何处理非英语输入？选项包括：(a) 分类前翻译为英语，(b) 在提示词中包含多语言示例，(c) 使用多语言嵌入模型。每种方案在延迟、成本和准确率方面有不同的权衡。

### 5.5 冷启动：Zero-Shot vs. Few-Shot 提示

对于没有提供训练示例的自定义意图，框架应回退到 zero-shot 提示，还是要求最少示例数？Zero-shot 更灵活，但对领域特定意图的准确率较低。

---

## 参考资料

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 父文档
- [状态机设计](./2026-06-16-state-machine-design.md) — 意图+状态解析逻辑
