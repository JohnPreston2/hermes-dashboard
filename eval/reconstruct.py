#!/usr/bin/env python3
"""Reconstruit le registre des veilles a partir de l'historique git de data.json.

Chaque snapshot ne montre qu'une partie du registre (~100 veilles sur ~600) :
on parcourt donc TOUS les snapshots et on garde, pour chaque veille, la suite
de ses etats successifs. Aucune donnee n'est recalculee ici : on ne fait que
relire ce que le pipeline a publie.

Sorties (eval/data/) :
  watches.jsonl          une ligne par veille, etat final + transitions
  watch_stats.csv        compteurs publies par le dashboard, snapshot par snapshot
  benchmark_history.json versions successives du benchmark publie

Usage : python3 eval/reconstruct.py   (depuis la racine du repo)
"""
import csv
import json
import os
import subprocess
import sys

OUT = os.path.join("eval", "data")
SINCE = "2026-08-03"  # premier snapshot qui porte le bloc watches (schema 2)
TERMINAL = ("HELD", "BROKEN", "UNEVALUABLE")
# champs qui peuvent evoluer pendant la vie d'une veille
MUTABLE = ("verdict", "decided", "observed_pct", "current", "note", "scale_odd", "baseline", "baseline_src")


def snapshots():
    out = subprocess.run(
        ["git", "log", "--reverse", "--format=%H %cI", "--", "data.json"],
        capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        sha, ts = line.split()
        if ts[:10] >= SINCE:
            yield sha, ts


class Blobs:
    """Lecture rapide des blobs via un seul `git cat-file --batch`."""

    def __init__(self):
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def get(self, sha, path):
        self.p.stdin.write(f"{sha}:{path}\n".encode())
        self.p.stdin.flush()
        hdr = self.p.stdout.readline().split()
        if len(hdr) < 3:
            return None
        size = int(hdr[2])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        return data


def watch_key(w):
    # `seen` = entree au registre : distingue deux veilles identiques reemises
    return "|".join(str(w.get(k)) for k in ("entity", "metric", "op", "threshold", "deadline", "src", "seen"))


def main():
    os.makedirs(OUT, exist_ok=True)
    blobs = Blobs()
    reg = {}
    stats_rows = []
    benchmarks = {}
    n_snap = n_bad = 0

    for sha, commit_ts in snapshots():
        raw = blobs.get(sha, "data.json")
        try:
            d = json.loads(raw) if raw else None
        except ValueError:
            d = None
        blk = (d or {}).get("blocks", {}).get("watches") if isinstance(d, dict) else None
        if not blk or not isinstance(blk.get("v"), dict):
            n_bad += 1
            continue
        n_snap += 1
        v = blk["v"]
        as_of = blk.get("as_of")

        s = v.get("stats") or {}
        bv = s.get("by_verdict") or {}
        row = {"commit_ts": commit_ts, "as_of": as_of, "total": s.get("total"),
               "rejected": s.get("rejected"), **{k.lower(): bv.get(k) for k in ("HELD", "BROKEN", "OPEN", "UNEVALUABLE")}}
        for src, x in (s.get("by_src") or {}).items():
            row[f"{src}_held"], row[f"{src}_broken"] = x.get("held"), x.get("broken")
        stats_rows.append(row)

        b = s.get("benchmark")
        if b:
            sig = json.dumps({k: b.get(k) for k in ("measured_at", "session", "bars", "fisher_p")}, sort_keys=True)
            benchmarks.setdefault(sig, {"first_seen": commit_ts, **b})["last_seen"] = commit_ts

        for w in v.get("items") or []:
            k = watch_key(w)
            rec = reg.get(k)
            if rec is None:
                rec = reg[k] = {
                    **{f: w.get(f) for f in ("entity", "metric", "op", "threshold", "deadline", "src", "seen", "why")},
                    "first_snapshot": as_of, "states": [],
                }
            state = {f: w.get(f) for f in MUTABLE}
            last = rec["states"][-1] if rec["states"] else None
            if last is None or any(last[f] != state[f] for f in MUTABLE):
                rec["states"].append({"as_of": as_of, **state})
            rec["last_snapshot"] = as_of

    for rec in reg.values():
        verdicts = [st["verdict"] for st in rec["states"]]
        terminal = [st for st in rec["states"] if st["verdict"] in TERMINAL]
        final = terminal[-1] if terminal else rec["states"][-1]
        rec.update({f: final[f] for f in MUTABLE})
        rec["verdict_path"] = [x for i, x in enumerate(verdicts) if i == 0 or x != verdicts[i - 1]]
        # une veille tranchee qui change ensuite de verdict terminal = incoherence a signaler
        rec["terminal_flips"] = sum(1 for a, b in zip(terminal, terminal[1:]) if a["verdict"] != b["verdict"])

    with open(os.path.join(OUT, "watches.jsonl"), "w") as f:
        for k in sorted(reg, key=lambda k: (reg[k]["seen"] or "", k)):
            f.write(json.dumps(reg[k], ensure_ascii=False) + "\n")

    cols = sorted({c for r in stats_rows for c in r}, key=lambda c: (c not in ("commit_ts", "as_of"), c))
    with open(os.path.join(OUT, "watch_stats.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(stats_rows)

    with open(os.path.join(OUT, "benchmark_history.json"), "w") as f:
        json.dump(list(benchmarks.values()), f, ensure_ascii=False, indent=1)

    by_v = {}
    for rec in reg.values():
        by_v[rec["verdict"]] = by_v.get(rec["verdict"], 0) + 1
    last = stats_rows[-1] if stats_rows else {}
    print(f"snapshots lus: {n_snap} (ignores: {n_bad})")
    print(f"veilles reconstruites: {len(reg)}  {dict(sorted(by_v.items()))}")
    print(f"registre publie (dernier snapshot): total={last.get('total')} rejected={last.get('rejected')} "
          f"held={last.get('held')} broken={last.get('broken')} open={last.get('open')} unevaluable={last.get('unevaluable')}")
    print(f"veilles avec flip de verdict terminal: {sum(1 for r in reg.values() if r['terminal_flips'])}")
    print(f"versions du benchmark: {len(benchmarks)}")


if __name__ == "__main__":
    sys.exit(main())
