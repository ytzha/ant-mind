# VERSION=0.1.0
# -*- coding: utf-8 -*-
"""把策略模板渲染成一次可冻结的评测出卷（纯标准库）。

用法：
    python scripts/eval-prompts/render_prompt.py --strategy s2 --species hauler --batch-id AB-SAMPLE-001
    python scripts/eval-prompts/render_prompt.py --strategy s0 --species builder --batch-id X \
        --ticks 300,600,1200 --species-set scout,hauler,soldier,chef,builder
    python scripts/eval-prompts/render_prompt.py --list
    python scripts/eval-prompts/render_prompt.py --verify-manifest

职责：
    1. 读 strategies/<strategy>.md 全文，算 promptSha256（含头部注释，口径见 README.md §7）；
    2. 把 {SPECIES} 换成实际物种，算 renderedPromptSha256；
    3. 写 request.json：batchId / templateVersion / strategyId / promptSha256 /
       renderedPromptSha256 / dslSha256 / contractVersion / species / speciesSet / ticks /
       maxTokens / temperature / modelId / ANTMIND_PIPE / hostSeed / freshPaused；
    4. 写 prompts.sha256 清单（模板 + 契约 + 四份策略，sha256sum -c 兼容）；
    5. 同 batchId 目录已存在 → 拒绝覆盖，退出码 2（对齐 AIGAMES --frozen 锚定）。

dslSha256 关联：本脚本出卷时 program 尚未产生，写 "PENDING"；clean_dsl.py 产出
clean_manifest.json 后由 scripts/eval-matrix-harness.py 把每个 programs/*.ant 的真实
dslSha256 回填进 request.json，并与 scripts/model-eval-bridge.py 的 cells[].dslSha256 对齐。

本脚本不连网关、不调模型、不跑 dotnet；只负责把「唯一自变量」冻结成字节可证的文件。

变更摘要：
    0.1.0（2026-11-13）首次实现。模板字节级自证、渲染自证、批次冻结拒绝覆盖、追溯维度落 request.json。
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_OUT = ROOT / ".tmp-eval-batches"
CONTRACT_VERSION = "dsl-syntax-0.1.0"
SPECIES = ("scout", "hauler", "soldier", "chef", "builder")
STANDARD_TICKS = (300, 600, 1200)
STRATEGY_FILES = {
    "s0": "s0-bare.md",
    "s1": "s1-skeleton-fewshot.md",
    "s2": "s2-checklist.md",
    "s3": "s3-excerpt.md",
}
RE_META = re.compile(r"^(\w+):\s*(.+?)\s*$", re.M)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    return Path(path).read_bytes()


def parse_meta(text):
    return {k: v for k, v in RE_META.findall(text)}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_strategies():
    print("可用策略（contractVersion=%s）：" % CONTRACT_VERSION)
    for sid, fname in STRATEGY_FILES.items():
        p = HERE / "strategies" / fname
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        meta = parse_meta(text)
        print("  %-3s %-32s templateVersion=%-8s promptSha256=%s" %
              (sid, fname, meta.get("templateVersion", "?"), sha256_bytes(p.read_bytes())[:12] if p.exists() else "MISSING"))
    return 0


def manifest_paths():
    paths = [HERE / "dsl-syntax-0.1.0.md", HERE / "README.md"]
    paths += [HERE / "strategies" / f for f in STRATEGY_FILES.values()]
    return [p for p in paths if p.exists()]


def write_manifest(out_dir, frozen):
    path = out_dir / "prompts.sha256"
    lines = []
    for p in manifest_paths():
        lines.append("%s  %s" % (sha256_bytes(read_bytes(p)), p.relative_to(ROOT).as_posix()))
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    if frozen and path.exists():
        raise FileExistsError("拒绝覆盖已冻结清单：%s" % path)
    path.write_bytes(payload)
    return path, len(lines)


def verify_manifest():
    path = HERE / "prompts.sha256"
    if not path.is_file():
        print("缺少 %s；先跑一次 render_prompt.py 出卷" % path, file=sys.stderr)
        return 2
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        want, rel = line.split("  ", 1)
        target = ROOT / rel
        got = sha256_bytes(read_bytes(target)) if target.exists() else "MISSING"
        ok = got == want
        print("%s  %s" % ("OK  " if ok else "FAIL", rel))
        bad += 0 if ok else 1
    print("prompts.sha256 校验：%d 项，差异 %d" %
          (len([x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]), bad))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", default="", help="s0 / s1 / s2 / s3")
    ap.add_argument("--species", default="hauler", help="渲染 {SPECIES} 的实际值（默认 hauler）")
    ap.add_argument("--batch-id", default="", help="批次 id；不给则用 UTC 时间戳生成")
    ap.add_argument("--model-id", default="MODEL_ID", help="模型 id 占位（本脚本不调模型）")
    ap.add_argument("--ticks", default=",".join(str(t) for t in STANDARD_TICKS),
                    help="标准档 300,600,1200")
    ap.add_argument("--species-set", default=",".join(SPECIES),
                    help="同题对照的全 5 物种口径")
    ap.add_argument("--max-tokens", type=int, default=1400)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--pipe", default="", help="ANTMIND_PIPE 独立值；不给用 antmind-ab-<batchId>")
    ap.add_argument("--out-root", default=str(DEFAULT_OUT), help="批次根目录（默认被 gitignore 的 .tmp-eval-batches/）")
    ap.add_argument("--frozen", action="store_true", help="目标已存在则拒绝覆盖（默认就拒绝，显式给出便于审计）")
    ap.add_argument("--list", action="store_true", help="列出四份策略与 promptSha256 前 12 位")
    ap.add_argument("--verify-manifest", action="store_true", help="校验 prompts.sha256 清单")
    args = ap.parse_args()

    if args.list:
        return list_strategies()
    if args.verify_manifest:
        return verify_manifest()
    if not args.strategy:
        ap.error("给 --strategy，或用 --list / --verify-manifest")
    if args.strategy not in STRATEGY_FILES:
        ap.error("--strategy 只接受 s0/s1/s2/s3，收到 %r" % args.strategy)
    if args.species not in SPECIES:
        ap.error("--species 只接受 %s，收到 %r" % ("/".join(SPECIES), args.species))

    species_set = [s.strip() for s in args.species_set.split(",") if s.strip()]
    bad = [s for s in species_set if s not in SPECIES]
    if bad:
        ap.error("--species-set 含不支持蚁种：%s" % bad)
    try:
        ticks = [int(t.strip()) for t in args.ticks.split(",") if t.strip()]
    except ValueError:
        ap.error("--ticks 必须是逗号分隔整数")
    if not ticks or not species_set or any(not 1 <= t <= 1200 for t in ticks):
        ap.error("--ticks 必须 1..1200（上游 evaluate_save 硬限制）")

    template = HERE / "strategies" / STRATEGY_FILES[args.strategy]
    if not template.is_file():
        ap.error("模板不存在：%s" % template)
    raw = read_bytes(template)
    text = raw.decode("utf-8")
    meta = parse_meta(text)
    if meta.get("contractVersion") != CONTRACT_VERSION:
        ap.error("模板 contractVersion 不是 %s：%r" % (CONTRACT_VERSION, meta.get("contractVersion")))
    if "{SPECIES}" not in text:
        ap.error("模板缺 {SPECIES} 槽位：%s" % template)

    prompt_sha = sha256_bytes(raw)
    rendered = text.replace("{SPECIES}", args.species)
    rendered_sha = sha256_bytes(rendered.encode("utf-8"))
    batch_id = args.batch_id or ("AB-%s" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    pipe = args.pipe or ("antmind-ab-%s" % re.sub(r"[^A-Za-z0-9_-]", "-", batch_id))
    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    out_dir = out_root / batch_id

    # 冻结：同 batchId 已存在即拒绝，任何文件都不覆盖
    if out_dir.exists():
        print("拒绝覆盖已冻结批次：%s（换 --batch-id 或另选 --out-root）" % out_dir, file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True)
    (out_dir / "prompt.rendered.md").write_bytes(rendered.encode("utf-8"))
    (out_dir / "CONDITION.md").write_text(
        "# 出卷条件（冻结）\n\n"
        "- batchId: `%s`\n- strategyId: `%s`\n- templateVersion: `%s`\n"
        "- contractVersion: `%s`\n- promptSha256: `%s`\n- renderedPromptSha256: `%s`\n"
        "- species: `%s`（渲染值）；speciesSet: `%s`（同题对照口径）\n"
        "- ticks: `%s`（标准档）\n- modelId: `%s`\n- maxTokens: `%d`；temperature: `%s`\n"
        "- ANTMIND_PIPE: `%s`；hostSeed: `42`；freshPaused: `true`\n"
        "- 评分：`Candidate.NewFoodPoints`（FirstAdmissionPoints 增量），GrossDelivered 仅展示\n"
        "- 样本：单批次，结论只能写「本 harness 下」，Wilson 区间重叠写「不能断言」\n"
        % (batch_id, args.strategy, meta.get("templateVersion", "0.1.0"), CONTRACT_VERSION,
           prompt_sha, rendered_sha, args.species, ",".join(species_set),
           ",".join(str(t) for t in ticks), args.model_id, args.max_tokens,
           args.temperature, pipe),
        encoding="utf-8")

    request = {
        "version": VERSION,
        "generatedAt": utc_now(),
        "batchId": batch_id,
        "templateVersion": meta.get("templateVersion", "0.1.0"),
        "strategyId": args.strategy,
        "promptSha256": prompt_sha,
        "renderedPromptSha256": rendered_sha,
        "contractVersion": CONTRACT_VERSION,
        "dslSha256": "PENDING",
        "templateFile": template.relative_to(ROOT).as_posix(),
        "species": args.species,
        "speciesSet": species_set,
        "ticks": ticks,
        "modelId": args.model_id,
        "maxTokens": args.max_tokens,
        "temperature": args.temperature,
        "ANTMIND_PIPE": pipe,
        "hostSeed": 42,
        "freshPaused": True,
        "seedNote": "宿主固定 42；EvaluationRequest 无 seed 字段，多 seed 靠换宿主种子 + 多 slot",
        "primaryScore": "Candidate.NewFoodPoints（FirstAdmissionPoints 增量）",
        "notPrimaryScore": "GrossDelivered 仅展示，不参与排名",
        "frozen": True,
        "gitHead": os.environ.get("GIT_HEAD", ""),
    }
    (out_dir / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    # 清单也落到模板目录一份，便于 commit 后独立复核（模板目录这份允许被本脚本刷新）
    manifest_lines = []
    for p in manifest_paths():
        manifest_lines.append("%s  %s" % (sha256_bytes(read_bytes(p)), p.relative_to(ROOT).as_posix()))
    (HERE / "prompts.sha256").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    _, count = write_manifest(out_dir, False)

    print("出卷完成（冻结，不可覆盖）：%s" % out_dir)
    print("  strategy=%s templateVersion=%s contractVersion=%s" %
          (args.strategy, meta.get("templateVersion", "0.1.0"), CONTRACT_VERSION))
    print("  promptSha256=%s" % prompt_sha)
    print("  renderedPromptSha256=%s" % rendered_sha)
    print("  speciesSet=%s ticks=%s pipe=%s" % (",".join(species_set), ",".join(str(t) for t in ticks), pipe))
    print("  prompts.sha256 清单 %d 项；dslSha256 待 clean_dsl 产出后由 harness 回填" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
