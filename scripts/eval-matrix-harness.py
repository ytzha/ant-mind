# VERSION=0.1.2
# -*- coding: utf-8 -*-
"""Ant Mind 同题对照矩阵 harness（纯标准库，不改 scripts/model-eval-bridge.py 0.2.1）。

用法：
    python scripts/eval-matrix-harness.py --help
    python scripts/eval-matrix-harness.py run \
        --request .tmp-eval-batches/AB-SAMPLE-001/request.json \
        --programs .tmp-eval-batches/AB-SAMPLE-001/programs \
        --run-id AB-SAMPLE-001-run1 --review \
        --ticks 300 --species hauler          # 样例收窄；不给则用 request.json 的全口径
    python scripts/eval-matrix-harness.py reconcile \
        --left .tmp-eval-harness/AB-SAMPLE-001-run1/main.json \
        --right .tmp-eval-harness/AB-SAMPLE-001-run1/review.json \
        --out .tmp-eval-harness/AB-SAMPLE-001-run1/reconcile.json

设计要点（对齐 AB-调研与设计.md §5.5 / §5.6 / §3.6）：
    1. 不改 当前桥：本脚本只在外层用 request.json + dslSha256 关联补追溯维度
       batchId / templateVersion / strategyId / promptSha256 / contractVersion / modelId 等。
    2. 同题对照控变量：同一份封存 programs/ 原样复制、同一 slot/ticks/species 口径、
       fresh paused seed42（Evaluator/Program.cs:32 GameSession(..., 42)）。
    3. 标准档 ticks=[300,600,1200]，全 5 物种 scout/hauler/soldier/chef/builder；
       --ticks / --species 可显式收窄成「一次实测样例」，但样例必须写「不能断言」。
    4. 跨 ANTMIND_PIPE 独立复核：--review 起两个独立 Evaluator --serve 宿主、两条独立 pipe、
       两个 --out 前缀、两个 --slot stem，跑同一份封存 programs/。
    5. reconcile 全字段对账：按 (species, ticks, label, dslSha256) 四元组定位，逐 cell 比业务字段全集；
       身份字段（slot/runtimeMs/file/cellId 等）在 COMPARE_EXCLUDED 里明示排除，不偷偷漏比。
    6. 产物一律落被 .gitignore:32 忽略的 .tmp-eval-harness/，不进 commit；--run-id 已存在拒绝覆盖。
    7. 任何能力结论的门槛：determinism 全通过 + reconcile 差异 0 + 换会话/换 pipe/换前缀，
       否则只写「本 harness 下，不能断言」。本脚本本身不下模型能力断言。

环境：用内层 `.tools/dotnet/dotnet.exe`（10.0.403）起宿主；本机系统 .NET 仅 8.0.425 不够。
      起进程一律后台静默（本脚本由外层 run_in_background 调用，内部 Popen 也设 CREATE_NO_WINDOW）。

变更摘要：
    0.1.1（2026-11-13）修 ROOT 计算：本脚本在 scripts/ 下，只上一层即工作树根；
      0.1.0 误写 HERE.parents[1] 指到 zcode-game/，实测报「找不到 Evaluator.dll」。
    0.1.0（2026-11-13）首次实现。外层追溯维度关联、双 pipe 独立复核、reconcile 全字段对账、
      标准档/全 5 物种口径、冻结拒绝覆盖。
"""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.2"
HERE = Path(__file__).resolve().parent   # scripts/
ROOT = HERE.parent                       # 内层工作树 ant-mind-linux/（本脚本在 scripts/ 下，只上一层）
BRIDGE = HERE / "model-eval-bridge.py"
EVALUATOR_DLL = ROOT / "tools/AntMind.Evaluator/bin/Debug/net10.0/AntMind.Evaluator.dll"
DEFAULT_BASELINE = ROOT / "content/programs/hauler-reliable.ant"
DEFAULT_OUT_ROOT = ROOT / ".tmp-eval-harness"
SPECIES = ("scout", "hauler", "soldier", "chef", "builder")
STANDARD_TICKS = (300, 600, 1200)
HOST_SEED = None
BRIDGE_VERSION = re.search(r"^# VERSION=(.+)$", BRIDGE.read_text(encoding="utf-8"), re.M).group(1)

# reconcile 的业务字段全集（对齐 AB 报告 §5.5 的清单 + 桥 cells 的其余评分字段）
COMPARE_FIELDS = (
    "score", "emptyControlScore", "deltaVsEmptyControl", "deltaVsBaselineFile",
    "baselineFileScore", "programErrors", "processingValueAdded", "developmentValueDelta",
    "valid", "validate", "selfcheck.passed", "rankInGroup", "grossDelivered",
    "antsLost", "endTick", "startTick", "inventoryDelta", "error",
    "dslSha256", "isBaselineFileCandidate", "protocolVersion", "seed",
)
# 独立复核必然不同、且不属于业务结果的身份字段：明示排除，写进 reconcile.json
COMPARE_EXCLUDED = (
    "slot", "runtimeMs", "selfcheck.secondRuntimeMs", "selfcheck.diffFields",
    "file", "cellId", "rank", "label(用于定位而非比较)",
)
TRACE_KEYS = (
    "batchId", "templateVersion", "strategyId", "promptSha256", "renderedPromptSha256",
    "contractVersion", "modelId", "maxTokens", "temperature", "speciesSet", "ticks",
    "ANTMIND_PIPE", "hostSeed", "freshPaused", "seedNote", "primaryScore",
)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    """稳定序列化，用于逐字段比对（口径同 model-eval-bridge.py:171-174）。"""
    if isinstance(obj, dict):
        return "{" + ",".join("%s:%s" % (json.dumps(k, ensure_ascii=False, sort_keys=True), canonical(v))
                              for k, v in sorted(obj.items())) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(canonical(v) for v in obj) + "]"
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def get_path(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return "<MISSING>"
        cur = cur[part]
    return cur


def diff_fields(left, right, fields=COMPARE_FIELDS):
    diffs = []
    for f in fields:
        a, b = get_path(left, f), get_path(right, f)
        if canonical(a) != canonical(b):
            diffs.append({"field": f, "left": a, "right": b})
    return diffs


def _dotnet_exe():
    local = ROOT / ".tools/dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    return str(local) if local.exists() else ("dotnet.exe" if os.name == "nt" else "dotnet")


def _popen_kwargs(env):
    kwargs = dict(cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def start_host(pipe):
    """起一条独立 Evaluator --serve 宿主；返回 Popen。失败直接抛 RuntimeError。"""
    if not EVALUATOR_DLL.is_file():
        raise RuntimeError("找不到 %s，请先构建 wire18 Debug 产物" % EVALUATOR_DLL)
    env = os.environ.copy()
    env["ANTMIND_PIPE"] = pipe
    dotnet = _dotnet_exe()
    local = ROOT / ".tools/dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    if local.exists():
        env["DOTNET_ROOT"] = str(local.parent)
    try:
        proc = subprocess.Popen([dotnet, str(EVALUATOR_DLL), "--serve"], **_popen_kwargs(env))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法启动 Evaluator 宿主（pipe=%s）：%s" % (pipe, exc)) from exc
    # 等宿主把 PipeServer 监听起来：进程存活即认为就绪，连接失败由桥的重试兜住
    for _ in range(12):
        if proc.poll() is not None:
            raise RuntimeError("Evaluator 宿主提前退出（pipe=%s，exit=%s）" % (pipe, proc.returncode))
        time.sleep(0.25)
    return proc


def stop_host(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    except (OSError, ValueError):
        try:
            proc.kill()
        except Exception:
            pass


def run_bridge(pipe, programs, baseline, ticks, species, slot_stem, out_prefix, attempts=3):
    """调 当前桥跑一次矩阵；不改桥一个字节。"""
    cmd = [sys.executable, str(BRIDGE), "--matrix",
           "--programs"] + [str(p) for p in programs] + [
           "--baseline", str(baseline),
           "--ticks", ",".join(str(t) for t in ticks),
           "--species", ",".join(species),
           "--slot", slot_stem,
           "--out", str(out_prefix)]
    env = os.environ.copy()
    env["ANTMIND_PIPE"] = pipe
    last = None
    for i in range(1, attempts + 1):
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        last = proc
        if proc.returncode == 0:
            return proc.returncode, proc.stdout, cmd
        # 宿主 PipeServer 在坏连接后会自动重建监听实例；短暂等待后重试
        time.sleep(0.8)
    return last.returncode, last.stdout, cmd


def load_result(json_path):
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


def reconcile(left, right, meta=None):
    """按 (species,ticks,label,dslSha256) 四元组定位，逐 cell 全字段对账。"""
    def key(c):
        return (c.get("species"), c.get("ticks"), c.get("label"), c.get("dslSha256"))

    lmap, rmap = {}, {}
    for c in left.get("cells", []):
        lmap.setdefault(key(c), []).append(c)
    for c in right.get("cells", []):
        rmap.setdefault(key(c), []).append(c)
    lkeys, rkeys = set(lmap), set(rmap)
    rows = []
    diffs_total = 0
    for k in sorted(lkeys & rkeys, key=lambda x: tuple(str(v) for v in x)):
        a, b = lmap[k][0], rmap[k][0]
        d = diff_fields(a, b)
        diffs_total += len(d)
        rows.append({"key": {"species": k[0], "ticks": k[1], "label": k[2], "dslSha256": k[3]},
                     "diffCount": len(d), "diffs": d,
                     "selfcheckPassedLeft": (a.get("selfcheck") or {}).get("passed"),
                     "selfcheckPassedRight": (b.get("selfcheck") or {}).get("passed")})
    only_left = [dict(zip(("species", "ticks", "label", "dslSha256"), k)) for k in sorted(lkeys - rkeys, key=str)]
    only_right = [dict(zip(("species", "ticks", "label", "dslSha256"), k)) for k in sorted(rkeys - lkeys, key=str)]
    duplicates = {"left": sum(len(v) - 1 for v in lmap.values()),
                  "right": sum(len(v) - 1 for v in rmap.values())}
    diffs_total += len(only_left) + len(only_right) + sum(duplicates.values())
    ld, rd = left.get("determinism") or {}, right.get("determinism") or {}
    def deterministic(payload, det):
        cells = payload.get("cells", [])
        return (bool(cells) and det.get("enabled") is True
                and det.get("failed") == 0 and det.get("passed") == len(cells)
                and det.get("total") == len(cells)
                and all((c.get("selfcheck") or {}).get("passed") is True for c in cells))
    det_left_ok = deterministic(left, ld)
    det_right_ok = deterministic(right, rd)
    passed = (diffs_total == 0 and det_left_ok and det_right_ok and not only_left and not only_right)
    return {
        "version": VERSION,
        "generatedAt": utc_now(),
        "left": (meta or {}).get("left", ""),
        "right": (meta or {}).get("right", ""),
        "comparedFields": list(COMPARE_FIELDS),
        "excludedIdentityFields": list(COMPARE_EXCLUDED),
        "cellCountLeft": len(left.get("cells", [])),
        "cellCountRight": len(right.get("cells", [])),
        "matchedKeys": len(lkeys & rkeys),
        "duplicateKeys": duplicates,
        "onlyLeft": only_left,
        "onlyRight": only_right,
        "determinism": {"left": ld, "right": rd, "leftOk": det_left_ok, "rightOk": det_right_ok},
        "diffCount": diffs_total,
        "passed": passed,
        "rows": rows,
        "verdict": ("reconcile 差异 0 且两次确定性自检全通过" if passed
                    else "存在差异或确定性自检未全通过；本批次结果作废，不能断言"),
    }


def _freeze_copy_programs(programs_dir, dest, frozen=True):
    """同一份封存 programs/ 原样复制：逐字节、带 sha、拒绝覆盖。"""
    files = sorted(p for p in Path(programs_dir).glob("*.ant") if p.is_file())
    if not files:
        raise RuntimeError("programs/ 里没有 *.ant：%s" % programs_dir)
    dest.mkdir(parents=True, exist_ok=False)
    rows = []
    for p in files:
        data = p.read_bytes()
        target = dest / p.name
        if frozen and target.exists():
            raise FileExistsError("拒绝覆盖已冻结 programs/：%s" % target)
        target.write_bytes(data)
        rows.append({"file": p.name, "bytes": len(data), "fileSha256": sha256_bytes(data),
                     "dslSha256": sha256_bytes(p.read_text(encoding="utf-8").encode("utf-8"))})
    return rows


def _traceability(request, programs_rows, run_meta):
    trace = {k: request.get(k) for k in TRACE_KEYS}
    trace["harnessVersion"] = VERSION
    trace["bridgeVersion"] = BRIDGE_VERSION
    trace["reviewRunId"] = run_meta.get("reviewRunId")
    trace["reviewOf"] = run_meta.get("reviewOf")
    trace["pipes"] = run_meta.get("pipes")
    trace["frozenPrograms"] = programs_rows
    trace["dslLink"] = []
    return trace


def _link_dsl(trace, results):
    """把封存 programs/ 的 dslSha256 与桥 cells[].dslSha256 关联起来。"""
    by_hash = {}
    for r in results:
        for c in r.get("cells", []):
            by_hash.setdefault(c.get("dslSha256"), []).append(c.get("cellId"))
    for row in trace["frozenPrograms"]:
        trace["dslLink"].append({"file": row["file"], "dslSha256": row["dslSha256"],
                                 "matchedCellIds": by_hash.get(row["dslSha256"], []),
                                 "matched": bool(by_hash.get(row["dslSha256"]))})
    return trace


def _write_summary_table(path, trace, results, rec):
    """出一张可复核的中文汇总表（不是能力结论）。"""
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "cellId", "species", "ticks", "label", "dslSha256", "valid",
                    "候选分NewFoodPoints", "空白对照分", "ProgramErrors.total", "自检", "备注"])
        for name, payload in results:
            for c in payload.get("cells", []):
                pe = c.get("programErrors") or {}
                w.writerow([name, c.get("cellId"), c.get("species"), c.get("ticks"), c.get("label"),
                            c.get("dslSha256"), c.get("valid"), c.get("score"),
                            c.get("emptyControlScore"), pe.get("total"),
                            (c.get("selfcheck") or {}).get("passed"),
                            "本 harness 下，单批次/区间未判，不能断言"])
        w.writerow([])
        w.writerow(["reconcile 差异数", rec["diffCount"] if rec else "未复核"])
        w.writerow(["结论", "本 harness 下可复跑；未满足独立复核六件套前，不能断言任何能力差异"])


def cmd_reconcile(args):
    left = load_result(args.left)
    right = load_result(args.right)
    rec = reconcile(left, right, {"left": str(args.left), "right": str(args.right)})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print("reconcile：匹配 %d cell，差异 %d，通过=%s → %s" %
          (rec["matchedKeys"], rec["diffCount"], rec["passed"], out))
    return 0 if rec["passed"] else 1


def cmd_run(args):
    request_path = Path(args.request)
    if not request_path.is_file():
        print("找不到 request.json：%s" % request_path, file=sys.stderr)
        return 2
    request = json.loads(request_path.read_text(encoding="utf-8"))
    missing = [k for k in ("batchId", "templateVersion", "strategyId", "promptSha256", "contractVersion")
               if not request.get(k)]
    if missing:
        print("request.json 缺追溯维度：%s" % missing, file=sys.stderr)
        return 2
    if request.get("contractVersion") != "dsl-syntax-0.1.0":
        print("contractVersion 不是 dsl-syntax-0.1.0：%r" % request.get("contractVersion"), file=sys.stderr)
        return 2

    ticks = [int(t) for t in args.ticks.split(",") if t.strip()] if args.ticks else list(request.get("ticks") or STANDARD_TICKS)
    species = [s.strip() for s in args.species.split(",") if s.strip()] if args.species else list(request.get("speciesSet") or SPECIES)
    bad_s = [s for s in species if s not in SPECIES]
    if bad_s:
        print("--species 含不支持蚁种：%s" % bad_s, file=sys.stderr)
        return 2
    if not ticks or not species or any(not 1 <= t <= 1200 for t in ticks):
        print("--ticks 必须 1..1200", file=sys.stderr)
        return 2
    narrowed = (args.ticks is not None) or (args.species is not None)
    standard_full = (list(ticks) == list(STANDARD_TICKS) and list(species) == list(SPECIES))

    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    run_dir = out_root / args.run_id
    if run_dir.exists():
        print("拒绝覆盖已冻结 run-id：%s（换 --run-id 或另选 --out-root）" % run_dir, file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True)

    # 同一份封存 programs/：两次 run 共用这一份字节，控住「题目/语料」混杂变量
    frozen_dir = run_dir / "programs"
    programs_rows = _freeze_copy_programs(args.programs, frozen_dir)
    programs = [str(frozen_dir / r["file"]) for r in programs_rows]
    baseline = Path(args.baseline)
    if not baseline.is_absolute():
        baseline = ROOT / baseline

    base_pipe = request.get("ANTMIND_PIPE") or ("antmind-ab-%s" % request["batchId"])
    runs = [("main", "%s-main-%s" % (base_pipe, args.run_id), "%s-main" % args.run_id)]
    if args.review:
        runs.append(("review", "%s-review-%s" % (base_pipe, args.run_id), "%s-review" % args.run_id))

    results = []
    pipes = {}
    commands = []
    for name, pipe, stem in runs:
        prefix = run_dir / name
        print("[%s] 起独立宿主 pipe=%s slot=%s" % (name, pipe, stem), file=sys.stderr)
        host = None
        try:
            host = start_host(pipe)
            code, output, cmd = run_bridge(pipe, programs, baseline, ticks, species, stem, prefix)
            commands.append({"run": name, "pipe": pipe, "command": cmd, "exitCode": code,
                             "outputTail": output[-2000:]})
            (run_dir / ("%s.bridge.log" % name)).write_text(output, encoding="utf-8")
        finally:
            stop_host(host)
        pipes[name] = pipe
        if code != 0:
            print("[%s] 桥退出码 %d，日志：%s" % (name, code, output[-1200:]), file=sys.stderr)
            return 3
        payload = load_result(Path(str(prefix) + ".json"))
        results.append((name, payload))
        det = payload.get("determinism") or {}
        print("[%s] cell=%d 确定性=%d/%d 输出=%s.json" %
              (name, len(payload.get("cells", [])), det.get("passed", 0), det.get("total", 0), prefix),
              file=sys.stderr)

    rec = None
    if args.review:
        rec = reconcile(results[0][1], results[1][1],
                        {"left": str(run_dir / "main.json"), "right": str(run_dir / "review.json")})
        (run_dir / "reconcile.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    trace = _traceability(request, programs_rows, {
        "reviewRunId": args.run_id if args.review else None,
        "reviewOf": request["batchId"] if args.review else None,
        "pipes": pipes,
    })
    trace = _link_dsl(trace, [p for _, p in results])
    if not all(row["matched"] for row in trace["dslLink"]):
        raise RuntimeError("Frozen program hashes did not match bridge cells")
    trace.update(bridgeVersion=BRIDGE_VERSION, hostSeed=None,
                 seedNote="Host default is 42; runtime seed not exposed or verified",
                 ticks=ticks, speciesSet=species)
    request = dict(request, dslSha256={r["file"]: r["dslSha256"] for r in programs_rows})
    verdict = {
        "capabilityClaimAllowed": False,  # Reproducibility alone is not statistical evidence of superiority.
        "statement": ("本 harness 下可复跑；单批次样例/区间未判，不能断言任何模型、策略、物种、ticks 的能力差异"
                      if (narrowed or not rec or not rec["passed"]) else
                      "reconcile 差异 0 且确定性自检全通过；仍需换会话复核六件套齐全后才允许落能力结论"),
        "standardTicks": list(STANDARD_TICKS),
        "standardSpecies": list(SPECIES),
        "usedTicks": ticks,
        "usedSpecies": species,
        "narrowedSample": narrowed,
        "hostSeed": HOST_SEED,
        "freshPaused": True,
        "bridgeUnmodified": True,
        "bridgeVersion": BRIDGE_VERSION,
    }
    summary = {
        "version": VERSION,
        "generatedAt": utc_now(),
        "runId": args.run_id,
        "traceability": trace,
        "verdict": verdict,
        "commands": commands,
        "reconcile": {"diffCount": rec["diffCount"], "passed": rec["passed"]} if rec else None,
        "determinism": {name: p.get("determinism") for name, p in results},
        "outputs": {"summary": str(run_dir / "harness.json"),
                    "table": str(run_dir / "harness.csv"),
                    "request": str(run_dir / "request.json"),
                    "programs": str(frozen_dir)},
    }
    (run_dir / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "CONDITION.md").write_text(
        "# 运行条件\n\n- runId: `%s`\n- batchId: `%s`\n- strategyId: `%s` / templateVersion: `%s`\n"
        "- promptSha256: `%s`\n- contractVersion: `%s`\n- pipes: `%s`\n"
        "- ticks: `%s`（标准档 %s）\n- species: `%s`（全 5 物种 %s）\n"
        "- 宿主：fresh paused，默认种子42但未从运行时验证，wire18 host `Evaluator.dll --serve`\n"
        "- 同一份封存 programs/：`%s`\n- 桥：`model-eval-bridge.py`，版本见 harness.json，**未改动**\n"
        "- 结论口径：%s\n" %
        (args.run_id, request["batchId"], request["strategyId"], request["templateVersion"],
         request["promptSha256"], request["contractVersion"], json.dumps(pipes, ensure_ascii=False),
         ",".join(str(t) for t in ticks), ",".join(str(t) for t in STANDARD_TICKS),
         ",".join(species), ",".join(SPECIES), frozen_dir, verdict["statement"]),
        encoding="utf-8")
    (run_dir / "harness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_table(run_dir / "harness.csv", trace, results, rec)

    print("harness 完成：%s" % run_dir)
    print("  追溯维度 batchId=%s templateVersion=%s strategyId=%s promptSha256=%s" %
          (request["batchId"], request["templateVersion"], request["strategyId"], request["promptSha256"][:12]))
    print("  ticks=%s species=%s（标准档 %s / 全 5 物种 %s）" %
          (",".join(str(t) for t in ticks), ",".join(species),
           ",".join(str(t) for t in STANDARD_TICKS), ",".join(SPECIES)))
    print("  出表：%s / %s" % (run_dir / "harness.json", run_dir / "harness.csv"))
    if rec:
        print("  reconcile 差异数=%d 通过=%s" % (rec["diffCount"], rec["passed"]))
    print("  %s" % verdict["statement"])
    return 0 if (rec is None or rec["passed"]) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")

    r = sub.add_parser("run", help="跑同题对照矩阵（可 --review 双 pipe 独立复核）")
    r.add_argument("--request", required=True, help="render_prompt.py 产出的 request.json")
    r.add_argument("--programs", required=True, help="封存 programs/ 目录（*.ant 原样复制）")
    r.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="官方默认参照 DSL")
    r.add_argument("--run-id", required=True, help="运行 id；目录已存在拒绝覆盖")
    r.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="产物根（默认 .tmp-eval-harness/，被 gitignore）")
    r.add_argument("--ticks", default=None, help="收窄样例档；不给用 request.json 的 300,600,1200")
    r.add_argument("--species", default=None, help="收窄样例物种；不给用 request.json 的全 5 物种")
    r.add_argument("--review", action="store_true", help="起第二条独立 ANTMIND_PIPE 复核并 reconcile 全字段对账")

    c = sub.add_parser("reconcile", help="对两份 result.json 做全字段对账")
    c.add_argument("--left", required=True)
    c.add_argument("--right", required=True)
    c.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.command == "run":
        return cmd_run(args)
    if args.command == "reconcile":
        return cmd_reconcile(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
