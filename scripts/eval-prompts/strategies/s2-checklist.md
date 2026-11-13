<!--
strategyId: s2
templateVersion: 0.1.0
contractVersion: dsl-syntax-0.1.0
形态: 清单式 —— 把契约 dsl-syntax-0.1.0 的三张白名单 + 9 个 GroupValue + 硬约束逐条列出，不给完整例程。
      与 s1 的差异是「给规则不给范例」，与 s0 的差异是「给封闭集合不给裸目标」；提示词长度差异本身即自变量，不额外归因给模型。
可比性: 仅与同 contractVersion / 同 harness / 同封存语料 / 同 ticks-species 口径的本批次 s0、s1、s3 结果可比；
        跨批次必须 (templateVersion, strategyId, promptSha256, batchId) 四元组全一致。
不可比: 与 .scratch/v019-eval/ 历史 8 份产物标 incompatible（历史无 raw_response、清洗器不同、契约未冻结）；
        不可把本策略结果写成模型能力名次。
promptSha256: 本文件全文 UTF-8 字节的 SHA-256，见同目录 prompts.sha256；render_prompt.py 运行时重算校验。口径见 README.md §7。
-->

# s2 · 清单式

你是 Ant Mind 的程序编写器。目标物种：`{SPECIES}`。

任务：写一份 Ant Mind DSL 程序，最大化首次入巢计分 FirstAdmissionPoints（尽快把巢中还没有的新食物搬回巢并 deliver）。评分只看 Candidate.NewFoodPoints，不看 GrossDelivered。

契约版本：contractVersion: dsl-syntax-0.1.0。下面是**封闭集合**：名字不在这几张清单里的标识符、函数、动作一律不许用，不许按常识自造。

## 语句形态

```text
// 单行注释
let 名字 = 表达式;
memory[0] = 表达式;
if (条件) { 语句 } else { 语句 }
repeat 4 { 语句 }
动作(参数, 参数);
函数(参数);
```

运算符 `|| && == != < <= > >= + - * / %`，`!` 取反。字符串只能作具名函数的 key，字符集 ASCII 字母数字 `_ . -`，长度 1..40。

## 清单 1 · Builtins（只读变量，100 项，只能用这些）

```text
nearest_supply_id nearest_supply_x nearest_supply_y nearest_supply_distance nearest_supply_food
has_target target_x target_y target_distance target_reached
food_wood species_builder ant_level experience experience_to_next move_percent work_percent attack_damage technology_level
food_balanced food_royal food_fiber food_concentrate food_meal species_chef
source_count building_count queen_source_count queen_building_count
group_task task_collect task_explore task_guard group_food_type group_radius
job_food_id job_food_amount job_food_x job_food_y job_food_distance
job_queen_amount job_queen_x job_queen_y job_explore_x job_explore_y
max_health food_fruit food_meat carry_food_type nest_fruit nest_meat
nearest_id nearest_food_type group_id group_order_version rally_x rally_y
objective_x objective_y retreat_x retreat_y nearest_ally_id nearest_group_member_id
health nearest_enemy_health species_soldier nearest_enemy_id nearest_enemy_x nearest_enemy_y nearest_enemy_distance
true false ant_id tick x y nest_x nest_y width height carry capacity
species_scout species_hauler nearest_amount nearest_x nearest_y at_nest nearest_distance
action_status queen_info_tick queen_request_status queen_report_status explore_x explore_y
queen_connected queen_count queen_amount queen_x queen_y
```

## 清单 2 · ExpressionFunctions（39 项）

```text
recipe_ready recipe_unlocked food_value
source_id_at queen_source_id_at building_id_at queen_building_id_at
source_x source_y source_amount source_type
queen_source_x queen_source_y queen_source_amount queen_source_type
building_x building_y building_ready building_busy building_can_feed building_phase building_material building_cost building_work
recipe_work holder_stock holder_output
abs min max
queen_x_at queen_y_at queen_amount_at queen_food_type_at
claimed_amount ally_x ally_y ally_health stock
```

参数个数：`recipe_ready` `holder_stock` `holder_output` `min` `max` 是 2 参，其余 34 个是 1 参。个数不符 → `Function 'x' expects N argument(s).`。**没有 `query` 这个函数**，写了就是 `Unknown expression function 'query'.`。

## 清单 3 · Actions（21 项）

```text
harvest deposit withdraw transfer work process pickup_from eat eat_from follow
claim_food release_claim attack set_target move_to pickup deliver wait drop
request_queen_info report_discovery
```

## 清单 4 · GroupValue（9 个具名函数，带字符串 key）

```text
require_param require_group_x require_group_y item_code param has_param group_x group_y has_point
```

正确写法 `param("station")`、`has_point("nest")`。key 只允许 ASCII 字母数字 `_ . -`，1..40 字符。

## 硬约束（逐条）

1. `if` 必须带圆括号：`if (cond) { ... }`。`if !at_nest` 非法，写 `if (!at_nest)`。
2. `let` 同名全局单次，不能与上面 100 个 Builtins 同名，赋值前必须先 `let`。重复声明 → `Variable 'x' cannot be declared here.`；未声明就赋值 → `Declare 'x' with let before assigning it.`。
3. `memory` 是关键字不是变量，只允许 `memory[0..15]`，越界 → `memory_index_out_of_range`。`let memory[0] = ...` 非法。
4. `repeat N` 的 N 是 1..16 的整数字面量，否则 `repeat bound must be 1 to 16.`。
5. 整份程序 1..8192 字符、≤512 语法节点、块/表达式嵌套 ≤8。超限分别报 `Program source must contain 1 to 8192 characters.` / `Program exceeds 512 syntax nodes.` / `Maximum block nesting exceeded.` / `Maximum expression nesting of 8 exceeded.`。
6. `+ - *` 用 `checked`，`/ %` 除零或溢出 → `program-error`。写除法/取模前先判分母，例如 `if (queen_count > 0) { ... % queen_count ... }`。
7. 运行期指令预算 64..1024，耗尽 → `budget-exceeded` + `instruction_budget_exceeded`，别写死循环式的大 repeat。
8. 任何别的字符（含 `<think>` 的首字符 `<`）→ `Unexpected character at offset 0.`。

## 输出纪律

只输出 DSL 程序本体。不要 markdown 围栏、不要解释、不要计划、不要 `<think>` 标签、不要复述清单。现在直接输出程序。
