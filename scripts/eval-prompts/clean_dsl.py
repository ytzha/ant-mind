# VERSION=0.1.1
# -*- coding: utf-8 -*-
"""Ant Mind 模型响应分级清洗器（纯标准库）。

用法：
    python scripts/eval-prompts/clean_dsl.py --input RAW.txt --output clean.json --program-out program.ant
    python scripts/eval-prompts/clean_dsl.py --input RAW.txt --fewshot official/builder.ant
    python scripts/eval-prompts/clean_dsl.py --batch-dir .tmp-eval-batch/ --frozen
    python scripts/eval-prompts/clean_dsl.py --selftest

分级（R0~R7，逐级只在文本层剥离，绝不代模型改语法）：
    R0 强制保留 raw_response 原文 + rawSha256（修旧 gen_dsl.py:69-91 / :123 只删围栏、
       README:191 自称「原始输出如实保留」却不落原文的结构缺陷）。
    R1 剥 <think> / <thinking> / <analysis> 块，含未闭合形态；记 think_block_stripped。
    R2 只删围栏行（``` / ~~~），围栏内的代码一字不动；记 fence_stripped。
    R3 删首尾说明行（扩充 最终代码/程序如下/Here is/Sure!/好的，我 等）；记 edge_chatter_stripped。
    R4 删整行中文计划句，但不删 // 合法注释；记 inline_chatter_stripped。
    R5 空判：status="empty_after_clean"，不与语法错误混成一桶。
    R6 只标不修：重复 let、伪造 query()、缺 deliver()、let memory[...]、if 无圆括号、
       非 ASCII 源码字符、疑似未保护分母 —— 全部进 diagnostics，不动 program 一个字节。
       理由：代改会把「模型能力」与「清洗器能力」混成一个自变量，validate_program 必须如实反映偏差。
    R7 复述检测：与 --fewshot 参照比对，SequenceMatcher > 0.85 记 fewshot_verbatim（只标不修）。

产物 JSON 字段（字段名与 scripts/eval-matrix-harness.py 的 request.json 对齐）：
    version / status / raw_response / rawSha256 / program / cleanSha256 / dslSha256
    flags / steps / diagnostics / fewshotComparisons / emptyAfterClean
    dslSha256 与 scripts/model-eval-bridge.py 的 cells[].dslSha256 同口径（送评字节的 SHA-256）。

冻结：--frozen 或 --batch-dir 模式下目标已存在 → 拒绝覆盖，退出码 2（对齐 AIGAMES --frozen 锚定）。

变更摘要：
    0.1.0（2026-11-13）首次实现。R0 留原文自证 + R1~R7 分级清洗/只标不修/复述检测/冻结拒绝覆盖。
"""

import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.1"
THRESHOLD_VERBATIM = 0.85

RE_THINK_CLOSED = re.compile(r"<(think|thinking|analysis)\b[^>]*>.*?</\1\s*>", re.S | re.I)
RE_THINK_OPEN = re.compile(r"<(think|thinking|analysis)\b[^>]*>.*\Z", re.S | re.I)
RE_LET = re.compile(r"^\s*let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)
RE_QUERY = re.compile(r"\bquery\s*\(")
RE_LET_MEMORY = re.compile(r"\blet\s+memory\s*\[")
RE_IF_NO_PAREN = re.compile(r"\bif\s+[^(\s]")
RE_CHATTER_HEAD = re.compile(
    r"^(这是|以下是|下面是|如下|代码[：:]|程序[：:]|答案[：:]|最终代码|程序如下|下面是程序|"
    r"以上[是为]|Here|Below|Sure|当然|好的|以下|As an AI|I hope|Note that|#{1,6}\s)",
    re.I,
)
RE_PLAN_LINE = re.compile(
    r"^\s*(首先|其次|然后|接着|最后|总之|以上|这样|说明|解释|注意|备注|思路|步骤|方案|"
    r"考虑到|为了|因此|所以)[：:，,]",
)
CODE_CHARS = set(";{}()=")
FENCE_PREFIXES = ("```", "~~~")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def _strip_think(text):
    removed = 0
    out, n = RE_THINK_CLOSED.subn("", text)
    removed += len(text) - len(out)
    text = out
    out2, n2 = RE_THINK_OPEN.subn("", text)
    if n2:
        removed += len(text) - len(out2)
        text = out2
    return text, removed, (n > 0 or RE_THINK_OPEN.search(out) is not None)


def _strip_fences(lines):
    kept = []
    removed = 0
    for line in lines:
        if line.lstrip().startswith(FENCE_PREFIXES):
            removed += 1
            continue
        kept.append(line)
    return kept, removed


def _is_soft_chatter(line):
    s = line.strip()
    if not s:
        return True
    if any(c in s for c in CODE_CHARS):
        return False
    if s.startswith("//"):
        return False
    if len(s) > 80:
        return False
    return bool(RE_CHATTER_HEAD.search(s))


def _strip_edge_chatter(lines):
    removed = 0
    while lines and _is_soft_chatter(lines[0]):
        lines.pop(0)
        removed += 1
    while lines and _is_soft_chatter(lines[-1]):
        lines.pop()
        removed += 1
    return lines, removed


def _strip_plan_lines(lines):
    kept = []
    removed = 0
    for line in lines:
        s = line.strip()
        if s.startswith("//"):
            kept.append(line)
            continue
        if any(c in s for c in CODE_CHARS):
            kept.append(line)
            continue
        if RE_PLAN_LINE.search(s):
            removed += 1
            continue
        kept.append(line)
    return kept, removed


def _normalize_for_similarity(text):
    return re.sub(r"\s+", " ", text).strip()


def clean_response(raw, fewshot_texts=None):
    """把一份模型原始响应清洗成结构化结果；raw 必须是未经任何修改的原文。"""
    if not isinstance(raw, str):
        raise TypeError("raw 必须是 str（原始响应全文，不许先 strip）")
    fewshot_texts = fewshot_texts or []
    raw_sha = sha256_text(raw)
    flags = []
    steps = []

    text, removed, think_hit = _strip_think(raw)
    if think_hit or removed:
        flags.append("think_block_stripped")
    steps.append({"rule": "R1", "name": "strip_think_blocks", "removedChars": removed,
                  "triggered": bool(removed or think_hit)})

    lines, removed = _strip_fences(text.splitlines())
    if removed:
        flags.append("fence_stripped")
    steps.append({"rule": "R2", "name": "strip_fence_lines_only", "removedLines": removed,
                  "triggered": removed > 0})
    text = "\n".join(lines)

    lines, removed = _strip_edge_chatter(lines)
    if removed:
        flags.append("edge_chatter_stripped")
    steps.append({"rule": "R3", "name": "strip_edge_chatter", "removedLines": removed,
                  "triggered": removed > 0})

    lines, removed = _strip_plan_lines(lines)
    if removed:
        flags.append("inline_chatter_stripped")
    steps.append({"rule": "R4", "name": "strip_whole_line_plan_sentences", "removedLines": removed,
                  "triggered": removed > 0})

    program = "\n".join(lines).strip("\n")
    empty = not program.strip()
    status = "empty_after_clean" if empty else "ok"
    if empty:
        flags.append("empty_after_clean")
    steps.append({"rule": "R5", "name": "empty_check", "triggered": empty, "status": status})

    # R6：只标不修，绝不改写 program
    let_names = RE_LET.findall(program)
    duplicates = sorted({n for n in let_names if let_names.count(n) > 1})
    diagnostics = {
        "duplicateLet": duplicates,
        "unknownQueryCall": bool(RE_QUERY.search(program)),
        "missingDeliver": ("deliver(" not in program.replace(" ", "")),
        "letMemoryDeclared": bool(RE_LET_MEMORY.search(program)),
        "ifWithoutParen": bool(RE_IF_NO_PAREN.search(program)),
        "nonAsciiInSource": any(ord(ch) > 127 for ch in program),
        "thinkResidue": "<think" in program.lower(),
        "possiblyUnguardedDivisor": bool(
            re.search(r"[/%]", program)
            and not re.search(r"(>\s*0|!=\s*0|>=\s*1|==\s*0)", program)
        ),
        "note": "以上仅为标注，不代改语法；语法偏差以 validate_program / evaluate_save 的如实结果为准。",
    }
    for key, label in (("duplicateLet", "duplicate_let_detected"),
                       ("unknownQueryCall", "unknown_query_call_detected"),
                       ("missingDeliver", "missing_deliver_detected"),
                       ("letMemoryDeclared", "let_memory_declared_detected"),
                       ("ifWithoutParen", "if_without_paren_detected"),
                       ("nonAsciiInSource", "non_ascii_in_source_detected"),
                       ("thinkResidue", "think_residue_detected")):
        value = diagnostics[key]
        if bool(value):
            flags.append(label)
    steps.append({"rule": "R6", "name": "diagnose_only_never_patch", "triggered": True,
                  "diagnostics": diagnostics})

    # R7：复述检测，只标不修
    comparisons = []
    base = _normalize_for_similarity(program)
    for label, ref in fewshot_texts:
        ratio = difflib.SequenceMatcher(None, base, _normalize_for_similarity(ref)).ratio() if base else 0.0
        hit = ratio > THRESHOLD_VERBATIM
        comparisons.append({"reference": label, "similarity": round(ratio, 6),
                            "verbatim": hit, "threshold": THRESHOLD_VERBATIM})
        if hit:
            flags.append("fewshot_verbatim")
    steps.append({"rule": "R7", "name": "fewshot_verbatim_detect_only", "triggered": bool(comparisons),
                  "comparisons": comparisons})

    clean_sha = sha256_text(program)
    return {
        "version": VERSION,
        "cleanVersion": VERSION,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "emptyAfterClean": empty,
        "raw_response": raw,
        "rawSha256": raw_sha,
        "program": program,
        "cleanSha256": clean_sha,
        "dslSha256": clean_sha,
        "dslBytes": len(program.encode("utf-8")),
        "flags": flags,
        "steps": steps,
        "diagnostics": diagnostics,
        "fewshotComparisons": comparisons,
    }


def _write_frozen(path, data, frozen):
    if frozen and path.exists():
        raise FileExistsError("拒绝覆盖已冻结产物：%s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _load_fewshots(paths):
    out = []
    for raw in paths:
        for item in raw.split(","):
            if not item.strip():
                continue
            p = Path(item.strip())
            out.append((p.name, p.read_text(encoding="utf-8")))
    return out


def _selftest():
    """内置回归夹具，覆盖历史语料的三类结构缺陷（不依赖外部文件）。"""
    cases = []

    r1 = "<think>先想一下\n再想</think>\n```ant\nif (at_nest) { deliver(); }\n```\n好的，以上。"
    c1 = clean_response(r1)
    cases.append(("think+fence+chatter", "think_block_stripped" in c1["flags"]
                  and "fence_stripped" in c1["flags"]
                  and c1["program"].strip() == "if (at_nest) { deliver(); }"
                  and c1["raw_response"] == r1))

    r2 = "<analysis>未闭合的思考块一直到这里\nif (at_nest) { deliver(); }"
    c2 = clean_response(r2)
    cases.append(("unclosed_think", "think_block_stripped" in c2["flags"]
                  and c2["raw_response"] == r2))

    r3 = ("let foodCode = 1;\nlet foodCode = 2;\nlet foodCode = 3;\nlet foodCode = 4;\n"
          "memory[0] = query(\"foodCode\") % 0;\nif (at_nest) { deliver(); }")
    c3 = clean_response(r3)
    cases.append(("diagnose_only", c3["diagnostics"]["duplicateLet"] == ["foodCode"]
                  and c3["diagnostics"]["unknownQueryCall"] is True
                  and c3["program"] == r3))

    r4 = "这是说明\n下面是程序\nSure! Here is the code"
    c4 = clean_response(r4)
    cases.append(("empty_after_clean", c4["status"] == "empty_after_clean"
                  and c4["emptyAfterClean"] is True))

    ref = "if (at_nest) { deliver(); } else { set_target(nest_x,nest_y); }"
    c5 = clean_response(ref, [("builder.ant", ref)])
    cases.append(("fewshot_verbatim", "fewshot_verbatim" in c5["flags"]
                  and c5["fewshotComparisons"][0]["similarity"] == 1.0))

    ok = True
    for name, passed in cases:
        print("%-24s %s" % (name, "PASS" if passed else "FAIL"))
        ok = ok and passed
    print("selftest: %d/%d 通过" % (sum(1 for _, p in cases if p), len(cases)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="", help="模型原始响应文件（UTF-8 全文，未经任何清洗）")
    ap.add_argument("--stdin", action="store_true", help="从 stdin 读原始响应全文")
    ap.add_argument("--output", default="", help="写完整清洗结果 JSON（含 raw_response / rawSha256）")
    ap.add_argument("--program-out", default="", help="另写清洗后 program 文本（送评字节）")
    ap.add_argument("--fewshot", action="append", default=[],
                    help="复述检测参照文件，可多次/逗号分隔（如官方 builder.ant / hauler-reliable.ant）")
    ap.add_argument("--batch-dir", default="",
                    help="批量模式：读 <dir>/raw/*.txt，写 <dir>/clean/*.json + <dir>/programs/*.ant + clean_manifest.json")
    ap.add_argument("--frozen", action="store_true", help="目标已存在则拒绝覆盖（退出码 2）")
    ap.add_argument("--selftest", action="store_true", help="跑内置回归夹具，不读写文件")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    fewshots = _load_fewshots(args.fewshot)

    if args.batch_dir:
        batch = Path(args.batch_dir)
        raw_dir = batch / "raw"
        if not raw_dir.is_dir():
            ap.error("批量模式找不到 %s" % raw_dir)
        clean_dir = batch / "clean"
        programs_dir = batch / "programs"
        manifest_path = batch / "clean_manifest.json"
        if manifest_path.exists():
            print("拒绝覆盖已冻结批次：%s" % manifest_path, file=sys.stderr)
            return 2
        args.frozen = True
        rows = []
        for raw_path in sorted(raw_dir.glob("*.txt")):
            result = clean_response(raw_path.read_bytes().decode("utf-8"), fewshots)
            (clean_dir / (raw_path.stem + ".json")).parent.mkdir(parents=True, exist_ok=True)
            (programs_dir / (raw_path.stem + ".ant")).parent.mkdir(parents=True, exist_ok=True)
            _write_frozen(clean_dir / (raw_path.stem + ".json"),
                          json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"), args.frozen)
            _write_frozen(programs_dir / (raw_path.stem + ".ant"),
                          result["program"].encode("utf-8"), args.frozen)
            rows.append({"modelId": raw_path.stem, "status": result["status"],
                         "rawSha256": result["rawSha256"], "dslSha256": result["dslSha256"],
                         "dslBytes": result["dslBytes"], "flags": result["flags"],
                         "programFile": "programs/%s.ant" % raw_path.stem,
                         "cleanFile": "clean/%s.json" % raw_path.stem})
        payload = {"version": VERSION, "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "frozen": bool(args.frozen), "count": len(rows), "rows": rows}
        _write_frozen(manifest_path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), args.frozen)
        print("批量清洗：%d 份 → %s" % (len(rows), batch))
        for r in rows:
            print("  %-32s %-18s dslSha256=%s" % (r["modelId"], r["status"], r["dslSha256"][:12]))
        return 0

    if args.stdin:
        raw = sys.stdin.read()
    elif args.input:
        raw = Path(args.input).read_bytes().decode("utf-8")
    else:
        ap.error("给 --input / --stdin / --batch-dir / --selftest 之一")
        return 1

    result = clean_response(raw, fewshots)
    rendered = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    if args.output:
        try:
            _write_frozen(Path(args.output), rendered, args.frozen)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.program_out:
        try:
            _write_frozen(Path(args.program_out), result["program"].encode("utf-8"), args.frozen)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if not args.output:
        sys.stdout.buffer.write(rendered + b"\n")
    print("clean_dsl v%s status=%s flags=%s dslSha256=%s" %
          (VERSION, result["status"], ",".join(result["flags"]) or "-", result["dslSha256"]),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
