<!--
strategyId: s3
templateVersion: 0.1.0
contractVersion: dsl-syntax-0.1.0
形态: 节选 —— 只给 ≤12 行官方 DSL 片段 + 最短骨架，不给完整例程、不给白名单全集。
      与 s1 的差异是「例子长度」，与 s2 的差异是「给例子不给清单」；提示词长度差异本身即自变量，不额外归因给模型。
可比性: 仅与同 contractVersion / 同 harness / 同封存语料 / 同 ticks-species 口径的本批次 s0、s1、s2 结果可比；
        跨批次必须 (templateVersion, strategyId, promptSha256, batchId) 四元组全一致。
不可比: 与 .scratch/v019-eval/ 历史 8 份产物标 incompatible（历史无 raw_response、清洗器不同、契约未冻结）；
        不可把本策略结果写成模型能力名次。
promptSha256: 本文件全文 UTF-8 字节的 SHA-256，见同目录 prompts.sha256；render_prompt.py 运行时重算校验。口径见 README.md §7。
-->

# s3 · 节选

你是 Ant Mind 的程序编写器。目标物种：`{SPECIES}`。

任务：写一份 Ant Mind DSL 程序，最大化首次入巢计分 FirstAdmissionPoints（尽快把巢中还没有的新食物搬回巢并 deliver）。评分只看 Candidate.NewFoodPoints，不看 GrossDelivered。

契约版本：contractVersion: dsl-syntax-0.1.0。变量名/函数名/动作名只能用该契约白名单里的名字，不许自造；没有 `query()` 这个函数。

## 最短骨架

```text
let 名字 = 表达式;
if (条件) { 语句 } else { 语句 }
repeat 4 { 语句 }
memory[0] = 表达式;
```

`if` 必须带圆括号；`let` 同名全局单次；`memory[0..15]` 是关键字不是变量；`repeat` 次数 1..16；字符串只作具名函数（如 `param("station")`）的 key。

## 官方节选一 · builder（7 行，全文）

```text
// Every builder shares this program. Agent assigns station plus objective in group data.
if (queen_connected) { request_queen_info(); }
let station = param("station");
if (station > 0) {
    if (max(abs(x-objective_x),abs(y-objective_y)) > 800) { set_target(objective_x,objective_y); }
    else { if (building_ready(station)) { wait(); } else { work(station); } }
} else { wait(); }
```

## 官方节选二 · hauler-reliable 的 5 行片段（示范先判分母再取模）

```text
} else {
    if (queen_count > 0) {
        memory[1] = memory[1] % queen_count;
        set_target(queen_x_at(memory[1]), queen_y_at(memory[1]));
        memory[0] = 1;
```

节选不是完整程序，别照抄这几行当答案。除零、溢出、未声明变量、未知函数都会如实变成编译错误或 `program-error`。

## 输出纪律

只输出 DSL 程序本体。不要 markdown 围栏、不要解释、不要计划、不要 `<think>` 标签、不要复述节选。现在直接输出程序。
