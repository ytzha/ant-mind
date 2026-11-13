# Ant Mind DSL 语法契约（冻结）

版本 0.1.0

> 本文件是**契约层冻结件**：把 `src/AntMind.Programs/AntDsl.cs` 在 `5e0da235a857a4bd8ab67ecfec6af67868b9baeb`（分支 `feat/linux-headless`）里已生效的语法集合逐字固化下来，供提示词模板与评测口径共同引用。
> 冻结含义：策略模板可以换、提示词可以换、模型可以换，**这份语法集合不许换**。策略层的所有差异都必须建立在同一个 `dsl-syntax-0.1.0` 之上，否则跨批次结果标 `incompatible`，不参与任何比较。
> 权威顺序：源码 `AntDsl.cs` > 本文件 > `.scratch/v019-eval/official/DSL_SYNTAX_v019.md`。本文件与源码不一致时以源码为准，并升版本号 + 追加变更摘要，不静默改字。

## 0. 权威源与适用范围

| 项 | 值 |
| --- | --- |
| 编译器 | `src/AntMind.Programs/AntDsl.cs` → `public static class AntDslCompiler` |
| 词法/语法 | 同文件 `private sealed class AntDslParser` |
| 解释器 | 同文件 `private sealed class AntDslInterpreter` |
| 冻结基线 | `5e0da235a857a4bd8ab67ecfec6af67868b9baeb` |
| 协议 | wire18 / content15 / save5 |
| 适用范围 | 只描述语法集合与运行期硬约束；不改编译器、不改 wire18、不改 world schema |

`DSL_SYNTAX_v019.md`（0.1.0，上游 `5b88eeee5`）第 45 行与第 106 行把 GroupValue 泛写成 `query("key")`，**源码里没有 `query` 函数**。以本文件 §3 的 9 个名字为准。`query("foodCode")` 会直接报 `Unknown expression function 'query'.`，这个偏差由 `validate_program` 如实反映，清洗器不代改。

## 1. 词法

- 单行注释 `//`，读到行尾丢弃（`AntDsl.cs:673-674`）。
- 标识符：ASCII 字母或 `_` 起头，后续可接字母/数字/`_`（`:686-690`）。
- 整数字面量：十进制数字（`:691-693`）；越界报 `Integer literal is out of range.`（`:630`）。
- 双字符符号 `== != <= >= && ||`（`:695-698`）；单字符符号 `(){}[];,=+-*/%<>!`（`:699-700`）。
- 字符串**只**作为 GroupValue 的 key 出现，字符集仅 ASCII 字母、数字、`_ . -`，长度 1..40（`:677-684`）。三条错误原文：
  - `Group keys only accept ASCII letters, digits, underscore, dot and dash.`
  - `Group key must have 1..40 characters.`
  - `Unterminated group key.`
- 任何其他字符 → `Unexpected character at offset {start}.`（`:702`）。`<think>` 标签首字符即 `<`，所以未清洗的思考块落进编译器必然是 `Unexpected character at offset 0.`。
- 运算符优先级（`Precedence`，`:664-667`）：`||`1 < `&&`2 < `== !=`3 < `< <= > >=`4 < `+ -`5 < `* / %`6。

## 2. 硬约束（编译期 + 运行期）

| 常量 | 值 | 源码位置 | 违反时的精确表现 |
| --- | --- | --- | --- |
| `MaxSourceLength` | 8192 | `:7`、`:15` | `Program source must contain 1 to 8192 characters.`；`Parse()` 空程序另有 `Program is empty.`（`:524-529`） |
| `MaxNodes` | 512 | `:8`、`:658-662` | `Program exceeds 512 syntax nodes.` |
| `MaxNesting` | 8 | `:9`、`:584-590`、`:600-615` | `Maximum block nesting exceeded.` / `Maximum expression nesting of 8 exceeded.` |
| `MaxRepeat` | 16 | `:10`、`:531-571` | `repeat bound must be 1 to 16.`，N 必须是整数字面量 |
| `MemorySlots` | 16 | `:11`、`:27-29`、`:219-229` | 只允许 `memory[0..15]`；索引越界 `memory_index_out_of_range`；`memory.Length != 16` → `program-error` + `memory_size_invalid` |

补充硬约束，逐条写清以便模板照抄：

1. **`if` 必须带圆括号**：`if (cond) { ... }`。`ParseIf` 在 `:573-581` 无条件 `Expect("(") ... Expect(")")`。`if !at_nest` 非法，要写 `if (!at_nest)` 或 `if (at_nest == 0)`。
2. **`let` 同名全局单次**：`locals` 是全局集合，块内不开新作用域。重复声明、或与 §3 Builtins 同名 → `Variable '{name}' cannot be declared here.`（`:542`）。赋值前必须先 `let`，否则 `Declare '{identifier}' with let before assigning it.`（`:554`）。旧 8 份语料里 `SF_-Qwen_Qwen3-8B` 的 4 个 `let foodCode` 就撞这一条，清洗器**只标不修**。
3. **`memory` 是关键字不是变量**：`let memory[0] = ...` 非法；读写用 `memory[i]`，i 必须是 0..15 的整数表达式。
4. **函数/动作参数个数固定**：不匹配 → `Function '{name}' expects {expected} argument(s).`（`:649`）/ `Action '{name}' expects {expected} argument(s).`（`:569`）。表达式函数里 34 个是 1 参，`recipe_ready`、`holder_stock`、`holder_output`、`min`、`max` 是 2 参（`:648`）。
5. **不存在的名字**：`Unknown expression function '{name}'.`（`:644`）、`Unknown action '{name}'.`（`:558`）、`Unknown variable '{name}'.`（`:652-653`）。
6. **运行期算术**：`+` `-` `*` 用 `checked`；`/` `%` 除零、`OverflowException`、`DslRuntimeException` 一律收敛为 `program-error`。写除法前先判分母，例如官方 `hauler-reliable.ant:52-53` 的 `if (queen_count > 0) { memory[1] = memory[1] % queen_count; ... }`。
7. **指令预算**：运行期 brainBudgets 区间 64..1024，耗尽 → `budget-exceeded` + `instruction_budget_exceeded`（此条来自 `AB-调研与设计.md` 的运行期整理，具体阈值以 Runtime 实现为准，本契约不擅自扩展）。
8. **错误带偏移**：`ErrorAt` 统一抛 `FormatException($"{message} (offset {token.Offset}).")`（`:718`），评测按括号前的错误串分桶即可。

## 3. Builtins（只读变量，100 项，逐字）

来源 `AntDsl.cs:499-509 private static readonly HashSet<string> Builtins`。**名字不在这 100 项里的标识符，不能当变量用。**

```text
nearest_supply_id
nearest_supply_x
nearest_supply_y
nearest_supply_distance
nearest_supply_food
has_target
target_x
target_y
target_distance
target_reached
food_wood
species_builder
ant_level
experience
experience_to_next
move_percent
work_percent
attack_damage
technology_level
food_balanced
food_royal
food_fiber
food_concentrate
food_meal
species_chef
source_count
building_count
queen_source_count
queen_building_count
group_task
task_collect
task_explore
task_guard
group_food_type
group_radius
job_food_id
job_food_amount
job_food_x
job_food_y
job_food_distance
job_queen_amount
job_queen_x
job_queen_y
job_explore_x
job_explore_y
max_health
food_fruit
food_meat
carry_food_type
nest_fruit
nest_meat
nearest_id
nearest_food_type
group_id
group_order_version
rally_x
rally_y
objective_x
objective_y
retreat_x
retreat_y
nearest_ally_id
nearest_group_member_id
health
nearest_enemy_health
species_soldier
nearest_enemy_id
nearest_enemy_x
nearest_enemy_y
nearest_enemy_distance
true
false
ant_id
tick
x
y
nest_x
nest_y
width
height
carry
capacity
species_scout
species_hauler
nearest_amount
nearest_x
nearest_y
at_nest
nearest_distance
action_status
queen_info_tick
queen_request_status
queen_report_status
explore_x
explore_y
queen_connected
queen_count
queen_amount
queen_x
queen_y
```

## 4. ExpressionFunctions（39 项，逐字）

来源 `AntDsl.cs:510 private static readonly HashSet<string> ExpressionFunctions`，实现在 `:233-267 public int Function(string name, int[] values)`。

```text
recipe_ready
recipe_unlocked
food_value
source_id_at
queen_source_id_at
building_id_at
queen_building_id_at
source_x
source_y
source_amount
source_type
queen_source_x
queen_source_y
queen_source_amount
queen_source_type
building_x
building_y
building_ready
building_busy
building_can_feed
building_phase
building_material
building_cost
building_work
recipe_work
holder_stock
holder_output
abs
min
max
queen_x_at
queen_y_at
queen_amount_at
queen_food_type_at
claimed_amount
ally_x
ally_y
ally_health
stock
```

其中 2 参函数只有 `recipe_ready` `holder_stock` `holder_output` `min` `max`，其余 34 个全为 1 参。`query` 不在此表。

## 5. Actions（21 项，逐字）

来源 `AntDsl.cs:511-513 private static readonly HashSet<string> Actions`，实现在 `:273-318 public void ActionStatement(string name, int[] values)`。

```text
harvest
deposit
withdraw
transfer
work
process
pickup_from
eat
eat_from
follow
claim_food
release_claim
attack
set_target
move_to
pickup
deliver
wait
drop
request_queen_info
report_discovery
```

## 6. GroupValue（9 项，逐字）

来源 `AntDsl.cs:181-195 public int GroupValue(string name, string key)` 的九个 case，也是 `:639-643` 里允许带引号 key 的全部名字。正确写法是 `param("station")`、`has_point("nest")` 这种**具名函数 + 字符串 key**，不是 `query("key")`。

```text
require_param
require_group_x
require_group_y
item_code
param
has_param
group_x
group_y
has_point
```

## 7. 冻结纪律

- 模板与语料必须声明 `contractVersion: dsl-syntax-0.1.0`；未声明或声明别的版本的批次，与其他批次一律标 `incompatible`。
- 编译器升级（新增 Builtins / 函数 / 动作、放宽硬约束）必须新开 `dsl-syntax-0.2.0` 并在本文件末尾追加「变更摘要」，旧批次不回改、不重算、不追认。
- 本契约**只描述**，不修改 `src/AntMind.Programs/`、`wire18` 协议或 `save5` 迁移。

## 变更摘要

- 0.1.0（2026-11-13）：首次冻结。逐字固化 Builtins 100 / ExpressionFunctions 39 / Actions 21 / GroupValue 9，补齐编译期 5 常量与运行期算术、预算、错误串；显式纠正 `DSL_SYNTAX_v019.md` 的 `query("key")` 误写。
