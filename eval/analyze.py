#!/usr/bin/env python3
"""Mesure ce que valent les veilles de Hermes, a partir des fichiers de reconstruct.py.

Trois sources de verite, de la plus complete a la plus riche :
  A. compteurs publies (watch_stats.csv) : tout le registre, mais seulement des totaux
  B. veilles reconstruites tranchees (watches.jsonl) : ~75 % des verdicts, avec le detail
  C. veilles delta_pct avec mouvement observe : permettent un tirage au hasard
     sur la meme population de predicats (meme principe que la barre "hasard" du benchmark)

Aucun LLM, graine fixe : deux executions donnent les memes chiffres.
Usage : python3 eval/reconstruct.py && python3 eval/analyze.py
"""
import csv
import datetime as dt
import json
import math
import os
import random
import sys

DATA = os.path.join("eval", "data")
SEED = 20261019
N_BOOT = 10000
SHORT_H = 10  # jours : separe les veilles ~7 j des veilles ~30 j


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(100 * (mid - half), 1), round(100 * (mid + half), 1)]


def rate(k, n):
    return {"held": k, "n": n, "rate_pct": round(100 * k / n, 1) if n else None, "ci95": wilson(k, n)}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def holds(threshold, move):
    """Verdict d'une veille delta_pct : seuil positif = hausse au moins egale, negatif = baisse."""
    return move >= threshold if threshold >= 0 else move <= threshold


def horizon_days(w):
    try:
        return (dt.date.fromisoformat(w["deadline"]) - dt.date.fromisoformat(w["seen"][:10])).days
    except (TypeError, ValueError):
        return None


def malformed(w):
    """Predicat absolu dont le seuil n'est pas a l'echelle de la metrique (ex. TVL <= 15.5 $,
    seuil negatif) : perdu par erreur de forme, pas par erreur de jugement."""
    t = num(w["threshold"])
    if w["op"] not in (">=", "<=") or t is None or w["current"] is None:
        return False
    if t <= 0:
        return True
    ratio = w["current"] / t
    return ratio > 20 or ratio < 0.05


def binom_sf(k, n, p):
    """P(X >= k) pour X ~ Binomiale(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


# ── A. compteurs publies : tout le registre, mois par mois ─────────────────
def published(rows):
    srcs = ("L3", "L4", "NEWS")
    last_by_month = {}
    for r in rows:
        last_by_month[r["as_of"][:7]] = r
    out = {"cumulative": {}, "monthly": []}
    last = rows[-1]
    out["cumulative"]["all"] = rate(int(last["held"]), int(last["held"]) + int(last["broken"]))
    for s in srcs:
        h, b = int(last.get(f"{s}_held") or 0), int(last.get(f"{s}_broken") or 0)
        out["cumulative"][s] = rate(h, h + b)

    prev = rows[0]
    out["monthly"].append({"period": f"avant {prev['as_of'][:10]}",
                           "all": rate(int(prev["held"]), int(prev["held"]) + int(prev["broken"]))})
    for month in sorted(last_by_month):
        r = last_by_month[month]
        entry = {"period": month, "until": r["as_of"][:16]}
        dh, db = int(r["held"]) - int(prev["held"]), int(r["broken"]) - int(prev["broken"])
        entry["all"] = rate(dh, dh + db)
        for s in srcs:
            dh = int(r.get(f"{s}_held") or 0) - int(prev.get(f"{s}_held") or 0)
            db = int(r.get(f"{s}_broken") or 0) - int(prev.get(f"{s}_broken") or 0)
            entry[s] = rate(dh, dh + db)
        out["monthly"].append(entry)
        prev = r
    return out


# ── B. veilles reconstruites : par source, metrique, sens, horizon ─────────
def breakdowns(decided):
    def group(keyf):
        g = {}
        for w in decided:
            k = keyf(w)
            if k is None:
                continue
            h, n = g.get(k, (0, 0))
            g[k] = (h + (w["verdict"] == "HELD"), n + 1)
        return {str(k): rate(h, n) for k, (h, n) in sorted(g.items(), key=lambda kv: -kv[1][1])}

    def direction(w):
        t = num(w["threshold"])
        if w["op"] == "delta_pct":
            return "hausse" if t >= 0 else "baisse"
        return "hausse" if w["op"] == ">=" else "baisse"

    def hz(w):
        h = horizon_days(w)
        return None if h is None else ("<=10 j" if h <= SHORT_H else ">10 j")

    held = sum(w["verdict"] == "HELD" for w in decided)
    wellformed = [w for w in decided if not malformed(w)]
    return {
        "all": rate(held, len(decided)),
        "all_wellformed": rate(sum(w["verdict"] == "HELD" for w in wellformed), len(wellformed)),
        "malformed": {"n": len(decided) - len(wellformed),
                      "held": sum(w["verdict"] == "HELD" for w in decided if malformed(w))},
        "by_src": group(lambda w: w["src"]),
        "by_metric": group(lambda w: w["metric"]),
        "by_direction": group(direction),
        "by_horizon": group(hz),
        "by_op": group(lambda w: w["op"]),
        "by_deadline_month": group(lambda w: (w["deadline"] or "")[:7] or None),
    }


def boot_diff(decided, a, b, rng):
    """IC bootstrap de la difference de taux (src a - src b)."""
    xa = [w["verdict"] == "HELD" for w in decided if w["src"] == a]
    xb = [w["verdict"] == "HELD" for w in decided if w["src"] == b]
    if not xa or not xb:
        return None
    diffs = sorted(
        sum(rng.choices(xa, k=len(xa))) / len(xa) - sum(rng.choices(xb, k=len(xb))) / len(xb)
        for _ in range(N_BOOT)
    )
    obs = sum(xa) / len(xa) - sum(xb) / len(xb)
    return {"diff_pct": round(100 * obs, 1),
            "ci95": [round(100 * diffs[int(0.025 * N_BOOT)], 1), round(100 * diffs[int(0.975 * N_BOOT)], 1)],
            "n": [len(xa), len(xb)]}


# ── C. tirage au hasard sur la meme population de predicats ────────────────
def shuffle_baseline(decided, rng):
    """Pour chaque veille delta_pct tranchee, quelle part des mouvements REELLEMENT observes
    sur les AUTRES veilles (meme metrique, meme classe d'horizon) aurait satisfait son seuil ?
    La moyenne donne le taux attendu si le choix de l'entite et du sens n'apportait aucune
    information au-dela du seuil choisi. On teste ensuite le nombre de veilles tenues contre
    cette attente (binomiale de Poisson approximee par permutations)."""
    pool = [w for w in decided if w["op"] == "delta_pct" and w["observed_pct"] is not None
            and num(w["threshold"]) is not None and horizon_days(w) is not None]

    def cls(w):
        return (w["metric"], horizon_days(w) <= SHORT_H)

    expected = []
    for w in pool:
        others = [o["observed_pct"] for o in pool if o is not w and cls(o) == cls(w)]
        if len(others) < 5:
            continue
        expected.append((w, sum(holds(num(w["threshold"]), m) for m in others) / len(others)))
    if not expected:
        return None
    obs = sum(w["verdict"] == "HELD" for w, _ in expected)
    exp = sum(p for _, p in expected)
    # permutation : on redistribue les mouvements observes entre veilles d'une meme classe
    by_cls = {}
    for w, _ in expected:
        by_cls.setdefault(cls(w), []).append(w)
    ge = 0
    n_perm = 2000
    for _ in range(n_perm):
        k = 0
        for ws in by_cls.values():
            moves = [w["observed_pct"] for w in ws]
            rng.shuffle(moves)
            k += sum(holds(num(w["threshold"]), m) for w, m in zip(ws, moves))
        ge += k >= obs
    # sens : le signe du mouvement observe suit-il le sens annonce ?
    signed = [(num(w["threshold"]), w["observed_pct"]) for w, _ in expected if w["observed_pct"] != 0]
    right = sum((t >= 0) == (m > 0) for t, m in signed)
    ups = sum(m > 0 for _, m in signed)
    bull = sum(t >= 0 for t, _ in signed)
    # taux de sens attendu si le sens annonce etait independant du sens realise
    p_dir = (bull / len(signed)) * (ups / len(signed)) + (1 - bull / len(signed)) * (1 - ups / len(signed))
    return {
        "n": len(expected),
        "observed": rate(obs, len(expected)),
        "expected_rate_pct": round(100 * exp / len(expected), 1),
        "lift_pts": round(100 * (obs - exp) / len(expected), 1),
        "p_perm_one_sided": round((ge + 1) / (n_perm + 1), 4),
        "direction": {"n": len(signed), "right": right, "rate_pct": round(100 * right / len(signed), 1),
                      "expected_if_independent_pct": round(100 * p_dir, 1),
                      "p_binom_one_sided": round(binom_sf(right, len(signed), p_dir), 4),
                      "share_bullish_calls_pct": round(100 * bull / len(signed), 1),
                      "share_up_moves_pct": round(100 * ups / len(signed), 1)},
    }


# ── E. controle croise TVL avec les series des snapshots (si series.py a tourne) ──
def tvl_crosscheck(decided):
    """Valeurs TVL publiees par les AUTRES blocs du dashboard (macro, movers, curator) :
    independantes du correcteur de veilles, mais pas de la source amont."""
    path = os.path.join(DATA, "series.csv")
    if not os.path.exists(path):
        return None
    series = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["metric"] == "tvl_usd":
                series.setdefault(r["entity"], []).append((r["as_of"], float(r["value"])))

    def at(entity, ts):
        pts = [p for p in series.get(entity, []) if p[0] <= ts]
        return max(pts)[1] if pts else None

    tvl = [w for w in decided if w["metric"] == "tvl"]
    out = {"n_tvl_decided": len(tvl), "no_series": 0, "no_value": 0, "graded": []}
    for w in tvl:
        if w["entity"] not in series:
            out["no_series"] += 1
            continue
        v0, v1 = at(w["entity"], w["seen"]), at(w["entity"], w["deadline"] + "T00:45:00Z")
        t = num(w["threshold"])
        if not v0 or v1 is None or t is None:
            out["no_value"] += 1
            continue
        ok = holds(t, 100 * (v1 / v0 - 1)) if w["op"] == "delta_pct" else (v1 >= t if w["op"] == ">=" else v1 <= t)
        required = t if w["op"] == "delta_pct" else 100 * (t / v0 - 1)
        out["graded"].append({"entity": w["entity"], "op": w["op"], "threshold": t, "seen": w["seen"],
                              "deadline": w["deadline"], "required_move_pct": round(required, 1),
                              "realized_move_pct": round(100 * (v1 / v0 - 1), 1),
                              "crosscheck": "HELD" if ok else "BROKEN", "published": w["verdict"]})
    g = out["graded"]
    out["agreement"] = f"{sum(x['crosscheck'] == x['published'] for x in g)}/{len(g)}"
    return out


# ── D. pertes : veilles jamais tranchees publiquement ──────────────────────
def coverage(watches, last_stats, today):
    open_past = [w for w in watches if w["verdict"] == "OPEN" and (w["deadline"] or "9") < today]
    pub_decided = int(last_stats["held"]) + int(last_stats["broken"])
    rec_decided = sum(w["verdict"] in ("HELD", "BROKEN") for w in watches)
    return {
        "reconstructed": len(watches),
        "published_total": int(last_stats["total"]),
        "published_rejected": int(last_stats["rejected"]),
        "decided_published": pub_decided,
        "decided_reconstructed": rec_decided,
        "decided_capture_pct": round(100 * rec_decided / pub_decided, 1) if pub_decided else None,
        "open_past_deadline_never_seen_decided": len(open_past),
        "unevaluable_reconstructed": sum(w["verdict"] == "UNEVALUABLE" for w in watches),
    }


def main():
    rng = random.Random(SEED)
    with open(os.path.join(DATA, "watch_stats.csv")) as f:
        rows = list(csv.DictReader(f))
    with open(os.path.join(DATA, "watches.jsonl")) as f:
        watches = [json.loads(line) for line in f]
    decided = [w for w in watches if w["verdict"] in ("HELD", "BROKEN")]
    today = rows[-1]["as_of"][:10]

    res = {
        "generated_from": {"last_snapshot": rows[-1]["as_of"], "snapshots": len(rows), "seed": SEED},
        "coverage": coverage(watches, rows[-1], today),
        "published": published(rows),
        "reconstructed": breakdowns(decided),
        "l3_minus_l4": boot_diff(decided, "L3", "L4", rng),
        "shuffle_baseline": shuffle_baseline(decided, rng),
        "tvl_crosscheck": tvl_crosscheck(decided),
    }
    with open(os.path.join(DATA, "benchmark_history.json")) as f:
        bench = json.load(f)
    res["published_benchmark"] = bench[-1] if bench else None

    with open(os.path.join(DATA, "analysis.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    p, r, s, c = res["published"], res["reconstructed"], res["shuffle_baseline"], res["coverage"]
    print(f"couverture : {c['decided_reconstructed']}/{c['decided_published']} verdicts publies retrouves "
          f"({c['decided_capture_pct']} %), {c['open_past_deadline_never_seen_decided']} veilles echues jamais vues tranchees")
    print("registre publie, cumul :", {k: (v["rate_pct"], v["ci95"], v["n"]) for k, v in p["cumulative"].items()})
    for m in p["monthly"]:
        print("  ", m["period"], {k: (v["rate_pct"], v["n"]) for k, v in m.items() if isinstance(v, dict)})
    print("reconstruit :", (r["all"]["rate_pct"], r["all"]["ci95"], r["all"]["n"]),
          "| sans predicats mal formes :", (r["all_wellformed"]["rate_pct"], r["all_wellformed"]["n"]),
          "| mal formes :", r["malformed"])
    for k in ("by_src", "by_metric", "by_direction", "by_horizon"):
        print(f"  {k}:", {kk: (vv["rate_pct"], vv["n"]) for kk, vv in r[k].items()})
    print("L3 - L4 :", res["l3_minus_l4"])
    if s:
        print(f"hasard sur la meme population (delta_pct, n={s['n']}) : observe {s['observed']['rate_pct']} % "
              f"vs attendu {s['expected_rate_pct']} % -> lift {s['lift_pts']} pts, p={s['p_perm_one_sided']}")
        d = s["direction"]
        print(f"  sens juste : {d['right']}/{d['n']} = {d['rate_pct']} % vs {d['expected_if_independent_pct']} % "
              f"attendu (p={d['p_binom_one_sided']}) ; appels haussiers {d['share_bullish_calls_pct']} %, "
              f"mouvements haussiers {d['share_up_moves_pct']} %")
    x = res["tvl_crosscheck"]
    if x:
        print(f"controle croise TVL : {len(x['graded'])}/{x['n_tvl_decided']} re-notables, accord {x['agreement']} "
              f"(sans serie : {x['no_series']}, sans valeur : {x['no_value']})")
        for g in x["graded"]:
            print(f"   {g['entity']} {g['op']} {g['threshold']:g} : demande {g['required_move_pct']:+} %, "
                  f"realise {g['realized_move_pct']:+} % -> {g['crosscheck']} (publie {g['published']})")


if __name__ == "__main__":
    sys.exit(main())
