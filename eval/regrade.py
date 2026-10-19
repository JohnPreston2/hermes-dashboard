#!/usr/bin/env python3
"""Re-note les veilles contre DefiLlama, sans LLM et sans regard vers le futur.

Necessite un acces reseau a api.llama.fi (bloque par defaut dans les sessions cloud :
l'ajouter aux domaines autorises de l'environnement). Sur le VPS, il tourne tel quel.

Trois mesures :
  1. accord entre la re-notation independante et le verdict publie par Hermes
  2. taux de base : pour chaque veille, part des fenetres historiques de meme duree
     ou le mouvement demande s'est produit sur cette entite (donnees anterieures a
     l'emission uniquement) -> nombre de veilles tenues attendu sans aucun jugement
  3. regle 0-LLM du benchmark ("flambee fees >= +50 % sur 7 j -> parier -20 % a T+7"),
     d'abord sur la fenetre du benchmark publie (jusqu'au 2026-08-04, attendu 49,1 %),
     puis depuis.

Hypotheses (a confirmer avec le code du pipeline) :
  - fees = frais journaliers DefiLlama (dailyFees), tvl = TVL journaliere
  - une veille est tranchee a 00h45 UTC le jour de l'echeance : la derniere valeur
    complete disponible est celle de la veille de l'echeance
  - les metriques open_interest, funding, price, stablecoin_flow ne sont pas re-notees

Usage : python3 eval/regrade.py [--offline]   (--offline : n'utilise que le cache)
"""
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

DATA = os.path.join("eval", "data")
CACHE = os.path.join(DATA, "llama_cache")
API = "https://api.llama.fi"
BENCH_END = dt.date(2026, 8, 4)
HISTORY_DAYS = 180  # profondeur utilisee pour le taux de base
SEED = 20261019
OFFLINE = "--offline" in sys.argv


def fetch(path):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, urllib.parse.quote(path, safe="") + ".json")
    if os.path.exists(fn):
        with open(fn) as f:
            return json.load(f)
    if OFFLINE:
        return None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(API + path, timeout=30) as r:
                data = json.load(r)
            with open(fn, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:  # reseau ou 404 : on reessaie puis on abandonne cette entite
            err = e
            time.sleep(2 ** attempt)
    print(f"  echec {path}: {err}", file=sys.stderr)
    return None


def norm(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def day(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()


class Llama:
    def __init__(self):
        protocols = fetch("/protocols")
        if not isinstance(protocols, list):
            sys.exit("impossible de lire /protocols : api.llama.fi est-il autorise ?")
        self.slug = {}
        for p in protocols:
            self.slug.setdefault(norm(p.get("name")), p.get("slug"))
        self.cache = {}

    def series(self, entity, metric):
        slug = self.slug.get(norm(entity))
        if not slug:
            return None
        key = (slug, metric)
        if key not in self.cache:
            out = {}
            if metric == "tvl":
                d = fetch(f"/protocol/{slug}") or {}
                for pt in d.get("tvl") or []:
                    out[day(pt["date"])] = pt["totalLiquidityUSD"]
            elif metric == "fees":
                d = fetch(f"/summary/fees/{slug}?dataType=dailyFees") or {}
                for ts, v in d.get("totalDataChart") or []:
                    out[day(ts)] = v
            self.cache[key] = out or None
        return self.cache[key]


def value_at(series, date):
    """Derniere valeur connue au plus tard a `date` (jamais apres)."""
    for back in range(0, 4):
        v = series.get(date - dt.timedelta(days=back))
        if v is not None:
            return v
    return None


def satisfied(op, threshold, v0, v1):
    if op == "delta_pct":
        move = 100 * (v1 / v0 - 1)
        return move >= threshold if threshold >= 0 else move <= threshold
    return v1 >= threshold if op == ">=" else v1 <= threshold


def base_rate(series, op, threshold, v0, seen, horizon):
    """Part des fenetres [t, t+h] anterieures a l'emission ou le meme mouvement relatif
    s'est produit. Pour un seuil absolu, on le traduit en mouvement relatif depuis v0."""
    if op in (">=", "<="):
        rel_thr, up = 100 * (threshold / v0 - 1), op == ">="
    else:
        rel_thr, up = threshold, threshold >= 0
    hits = n = 0
    for k in range(1, HISTORY_DAYS - horizon):
        t1 = seen - dt.timedelta(days=k)  # fenetre entierement anterieure a l'emission
        t0 = t1 - dt.timedelta(days=horizon)
        a, b = series.get(t0), series.get(t1)
        if not a or b is None:
            continue
        move = 100 * (b / a - 1)
        hits += move >= rel_thr if up else move <= rel_thr
        n += 1
    return hits / n if n >= 30 else None


def regrade(watches, llama):
    rows = []
    for w in watches:
        if w["verdict"] not in ("HELD", "BROKEN") or w["metric"] not in ("tvl", "fees"):
            continue
        try:
            thr = float(w["threshold"])
            seen = dt.date.fromisoformat(w["seen"][:10])
            deadline = dt.date.fromisoformat(w["deadline"])
        except (TypeError, ValueError):
            continue
        s = llama.series(w["entity"], w["metric"])
        if not s:
            rows.append({**w, "regrade": "NO_SERIES"})
            continue
        v0 = value_at(s, seen - dt.timedelta(days=1))
        v1 = value_at(s, deadline - dt.timedelta(days=1))
        if not v0 or v1 is None:
            rows.append({**w, "regrade": "NO_VALUE"})
            continue
        ok = satisfied(w["op"], thr, v0, v1)
        horizon = max(1, (deadline - seen).days)
        rows.append({**w, "regrade": "HELD" if ok else "BROKEN", "llama_v0": v0, "llama_v1": v1,
                     "base_rate": base_rate(s, w["op"], thr, v0, seen, horizon)})
    return rows


def rule_zero_llm(llama, entities, start, end):
    """Regle du benchmark : fees(T) >= 1.5 x fees(T-7) -> predire fees(T+7) <= 0.8 x fees(T)."""
    held = n = 0
    for e in sorted(entities):
        s = llama.series(e, "fees")
        if not s:
            continue
        t = start
        while t <= end:
            a, b, c = s.get(t - dt.timedelta(days=7)), s.get(t), s.get(t + dt.timedelta(days=7))
            if a and b and c is not None and b >= 1.5 * a:
                n += 1
                held += c <= 0.8 * b
            t += dt.timedelta(days=1)
    return {"held": held, "n": n, "rate_pct": round(100 * held / n, 1) if n else None,
            "window": [start.isoformat(), end.isoformat()]}


def main():
    with open(os.path.join(DATA, "watches.jsonl")) as f:
        watches = [json.loads(line) for line in f]
    llama = Llama()
    rows = regrade(watches, llama)
    graded = [r for r in rows if r["regrade"] in ("HELD", "BROKEN")]
    agree = sum(r["regrade"] == r["verdict"] for r in graded)
    with_base = [r for r in graded if r["base_rate"] is not None]
    observed = sum(r["regrade"] == "HELD" for r in with_base)
    expected = sum(r["base_rate"] for r in with_base)
    # test : distribution du nombre de succes si chaque veille reussit avec sa probabilite de base
    rng = random.Random(SEED)
    sims = [sum(rng.random() < r["base_rate"] for r in with_base) for _ in range(5000)]
    p = (sum(x >= observed for x in sims) + 1) / (len(sims) + 1)

    fee_entities = {w["entity"] for w in watches if w["metric"] == "fees"}
    today = max(dt.date.fromisoformat(w["deadline"]) for w in watches if w.get("deadline"))
    res = {
        "graded": len(graded),
        "not_graded": {k: sum(r["regrade"] == k for r in rows) for k in ("NO_SERIES", "NO_VALUE")},
        "agreement_with_published_pct": round(100 * agree / len(graded), 1) if graded else None,
        "base_rate": {"n": len(with_base), "observed_held": observed, "expected_held": round(expected, 1),
                      "lift_pts": round(100 * (observed - expected) / len(with_base), 1) if with_base else None,
                      "p_one_sided": round(p, 4)},
        "rule_zero_llm_benchmark_window": rule_zero_llm(llama, fee_entities, BENCH_END - dt.timedelta(days=60),
                                                        BENCH_END - dt.timedelta(days=7)),
        "rule_zero_llm_since": rule_zero_llm(llama, fee_entities, BENCH_END, today - dt.timedelta(days=7)),
        "published_benchmark_rule": {"rate_pct": 49.1, "held": 80, "n": 163},
    }
    with open(os.path.join(DATA, "regrade.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    with open(os.path.join(DATA, "regrade_summary.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
