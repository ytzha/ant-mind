<!--
strategyId: s1
templateVersion: 0.1.0
contractVersion: dsl-syntax-0.1.0
形态: 骨架 few-shot —— 给语句骨架 + 两份官方 DSL 完整原文（与 .scratch/v019-eval/gen_dsl.py:43-53 的历史形态对齐：语法说明 + builder/hauler 完整 few-shot）。
可比性: 仅与同 contractVersion / 同 harness / 同封存语料 / 同 ticks-species 口径的本批次 s0、s2、s3 结果可比；
        跨批次必须 (templateVersion, strategyId, promptSha256, batchId) 四元组全一致。
不可比: 与 .scratch/v019-eval/ 历史 8 份产物仅「策略形态」可比，结果标 incompatible —— 历史批次没留 raw_response、
        clean() 只删围栏、契约当时未冻结且 DSL_SYNTAX_v019.md:45/106 误写 query("key")；本模板已按契约纠正该误写。
        不可把本策略结果写成模型能力名次。
promptSha256: 本文件全文 UTF-8 字节的 SHA-256，见同目录 prompts.sha256；render_prompt.py 运行时重算校验。口径见 README.md §7。
-->

# s1 · 骨架 few-shot

你是 Ant Mind 的程序编写器。目标物种：`{SPECIES}`。

任务：写一份 Ant Mind DSL 程序，最大化首次入巢计分 FirstAdmissionPoints（尽快把巢中还没有的新食物搬回巢并 deliver）。评分只看 Candidate.NewFoodPoints，不看 GrossDelivered。

契约版本：contractVersion: dsl-syntax-0.1.0。

## 语句骨架

```text
// 单行注释
let 名字 = 表达式;             // 同名全局只能声明一次，赋值前必须先 let
memory[0] = 表达式;            // 只允许 memory[0..15]，memory 是关键字不是变量
if (条件) { 语句 } else { 语句 }   // if 必须带圆括号
repeat 4 { 语句 }             // 次数是 1..16 的整数字面量
动作(参数, 参数);              // 参数个数固定
函数(参数);                    // 可出现在表达式里
```

运算符：`|| && == != < <= > >= + - * / %`，用 `!` 取反。字符串只允许作具名函数（如 `param("station")`、`has_point("nest")`）的 key，字符集 ASCII 字母数字 `_ . -`，长度 1..40。没有 `query()` 这个函数。变量名、函数名、动作名只能取契约 `dsl-syntax-0.1.0` 白名单里的名字，不许自造。整份程序 1..8192 字符、≤512 语法节点、块/表达式嵌套 ≤8。

## 官方例程一 · builder（完整原文）

```text
// Every builder shares this program. Agent assigns station plus objective in group data.
if (queen_connected) { request_queen_info(); }
let station = param("station");
if (station > 0) {
    if (max(abs(x-objective_x),abs(y-objective_y)) > 800) { set_target(objective_x,objective_y); }
    else { if (building_ready(station)) { wait(); } else { work(station); } }
} else { wait(); }
```

## 官方例程二 · hauler-reliable（完整原文）

```text
// Every hauler executes this same program; groups supply cached job parameters.
if (group_id > 0) {
    if (carry > 0) {
        if (at_nest) { deliver(); }
        else { set_target(nest_x,nest_y); }
    } else if (group_order_version == 0) {
        request_queen_info(); set_target(nest_x,nest_y);
    } else {
        if (queen_connected) { report_discovery(); request_queen_info(); }
        if (group_task == task_collect) {
            if (job_food_amount > 0) {
                if (job_food_distance <= 1000) { pickup_from(job_food_id); }
                else { set_target(job_food_x,job_food_y); }
            } else if (job_queen_amount > 0) { set_target(job_queen_x,job_queen_y); }
            else { set_target(job_explore_x,job_explore_y); }
        } else if (group_task == task_explore) { set_target(job_explore_x,job_explore_y); }
        else { set_target(objective_x,objective_y); }
    }
} else {
let mode = memory[0];
if (carry > 0) {
    memory[0] = 0;
    if (at_nest) { deliver(); }
    else { set_target(nest_x, nest_y); }
} else if (mode == 1) {
    if (action_status != 1) {
        if (nearest_distance <= 1000) { pickup(); }
        else {
            memory[1] = memory[1] + 1;
            memory[0] = 2;
            set_target(nest_x, nest_y);
        }
    }
} else if (mode == 2) {
    if (at_nest) {
        report_discovery();
        request_queen_info();
        memory[2] = tick;
        memory[0] = 3;
        wait();
    } else { set_target(nest_x, nest_y); }
} else if (mode == 3) {
    report_discovery();
    request_queen_info();
    if (queen_info_tick >= memory[2]) { memory[0] = 0; }
    wait();
} else {
    if (queen_connected) {
        report_discovery();
        request_queen_info();
    }
    if (queen_count > 0) {
        memory[1] = memory[1] % queen_count;
        set_target(queen_x_at(memory[1]), queen_y_at(memory[1]));
        memory[0] = 1;
    } else if (nearest_distance <= 1000) { pickup(); }
    else { set_target(explore_x, explore_y); }
}

}
```

注意 `if (queen_count > 0)` 先判分母再写 `% queen_count`；除零与溢出都会变成 `program-error`。`let` 只出现一次；`memory` 不当变量声明。

## 输出纪律

只输出 DSL 程序本体。不要 markdown 围栏、不要解释、不要计划、不要 `<think>` 标签、不要复述上面两份例程。现在直接输出程序。
