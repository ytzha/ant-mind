# Ant Mind 「写对率」定义（冻结）

版本 0.1.0

> 这份文档只做一件事：把「模型写对了没有」拆成五层漏斗，锁死主指标，写清什么时候必须说「不能断言」。
> 它是评测口径，不是结论。任何实测数字、对比结论都不写进本文件；本轮单次样例也不在这里下能力断言。
> 契约版本固定 `dsl-syntax-0.1.0`；契约一变，本文件升位，旧批次的比率不回算、不追认。

## 1. 五层漏斗（分母逐级收窄）

| 层 | 名称 | 判据 | 分母 | 失败分桶 |
| --- | --- | --- | --- | --- |
| L1 | 通道成功率 | 模型调用返回且拿到 `choices[0].message.content` | 计划模型数 | `timeout` / `429` / `5xx` / `no_choices` / `auth_error` |
| L2 | 有码率 | L1 通过且 `clean_dsl.py` 的 `status != empty_after_clean` | L1 通过数 | `empty_after_clean`（与语法错分开，不混桶） |
| **L3** | **编译写对率＝主指标** | `validate_program.valid == true` | L2 通过数 | 见 §2 错误码分桶 |
| L4 | 运行写对率 | `evaluate_save` 无 `error`、`programErrors.total == 0`、无 `budget-exceeded`、无 `program-error` | L3 通过数 | `program_error` / `budget_exceeded` / `memory_index_out_of_range` / `eval_error` |
| L5 | 得分有效率 | `Candidate.NewFoodPoints > baselineFileScore`（同 `species,ticks` 的官方默认参照行） | L4 通过数 | `not_above_baseline`（**单列「得分能力」，不并入写对率**） |

关键纪律：

- 主指标锁 L3：`validate_program.valid == true` 才算「写对」。L4/L5 是附加观察，不拿来替换主指标。
- `emptyControlScore` 是 `evaluate_save` 内部 `Run(false)` 的空白对照分支；`baselineFileScore` 是官方默认 DSL 作为候选行的实测分。两者不混，L5 用后者。
- 评分只看 `Candidate.NewFoodPoints`（FirstAdmissionPoints 增量）；`GrossDelivered` 只展示、不参与任何排名。
- 清洗器 `clean_dsl.py` 只标不修语法：重复 `let`、伪造 `query()`、缺 `deliver()` 等偏差必须原样进 L3 的错误桶，不许被清洗器偷偷修好。修了就是把「模型能力」和「清洗器能力」混成一个自变量。

## 2. L3 错误分桶（按 `validate_program` 返回串括号前的主干）

逐条对应 `dsl-syntax-0.1.0.md` §2 的硬约束，便于跨批次同口径比较：

| 桶 | 匹配串 | 契约条目 |
| --- | --- | --- |
| `unexpected_character` | `Unexpected character at offset ...` / `<think>` 残留 | §1 词法、§2.8 |
| `duplicate_let` | `Variable 'x' cannot be declared here.` | §2.2 |
| `undeclared_assignment` | `Declare 'x' with let before assigning it.` | §2.2 |
| `unknown_expression_function` | `Unknown expression function 'x'.`（含 `query`） | §4 / §2.5 |
| `unknown_variable` | `Unknown variable 'x'.` | §3 / §2.5 |
| `unknown_action` | `Unknown action 'x'.` | §5 / §2.5 |
| `argument_count` | `Function 'x' expects N argument(s).` / `Action 'x' expects N argument(s).` | §2.4 |
| `nesting_or_nodes` | `Maximum ... nesting ...` / `Program exceeds 512 syntax nodes.` | §2 表 |
| `integer_literal` | `Integer literal is out of range.` | §1 |
| `group_key` | `Group key must have 1..40 characters.` / `Group keys only accept ...` / `Unterminated group key.` | §1 / §6 |
| `if_paren` | `Expected '(' ...` / `Expected ')' ...` | §2.1 |
| `repeat_bound` | `repeat bound must be 1 to 16.` | §2 表 |
| `source_length` | `Program source must contain 1 to 8192 characters.` / `Program is empty.` | §2 表 |
| `other` | 其余（原样保留，不猜） | — |

## 3. 比率与区间

每一层都给 `k / n`、点估计 `p = k/n` 与 **Wilson 95% 区间**：

```python
# z=1.959963984540054（双侧 95%）
denom = 1 + z*z/n
center = (p + z*z/(2*n)) / denom
half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
lo, hi = max(0.0, center - half), min(1.0, center + half)
```

`n == 0` 时比率写 `null`、区间写 `null`，并在报告里写「该层无样本，不能断言」，不许拿 0/0 当 0%。

## 4. 「不能断言」的触发条件（任一命中即写）

1. 两个策略/模型/物种/ticks 的 Wilson 区间**重叠** → 写「不能断言差异」，不给名次。
2. **单批次样本**（`batchCount == 1`）→ 写「不能断言」，且所有表述限定为「本 harness 下」。
3. 未完成独立复核（§6）→ 不写「谁更强」，只写本批次实测值。
4. `determinism.failed > 0` 或 `reconcile` 差异 ≠ 0 → 该批次结果作废，不进任何汇总。
5. 四元组 `(templateVersion, strategyId, promptSha256, batchId)` 不全一致 → 标 `incompatible`，不合并、不比较。
6. 全 cell 0 分（`scripts/model-eval-bridge.py:696-698` 的提示）→ 写「本档无区分度」，不写能力结论。

**禁止写法**：模型能力名次表、「X 比 Y 强」的定性结论、把 L5 得分能力并进 L3 写对率、把 `emptyControlScore` 当 `baselineFileScore`。

## 5. 过程指标（只描述分布，不排名）

`cleanFlagRate`（`think_block_stripped` / `fence_stripped` / `fewshot_verbatim` 等命中率）、`fewshotVerbatimRate`、`meanSourceBytes`、`programErrors.total` 分布、`runtimeMs` 分布、`rawSha256` 与 `dslSha256` 清单完整性。这些是诊断用，用来解释「为什么 L2/L3 掉了」，不是能力结论。

## 6. 独立复核口径

任何准备落进文档的「策略/模型/物种/ticks 差异」结论，必须：

1. 换会话、换 `ANTMIND_PIPE`、换 `--out` 前缀、换 `--slot` stem；
2. 用**同一份封存 `programs/`** 与同一 `request.json` 重跑，控住同题对照：同一 slot/ticks/species 口径、fresh paused seed42；
3. `reconcile` 按 `(species, ticks, label, dslSha256)` 四元组定位，逐 cell 比 `score / emptyControlScore / deltaVsEmptyControl / deltaVsBaselineFile / programErrors / processingValueAdded / developmentValueDelta / valid / selfcheck.passed / rankInGroup` **全字段**；
4. 两次 `determinism.passed == determinism.total` 且 reconcile 差异 **0**，才允许写结论；
5. 原始输入与方法六件套缺一不算复核：`request.json` + `programs/` + `raw/`（原文响应）+ `prompts.sha256` + `result.json` + `reconcile.json` + `CONDITION.md`。

单次样例只证明 harness 可复跑、出表、对账通；**不构成能力结论**。

## 7. 冻结与升位

- 模板升位 / 策略切换 / ticks 改动 / 旧 content14 产物 → 一律标 `incompatible`，旧批次不回改。
- 契约 `dsl-syntax` 升位 → 本文件升位并追加变更摘要，旧比率保留、不重算。
- 清洗器升位 → `cleanVersion` 变化即视为不同口径，L2/L3 不跨版本合并。

## 变更摘要

- 0.1.0（2026-11-13）：首次定义。五层漏斗、L3 锁主指标、13 个错误桶、Wilson 区间、6 条「不能断言」触发条件、独立复核六件套与全字段对账口径。
