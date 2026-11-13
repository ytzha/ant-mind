<!--
strategyId: s0
templateVersion: 0.1.0
contractVersion: dsl-syntax-0.1.0
可比性: 仅与同 contractVersion / 同 harness / 同封存语料 / 同 ticks-species 口径的 s1、s2、s3 本批次结果可比；
        与 .scratch/v019-eval/ 历史 8 份产物不可比（历史无 raw_response、清洗器不同、契约未冻结），标 incompatible；
        跨批次必须 (templateVersion, strategyId, promptSha256, batchId) 四元组全一致才可比。
不可比: 任何把本策略结果当作「某模型能力名次」的用法；任何混入不同 ticks/species 的合并表。
promptSha256: 本文件全文 UTF-8 字节的 SHA-256，值见同目录 prompts.sha256 清单；
              render_prompt.py 运行时重算并校验，不一致即拒绝出卷。口径见 README.md §7。
-->

# s0 · 裸指令

你是 Ant Mind 的程序编写器。目标物种：`{SPECIES}`。

任务：写一份 Ant Mind DSL 程序，最大化首次入巢计分 FirstAdmissionPoints（尽快把巢中还没有的新食物搬回巢并 deliver）。评分只看 Candidate.NewFoodPoints，不看 GrossDelivered。

契约版本：contractVersion: dsl-syntax-0.1.0。

输出纪律：只输出 DSL 程序本体。不要 markdown 围栏、不要解释、不要计划、不要 `<think>` 标签、不要任何代码之外的文字。

现在直接输出程序。
