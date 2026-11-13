# Ant Mind 评测提示词策略层

版本 0.1.0

> 这一层是**唯一自变量**。契约层 `dsl-syntax-0.1.0.md` 冻结不动，模型/语料批次/物种/ticks 由 harness 控制，只有「给模型看多少提示」允许在 s0~s3 之间变。
> 每份模板是独立文件、独立 `promptSha256`、独立 `strategyId`，互不拼接、互不继承。模板头部必须写「与哪一版可比/不可比」；模板内容一改就升版本 + 追加变更摘要，旧批次的 `promptSha256` 不回改。
> `promptSha256` 算法见本文件 §7：取模板文件**全文 UTF-8 字节**（含头部注释）做 SHA-256，生成器与 harness 都按这个口径算，避免「同一份模板两处算不一样」。

## 1. 四份策略

| strategyId | 文件 | 自变量内容 | contractVersion | 可比口径 |
| --- | --- | --- | --- | --- |
| `s0` | `strategies/s0-bare.md` | 裸指令：只说目标 + 输出纪律，不给语法、不给例子 | `dsl-syntax-0.1.0` | 同 contractVersion、同 harness、同语料封存、同 ticks/species 才可比；与 s1/s2/s3 只能比「策略效果」，不能比模型能力 |
| `s1` | `strategies/s1-skeleton-fewshot.md` | 骨架 + 官方完整 few-shot（历史 v019 语料用的就是这一档） | `dsl-syntax-0.1.0` | **与历史 `.scratch/v019-eval/` 8 份产物仅策略形态可比，结果不可直接合并**：历史批次没留 `raw_response`、清洗器不同、契约文档当时未冻结，须标 `incompatible` |
| `s2` | `strategies/s2-checklist.md` | 清单式：三张白名单 + 硬约束逐条列出，不给完整示例 | `dsl-syntax-0.1.0` | 同批次内与 s0/s1/s3 可比；跨批次须四元组 `(templateVersion, strategyId, promptSha256, batchId)` 全一致 |
| `s3` | `strategies/s3-excerpt.md` | 节选：≤12 行官方 DSL 片段 + 最短骨架 | `dsl-syntax-0.1.0` | 同批次内可比；提示词长度与 s2 差异本身就是自变量，不额外归因给模型 |

## 2. 共享不变量（所有策略都必须带）

这几项不是自变量，四份模板逐字一致，缺一项该批次标 `incompatible`：

- 目标：`最大化首次入巢计分 FirstAdmissionPoints（尽快把巢中还没有的新食物搬回巢并 deliver）`。
- 物种槽位：`{SPECIES}`，取值 `scout/hauler/soldier/chef/builder`，由 harness 渲染，模板里不许写死某个物种。
- 输出纪律：只输出 DSL 程序本体；不要 markdown 围栏、不要解释、不要计划、不要 `<think>`。
- 契约版本行：`contractVersion: dsl-syntax-0.1.0`。
- 评分不看 `GrossDelivered`，只看 `Candidate.NewFoodPoints`（这一句给模型看，避免它去刷搬运总量）。

## 3. 渲染与自证

`scripts/eval-prompts/render_prompt.py` 负责：

1. 读 `--strategy` 指定的模板全文，算 `promptSha256`；
2. 把 `{SPECIES}` 替换成实际物种，算 `renderedPromptSha256`；
3. 写 `request.json`，字段至少含 `batchId / templateVersion / strategyId / promptSha256 / renderedPromptSha256 / dslSha256 / contractVersion / species / ticks / maxTokens / temperature / modelId`；
4. 同一 `batchId` 目录已存在 → **拒绝覆盖**（对齐 AIGAMES `--frozen` 锚定），报 `batch already frozen: <path>`，退出码 2。

`dslSha256` 用清洗后、送评前的 `program` 字节算，与 `scripts/model-eval-bridge.py` 的 `dslSha256` 口径一致，用来把外层 `request.json` 与桥的 `cells[].dslSha256` 关联起来。

## 4. 清洗纪律（指向 clean_dsl）

模型原始响应必须落 `raw_response` + `rawSha256`，`scripts/eval-prompts/clean_dsl.py` 只做分级剥离、不代改语法。重复 `let`、伪造 `query()`、缺 `deliver()`、分母没保护，全部保留原样交给 `validate_program` 如实报错。清洗器改一个字，`cleanVersion` 升一位，旧批次不重算。

## 5. 指标口径（指向定义文档）

主指标锁在 L3（`validate_program.valid == true`），L5 得分另列「得分能力」，不并进写对率。Wilson 区间重叠或单批次样本 → 写「不能断言」，不写模型能力名次。全文见 `write-correctness-0.1.0.md`。

## 6. 独立复核

任何「某策略/某模型/某物种/某 ticks 更强」的说法，必须换会话、换 `ANTMIND_PIPE`、换输出前缀，用同一份封存 `programs/` 重跑，`reconcile` 全字段差异 0 才允许落文档。本 harness 的单次样例只证明可复跑，不构成能力结论。

## 7. promptSha256 算法

```python
import hashlib
from pathlib import Path
prompt_sha256 = hashlib.sha256(Path(template_path).read_bytes()).hexdigest()
rendered_prompt_sha256 = hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
dsl_sha256 = hashlib.sha256(program_bytes).hexdigest()
```

三者都是十六进制小写 64 字符，写进 `request.json` 与 `prompts.sha256` 清单。`prompts.sha256` 每行格式 `<sha256>  <相对路径>`，与 `sha256sum -c` 兼容。

## 变更摘要

- 0.1.0（2026-11-13）：首次定义策略层。四份独立模板、共享不变量、`promptSha256` 字节级自证、`batchId` 冻结拒绝覆盖、跨批次可比性判据。
