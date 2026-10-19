#!/usr/bin/env python3
"""Evaluation des « convictions » du livre de theses de Hermes.

Reconstruit, a partir de TOUS les snapshots de data.json (historique git),
le journal deduplique des evaluations de theses + l'union des points
`history`, ecrit `eval/data/thesis_assessments.jsonl` et affiche les chiffres
cles qui alimentent `eval/THESES.md`.

Usage (depuis la racine du repo, Python 3, bibliotheque standard seule) :

    python3 eval/theses.py              # historique jusqu'a HEAD
    python3 eval/theses.py --rev <sha>  # fige l'analyse a un commit

Perimetre : snapshots dont la date de commit (UTC) est >= 2026-07-09.
Schema 1 : d['theses'] (liste) ; schema 2 : d['blocks']['theses']['v'] (liste
dans les premiers snapshots, puis dict avec 'items').
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

CUTOFF = datetime(2026, 7, 9, tzinfo=timezone.utc)
YEAR = 2026                      # `history[].ts` est « MM-JJ » sans annee
OUT_REL = os.path.join("eval", "data", "thesis_assessments.jsonl")
TOL = 0.05                       # « ≈ x » pour les allers-retours x -> 0 -> ≈x


# --------------------------------------------------------------------------
# Lecture de l'historique git
# --------------------------------------------------------------------------
def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def repo_root():
    return git("rev-parse", "--show-toplevel").decode().strip()


def list_snapshots(rev):
    out = git("log", "--reverse", "--format=%H %cI", rev, "--", "data.json").decode()
    snaps = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, iso = line.split()
        t = datetime.fromisoformat(iso).astimezone(timezone.utc)
        if t >= CUTOFF:
            snaps.append((sha, t))
    snaps.sort(key=lambda s: s[1])          # tri stable : ordre git en cas d'egalite
    return snaps


def iter_snapshots(snaps):
    """Rend (sha, t, dict|None) via un unique `git cat-file --batch`."""
    p = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE)
    try:
        for sha, t in snaps:
            p.stdin.write(f"{sha}:data.json\n".encode())
            p.stdin.flush()
            hdr = p.stdout.readline().decode().split()
            if len(hdr) < 3:                 # « <obj> missing »
                yield sha, t, None
                continue
            body = p.stdout.read(int(hdr[2]))
            p.stdout.read(1)                 # LF final
            try:
                yield sha, t, json.loads(body)
            except ValueError:
                yield sha, t, None
    finally:
        p.stdin.close()
        p.wait()


def schema_of(d):
    return 2 if "blocks" in d else 1


def thesis_items(d):
    if schema_of(d) == 2:
        v = ((d.get("blocks") or {}).get("theses") or {}).get("v")
    else:
        v = d.get("theses")
    if isinstance(v, dict):
        return v.get("items") or []
    return v if isinstance(v, list) else []


def brief_list(d):
    if schema_of(d) == 2:
        v = ((d.get("blocks") or {}).get("briefs") or {}).get("v")
    else:
        v = d.get("briefs")
    return v if isinstance(v, list) else []


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Reconstruction : journal des evaluations + union des points history
# --------------------------------------------------------------------------
def reconstruct(snaps):
    asm = {}          # (key, ts)  -> record d'evaluation
    hist = {}         # (key, day) -> record de point history
    briefs = {}       # (ts, tier, mode) -> brief (premiere version vue)
    cur_hist = []     # history de chaque item du DERNIER snapshot (verification)
    conflicts = Counter()
    n_by_schema = Counter()
    n_missing = 0
    last = None
    for sha, t, d in iter_snapshots(snaps):
        if d is None:
            n_missing += 1
            continue
        sch = schema_of(d)
        n_by_schema[sch] += 1
        last = (sha, t, d)
        for it in thesis_items(d):
            k = (it["key"], it["ts"])
            r = asm.get(k)
            if r is None:
                r = asm[k] = {
                    "kind": "assessment", "key": it["key"], "ts": it["ts"],
                    "verdict": it["verdict"], "conviction": it["conviction"],
                    "trigger": it["trigger"], "kill": it["kill"],
                    "kill_first": it["kill"], "kill_all": [it["kill"]],
                    "first_seen": iso(t), "last_seen": iso(t), "n_snapshots": 0,
                    "schema_first": sch, "n_ledger": None,
                }
            for f in ("verdict", "conviction", "trigger"):
                if r[f] != it[f]:
                    conflicts[f] += 1
            r["n_snapshots"] += 1
            r["last_seen"] = iso(t)
            r["kill"] = it["kill"]
            if it["kill"] not in r["kill_all"]:
                r["kill_all"].append(it["kill"])
            if "n" in it:
                r["n_ledger"] = it["n"]
            for h in it.get("history") or []:
                hk = (it["key"], f"{YEAR}-{h['ts']}")
                hr = hist.get(hk)
                val = {"c": h["c"], "v": h.get("v")}
                if hr is None:
                    hr = hist[hk] = {
                        "kind": "history_point", "key": it["key"], "day": hk[1],
                        "variants": [], "first_seen": iso(t),
                    }
                if val not in hr["variants"]:
                    hr["variants"].append(val)
                hr["conviction"], hr["v"] = h["c"], h.get("v")   # derniere valeur vue
                hr["last_seen"] = iso(t)
        for b in brief_list(d):
            briefs.setdefault((b["ts"], b.get("tier"), b.get("mode")), b)
    if last is not None:
        cur_hist = [(it["key"], [h["c"] for h in it.get("history") or []])
                    for it in thesis_items(last[2])]
    return asm, hist, briefs, cur_hist, last, conflicts, n_by_schema, n_missing


def enrich(asm, hist):
    """Champs derives : precedent, delta, restatement ; rattachement history -> journal."""
    by_key = defaultdict(list)
    for r in asm.values():
        by_key[r["key"]].append(r)
    for key, rs in by_key.items():
        rs.sort(key=lambda r: r["ts"])
        prev = None
        for r in rs:
            r["entity"], _, r["topic"] = key.partition("::")
            r["pre_cutoff"] = r["ts"] < CUTOFF.strftime("%Y-%m-%d")
            if prev is None:
                r.update(prev_ts=None, prev_verdict=None, prev_conviction=None,
                         delta=None, restated=False)
            else:
                r.update(prev_ts=prev["ts"], prev_verdict=prev["verdict"],
                         prev_conviction=prev["conviction"],
                         delta=round(r["conviction"] - prev["conviction"], 4),
                         restated=(r["verdict"], r["conviction"], r["trigger"]) ==
                                  (prev["verdict"], prev["conviction"], prev["trigger"]))
            prev = r
    day_idx = defaultdict(list)
    for r in asm.values():
        day_idx[(r["key"], r["ts"][:10])].append(r)
    for hk, hr in hist.items():
        rs = sorted(day_idx.get(hk, []), key=lambda r: r["ts"])
        hr["n_variants"] = len(hr["variants"])
        hr["journal_verdict"] = rs[-1]["verdict"] if rs else None
        hr["journal_conviction"] = rs[-1]["conviction"] if rs else None
        hr["matches_journal"] = (None if not rs else
                                 (rs[-1]["conviction"] == hr["conviction"] and
                                  (rs[-1]["verdict"] == "revise") == (hr["v"] == "revise")))
    return by_key


# --------------------------------------------------------------------------
# Classifieurs textuels (heuristiques, regex ordonnees)
# --------------------------------------------------------------------------
RETIRE_RULES = [
    ("deja_retire", r"marked retired in priors|retirement stands"),
    ("faits_contraires", r"invalidat|collapse|critical exploit|captures? 0%|token capture remains|"
                         r"compression|fees compress|trailing peer|divergence between|"
                         r"lacks evidence in protocol economics"),
    ("donnees_absentes", r"data absent|\bno (\w+ )?data\b|lack of data|lacks .{0,12}data|null tvl|data failure|"
                         r"cannot be evaluated|insufficient|no live|no relevant|unable to address|"
                         r"no new data"),
    ("remplacee_ou_focus", r"supersed|rebrand|focus shift|shifts? (in|to)|shifted|moot|replaced"),
    ("stable_ou_acquise", r"stable|stabili[sz]ed|base case|no further research edge|solidified|"
                          r"maintains|persists|continues to demonstrate|no longer|validates"),
]
RETIRE_RULES = [(n, re.compile(p, re.I)) for n, p in RETIRE_RULES]


def retire_reason(trigger):
    for name, rx in RETIRE_RULES:
        if rx.search(trigger or ""):
            return name
    return "autre"


# « pas de substance » dans le trigger, quel que soit le verdict
NO_EVIDENCE = re.compile(
    r"^(n/?a\b|no (new|direct|relevant|live|contradict)|nothing|lack of|insufficient|"
    r"digest lacks|null tvl|data failure)|"
    r"no (new|relevant|digest) data|no contradictory|lack of (fundamental )?data|"
    r"no live reg news", re.I)

NUM_RE = re.compile(r"\$\s?\d|\d[\d.,]*\s?(%|bps|x\b|[kKmMbB]\b|million|billion|percent)")
HOR_RE = re.compile(
    r"(next|coming|following)\s+(\d+|one|two|three|four|six|few)?\s*(day|week|month|quarter|year|hour)s?|"
    r"within\s+(the\s+)?(next\s+)?(\d+|one|two|three|quarter|month|week)|\b\d+[- ](day|week|month)s?\b|"
    r"\bby\s+(Q[1-4]|end of|20\d\d)|\bQ[1-4]\s*20\d\d|\b20\d\d-\d\d-\d\d|quarterly|"
    r"(next|this)\s+(quarter|month|year|week)", re.I)


def kill_class(text):
    t = (text or "").strip()
    if not t:
        return "vide"
    num, hor = bool(NUM_RE.search(t)), bool(HOR_RE.search(t))
    if num and hor:
        return "mesurable"            # nombre + horizon (lecture lache)
    if hor:
        return "vague_avec_horizon"   # « Monitor X over the next quarter » : pas de seuil
    return "vague_sans_horizon"


# --------------------------------------------------------------------------
# Statistiques de sauts / allers-retours
# --------------------------------------------------------------------------
def jump_stats(series, tol=TOL):
    """series : {key: [(label, conviction), ...]} trie dans le temps."""
    s = Counter()
    trips, dead_end, starts0 = [], [], []
    for key, pts in series.items():
        v = [c for _, c in pts]
        s["points"] += len(v)
        s["series"] += 1
        for (la, a), (lb, b) in zip(pts, pts[1:]):
            d = abs(b - a)
            s["transitions"] += 1
            if d > 1e-9:
                s["changed"] += 1
            if d >= 0.5 - 1e-9:
                s["ge05"] += 1
                if a == 0 or b == 0:
                    s["ge05_zero"] += 1
            if d >= 0.8 - 1e-9:
                s["ge08"] += 1
                if a == 0 or b == 0:
                    s["ge08_zero"] += 1
        i, n = 0, len(v)
        while i < n:
            if v[i] != 0:
                i += 1
                continue
            j = i
            while j + 1 < n and v[j + 1] == 0:
                j += 1
            if i == 0:
                starts0.append((key, pts[i][0], pts[j][0]))
            elif j == n - 1:
                dead_end.append((key, pts[i - 1][0], pts[i - 1][1], pts[i][0]))
            else:
                x, y = v[i - 1], v[j + 1]
                s["zero_runs_interior"] += 1
                rt = abs(y - x) <= tol + 1e-9
                ex = abs(y - x) <= 1e-9
                s["roundtrip"] += rt
                s["roundtrip_exact"] += ex
                if x >= 0.8 - 1e-9:
                    s["interior_from_ge08"] += 1
                    s["roundtrip_from_ge08"] += rt
                trips.append((key, pts[i - 1][0], x, pts[i][0], pts[j][0], pts[j + 1][0], y, rt, ex))
            i = j + 1
    s["zero_runs_dead_end"] = len(dead_end)
    s["zero_runs_start"] = len(starts0)
    return s, trips, dead_end


def jumps_in_roundtrips(series, tol=TOL):
    """Parmi les sauts >= 0.8, combien appartiennent a un aller-retour x->0->≈x."""
    tot = in_rt = 0
    for key, pts in series.items():
        v = [c for _, c in pts]
        n = len(v)
        # indices des runs de zeros interieurs qui reviennent a ≈x
        rt_edges = set()
        i = 0
        while i < n:
            if v[i] != 0:
                i += 1
                continue
            j = i
            while j + 1 < n and v[j + 1] == 0:
                j += 1
            if i > 0 and j < n - 1 and abs(v[j + 1] - v[i - 1]) <= tol + 1e-9:
                rt_edges.add((i - 1, i))       # transition x -> 0
                rt_edges.add((j, j + 1))       # transition 0 -> ≈x
            i = j + 1
        for idx, (a, b) in enumerate(zip(v, v[1:])):
            if abs(b - a) >= 0.8 - 1e-9:
                tot += 1
                if (idx, idx + 1) in rt_edges:
                    in_rt += 1
    return tot, in_rt


def pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "n/a"


def bucket(c):
    if c == 0:
        return "0"
    if c < 0.5:
        return "]0;0.5["
    if c < 0.8:
        return "[0.5;0.8["
    return "[0.8;1]"


BUCKETS = ["0", "]0;0.5[", "[0.5;0.8[", "[0.8;1]"]


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rev", default="HEAD", help="commit jusqu'auquel lire l'historique (defaut HEAD)")
    ap.add_argument("--out", default=OUT_REL, help="fichier JSONL de sortie")
    args = ap.parse_args()

    os.chdir(repo_root())
    snaps = list_snapshots(args.rev)
    asm, hist, briefs, cur_hist, last, conflicts, n_by_schema, n_missing = reconstruct(snaps)
    by_key = enrich(asm, hist)
    A = sorted(asm.values(), key=lambda r: (r["key"], r["ts"]))
    H = sorted(hist.values(), key=lambda r: (r["key"], r["day"]))
    for r in A:
        if r["verdict"] == "retire":
            r["retire_reason"] = retire_reason(r["trigger"])
        r["kill_class"] = kill_class(r["kill"])

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    order_a = ["kind", "key", "entity", "topic", "ts", "verdict", "conviction", "trigger", "kill",
               "kill_first", "kill_all", "kill_class", "retire_reason", "prev_ts", "prev_verdict",
               "prev_conviction", "delta", "restated", "n_ledger", "first_seen", "last_seen",
               "n_snapshots", "schema_first", "pre_cutoff"]
    order_h = ["kind", "key", "day", "conviction", "v", "n_variants", "variants", "journal_verdict",
               "journal_conviction", "matches_journal", "first_seen", "last_seen"]
    with open(args.out, "w", encoding="utf-8") as f:
        for r in A:
            f.write(json.dumps({k: r[k] for k in order_a if k in r}, ensure_ascii=False) + "\n")
        for r in H:
            f.write(json.dumps({k: r[k] for k in order_h if k in r}, ensure_ascii=False) + "\n")

    out = print
    sha_last, t_last, _ = last
    out("=" * 78)
    out("0. COUVERTURE")
    out("=" * 78)
    out(f"rev={args.rev}  snapshots >= {CUTOFF.date()} : {len(snaps)} "
        f"(lus {sum(n_by_schema.values())}, manquants/illisibles {n_missing}; "
        f"schema 1 : {n_by_schema[1]}, schema 2 : {n_by_schema[2]})")
    out(f"premier {iso(snaps[0][1])}  dernier {iso(t_last)} ({sha_last[:10]})")
    out(f"evaluations distinctes (key, ts) : {len(A)} ; cles : {len(by_key)} ; "
        f"conflits verdict/conviction/trigger pour un meme (key, ts) : {dict(conflicts) or 0}")
    out(f"  dont ts < 2026-07-09 (portees par les premiers snapshots, conservees) : "
        f"{sum(r['pre_cutoff'] for r in A)}")
    out(f"  ts min {A and min(r['ts'] for r in A)}  max {max(r['ts'] for r in A)}")
    out(f"  restatements (meme verdict+conviction+trigger que l'eval precedente de la cle) : "
        f"{sum(r['restated'] for r in A)} / {len(A)} ({pct(sum(r['restated'] for r in A), len(A))})")
    ledger = {}
    for r in A:
        if r["n_ledger"] is not None:
            ledger[r["key"]] = max(ledger.get(r["key"], 0), r["n_ledger"])
    out(f"  ledger : somme des `n` (dernier vu par cle) = {sum(ledger.values())} "
        f"vs {sum(len(by_key[k]) for k in ledger)} evaluations reconstruites "
        f"-> couverture {pct(sum(len(by_key[k]) for k in ledger), sum(ledger.values()))}")
    nh_conf = sum(1 for h in H if h["n_variants"] > 1)
    nh_nojn = sum(1 for h in H if h["matches_journal"] is None)
    nh_ok = sum(1 for h in H if h["matches_journal"] is True)
    nh_ko = sum(1 for h in H if h["matches_journal"] is False)
    out(f"points history (key, jour) : {len(H)} ; reecrits dans la journee (>=2 valeurs vues) : {nh_conf} ; "
        f"sans eval journal le meme jour : {nh_nojn} ; "
        f"= derniere eval du jour : {nh_ok}/{nh_ok + nh_ko}")
    out(f"  historique : jours {min(h['day'] for h in H)} -> {max(h['day'] for h in H)} ; "
        f"tag `v` observes : {dict(Counter(h['v'] for h in H))}")
    ents = Counter(r["entity"] for r in A)
    out(f"  evaluations par entite : {dict(ents.most_common())}")
    out(f"-> ecrit {args.out} ({len(A)} evaluations + {len(H)} points history)")

    # ---------------------------------------------------------------- verif prelim.
    out("\n" + "=" * 78)
    out("VERIFICATION de l'observation preliminaire (history du DERNIER snapshot)")
    out("=" * 78)
    vals = [c for _, cs in cur_hist for c in cs]
    trs = [(a, b) for _, cs in cur_hist for a, b in zip(cs, cs[1:])]
    z8 = sum(1 for v in vals if v == 0 or v >= 0.8)
    z75 = sum(1 for v in vals if v == 0 or v >= 0.75)
    out(f"{len(cur_hist)} items, {len(vals)} valeurs ; 0 ou >=0.8 : {z8} ({pct(z8, len(vals))}) ; "
        f"0 ou >=0.75 : {z75} ({pct(z75, len(vals))})")
    out(f"transitions {len(trs)} ; |d|>=0.5 : {sum(1 for a, b in trs if abs(a - b) >= 0.5 - 1e-9)} ; "
        f"|d|>=0.8 : {sum(1 for a, b in trs if abs(a - b) >= 0.8 - 1e-9)}")

    # ---------------------------------------------------------------- Q2
    out("\n" + "=" * 78)
    out("Q2. SENS DE conviction = 0")
    out("=" * 78)
    tab = Counter((r["verdict"], bucket(r["conviction"])) for r in A)
    out(f"{'verdict':8s} " + " ".join(f"{b:>10s}" for b in BUCKETS) + "     total")
    for v in ("confirm", "revise", "retire"):
        row = [tab[(v, b)] for b in BUCKETS]
        out(f"{v:8s} " + " ".join(f"{x:10d}" for x in row) + f"  {sum(row):8d}")
    other = sorted({r["verdict"] for r in A} - {"confirm", "revise", "retire"})
    out(f"autres verdicts : {other or 'aucun'} ; conviction nulle/absente (None) : "
        f"{sum(1 for r in A if r['conviction'] is None)}")
    z = [r for r in A if r["conviction"] == 0]
    zr = Counter(r["verdict"] for r in z)
    out(f"conviction == 0 : {len(z)} evaluations -> {dict(zr)}")
    ret = [r for r in A if r["verdict"] == "retire"]
    r0 = [r for r in ret if r["conviction"] == 0]
    rp = [r for r in ret if r["conviction"] > 0]
    out(f"retire : {len(ret)} dont conviction 0 : {len(r0)} ({pct(len(r0), len(ret))}) ; "
        f"conviction > 0 : {len(rp)} (ts {min(r['ts'] for r in rp)} .. {max(r['ts'] for r in rp)}, "
        f"valeurs {sorted(Counter(r['conviction'] for r in rp).items())})")
    out(f"  retire/0 : ts {min(r['ts'] for r in r0)} .. {max(r['ts'] for r in r0)} ; "
        f"retire a partir de {max(r['ts'] for r in rp)} : "
        f"{sum(1 for r in ret if r['ts'] > max(x['ts'] for x in rp))} dont conviction>0 : "
        f"{sum(1 for r in ret if r['ts'] > max(x['ts'] for x in rp) and r['conviction'] > 0)}")
    for r in z:
        if r["verdict"] != "retire":
            out(f"  zero non-retire : {r['key']} {r['ts']} {r['verdict']} prev={r['prev_verdict']}/"
                f"{r['prev_conviction']} @ {r['prev_ts']} trigger={r['trigger'][:90]!r}")
    # points history a 0
    h0 = [h for h in H if h["conviction"] == 0]
    out(f"points history a 0 : {len(h0)} -> verdict journal du jour : "
        f"{dict(Counter(h['journal_verdict'] for h in h0))}")
    out(f"points history `v`=='revise' : {sum(1 for h in H if h['v'] == 'revise')} ; retire n'a pas de tag `v` "
        f"(history ne distingue pas retire de confirm)")
    rr = Counter(r["retire_reason"] for r in r0)
    rrd = Counter(reason for reason in {(r["key"], r["trigger"]): r["retire_reason"] for r in r0}.values())
    out(f"motif du retire a 0 (regex sur trigger, n={len(r0)} evaluations) : {dict(rr.most_common())}")
    out(f"  idem sur claims distincts (key, trigger), n={sum(rrd.values())} : {dict(rrd.most_common())}")
    for name in [n for n, _ in RETIRE_RULES] + ["autre"]:
        ex = sorted({r["trigger"][:100] for r in r0 if r["retire_reason"] == name})[:3]
        for e in ex:
            out(f"    [{name}] {e!r}")
    # absence de substance, tous verdicts
    ne = Counter(r["verdict"] for r in A if NO_EVIDENCE.search(r["trigger"].strip()))
    out(f"trigger « sans substance » (regex) par verdict : {dict(ne)} ; conviction mediane par verdict : "
        + str({v: statistics.median(r['conviction'] for r in A if r['verdict'] == v and
                                    NO_EVIDENCE.search(r['trigger'].strip()))
               for v in ne}))
    out(f"trigger vide : {sum(1 for r in A if not r['trigger'].strip())}")
    dorm = Counter()
    for it in thesis_items(last[2]):
        dorm[(bool(it.get("dormant")), it["verdict"], "0" if it["conviction"] == 0 else ">0")] += 1
    out("dernier snapshot, (dormante, verdict, conviction) : " + str(dict(sorted(dorm.items()))))
    nd_nr = sum(n for (dm, v, c), n in dorm.items() if dm and v != "retire")
    nd_nr0 = sum(n for (dm, v, c), n in dorm.items() if dm and v != "retire" and c == "0")
    out(f"  dormantes non-retire : {nd_nr}, dont conviction 0 : {nd_nr0} (la dormance garde la derniere valeur)")
    # verdicts rejetes (thv des briefs)
    thv = [b["thv"] for b in briefs.values() if isinstance(b.get("thv"), dict)]
    out(f"briefs distincts : {len(briefs)} ; avec thv : {len(thv)} ; verdicts emis "
        f"{sum(x.get('emitted', 0) for x in thv)}, ecrits {sum(x.get('applied', 0) for x in thv)}, "
        f"rejetes (id inconnu) {sum(x.get('unresolved', 0) for x in thv)} -> un verdict rejete n'ecrit rien "
        f"(pas de ligne a 0)")
    # briefs : conviction citee pour un RETIRE vs valeur ecrite au registre (meme ts)
    by_ts = defaultdict(list)
    for r in A:
        by_ts[r["ts"]].append(r)
    struct, prose, zero_txt = [], [], []
    for (bts, tier, mode), b in sorted(briefs.items()):
        m = re.search(r"##\s*RECONCILIATION\s*\n(.*?)(?=\n##\s|\Z)", b.get("brief") or "", re.S)
        if not m:
            continue
        for ln in re.split(r"\n(?=\s*(?:[*\-]|\d+\.)\s)", m.group(1)):
            if not re.search(r"\bRETIR", ln):
                continue
            ids = [i.upper() for i in re.findall(r"th_\d{8}_\d{4}_([a-z0-9]+)", ln)]
            led = [r for r in by_ts.get(bts, []) if r["entity"] in ids and r["verdict"] == "retire"]
            ms = re.search(r"\bRETIRE\b\s*\|\s*conviction:\s*(\d(?:\.\d+)?)", ln)
            mc = re.search(r"conviction[^0-9\n]{0,15}(\d(?:\.\d+)?)", ln, re.I)
            if ms and led:
                struct.append((bts, float(ms.group(1)), sorted({r['key'] for r in led}),
                               sorted({r['conviction'] for r in led})))
            elif mc and led and float(mc.group(1)) > 0:
                prose.append((bts, float(mc.group(1)), sorted({r['key'] for r in led}),
                              sorted({r['conviction'] for r in led})))
            elif mc and led and float(mc.group(1)) == 0:
                zero_txt.append(bts)
    out(f"briefs, ligne structurée « RETIRE | conviction: x » avec x>0 et retire au registre au meme ts : "
        f"{len(set(struct))} cas")
    for a, b, c, d in sorted(set((a, b, tuple(c), tuple(d)) for a, b, c, d in struct)):
        out(f"    brief {a}  conviction emise={b}  -> registre {c} conviction={d}")
    out(f"briefs, prose citant une conviction > 0 pour un RETIRE (peut etre la conviction ANTERIEURE) : "
        f"{len({(a, tuple(c)) for a, b, c, d in prose})} cas ; "
        f"prose citant « conviction 0.0 » : {len(set(zero_txt))} briefs, premier {min(zero_txt) if zero_txt else None}")

    # ---------------------------------------------------------------- Q3
    out("\n" + "=" * 78)
    out("Q3. SAUTS DE CONVICTION")
    out("=" * 78)
    ser_j = {k: [(r["ts"], r["conviction"]) for r in rs] for k, rs in by_key.items()}
    ser_h = defaultdict(list)
    for h in H:
        ser_h[h["key"]].append((h["day"], h["conviction"]))
    # journal « changements d'etat » : on fusionne les restatements consecutifs identiques
    ser_c = {}
    for k, rs in by_key.items():
        pts = []
        for r in rs:
            if not pts or (pts[-1][1], pts[-1][2]) != (r["verdict"], r["conviction"]):
                pts.append((r["ts"], r["verdict"], r["conviction"]))
        ser_c[k] = [(a, c) for a, _, c in pts]
    ser_cur = {k: [(i, c) for i, c in enumerate(cs)] for k, cs in cur_hist}
    views = [("history du dernier snapshot (12 pts max/cle)", ser_cur),
             ("union history (point = dernier du jour)", dict(ser_h)),
             ("journal (toutes evaluations)", ser_j),
             ("journal (restatements fusionnes)", ser_c)]
    res_views = {}
    for name, ser in views:
        s, trips, dead = jump_stats(ser)
        tot8, in8 = jumps_in_roundtrips(ser)
        res_views[name] = (s, trips, dead)
        out(f"\n[{name}] {s['series']} series, {s['points']} points, {s['transitions']} transitions "
            f"(dont valeur changee : {s['changed']})")
        out(f"  |d|>=0.5 : {s['ge05']} ({pct(s['ge05'], s['transitions'])}) dont impliquant 0 : {s['ge05_zero']}")
        out(f"  |d|>=0.8 : {s['ge08']} ({pct(s['ge08'], s['transitions'])}) dont impliquant 0 : {s['ge08_zero']} ; "
            f"dans un aller-retour x->0->≈x : {in8}/{tot8}")
        out(f"  plages de zeros : interieures {s['zero_runs_interior']} -> retour a ≈x (±{TOL}) "
            f"{s['roundtrip']} ({pct(s['roundtrip'], s['zero_runs_interior'])}), a x exactement "
            f"{s['roundtrip_exact']} ; sans retour (zero jusqu'au dernier point) {s['zero_runs_dead_end']} ; "
            f"serie qui commence a 0 : {s['zero_runs_start']}")
        out(f"  dont x>=0.8 avant le zero : {s['interior_from_ge08']} -> retour ≈x : {s['roundtrip_from_ge08']}")
    s, trips, dead = res_views["union history (point = dernier du jour)"]
    s10, trips10, _ = jump_stats(dict(ser_h), tol=0.10)
    out(f"\nsensibilite tolerance ±0.10 (union history) : retour ≈x {s10['roundtrip']}/{s10['zero_runs_interior']}"
        f" ; cles avec >=1 aller-retour (±{TOL}) : {len({t[0] for t in trips if t[7]})}")
    out("exemples d'allers-retours (union history) :")
    for t in sorted(trips, key=lambda t: t[3])[:8]:
        out(f"  {t[0]:22s} {t[1]} {t[2]:.2f} -> 0 [{t[3]}..{t[4]}] -> {t[5]} {t[6]:.2f} "
            f"{'≈' if t[7] else '≠'}{' =' if t[8] else ''}")
    out("sans retour (union history) : " + "; ".join(f"{k} {c:.2f}@{d}->0@{e}" for k, d, c, e in dead))
    # resurrections
    n_res = 0
    keys_res = set()
    keys_ever = set()
    for k, rs in by_key.items():
        for a, b in zip(rs, rs[1:]):
            if a["verdict"] == "retire" and b["verdict"] != "retire":
                n_res += 1
                keys_res.add(k)
        if any(r["verdict"] == "retire" for r in rs):
            keys_ever.add(k)
    out(f"\nretire n'est pas terminal : transitions retire -> confirm/revise = {n_res} "
        f"sur {len(keys_res)} cles (cles ayant eu un retire : {len(keys_ever)} / {len(by_key)})")
    ex = [(r["key"], r["prev_ts"], r["ts"], r["verdict"], r["conviction"]) for rs in by_key.values()
          for r, p in zip(rs[1:], rs) if p["verdict"] == "retire" and r["verdict"] != "retire"]
    for e in ex[:6]:
        out(f"    {e}")

    # ---------------------------------------------------------------- Q4
    out("\n" + "=" * 78)
    out("Q4. DISTRIBUTION DES CONVICTIONS NON NULLES")
    out("=" * 78)
    nz = [r for r in A if r["conviction"] > 0]
    vals = [r["conviction"] for r in nz]
    claims = {}
    for r in nz:
        claims.setdefault((r["key"], r["trigger"]), r["conviction"])
    out(f"evaluations non nulles : {len(nz)} / {len(A)} ; claims distincts (key, trigger) : {len(claims)} ; "
        f"valeurs distinctes : {len(set(vals))} ; min {min(vals)} max {max(vals)}")
    q = statistics.quantiles(vals, n=4)
    out(f"quartiles {q} ; moyenne {statistics.mean(vals):.3f} ; ecart-type {statistics.pstdev(vals):.3f}")
    edges = [(0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    out("tranche        evaluations      claims (key,trigger)   history-union")
    hv = [h["conviction"] for h in H if h["conviction"] > 0]
    for lo, hi in edges:
        a = sum(1 for v in vals if lo <= v < hi)
        b = sum(1 for v in claims.values() if lo <= v < hi)
        c = sum(1 for v in hv if lo <= v < hi)
        out(f"[{lo:.1f};{min(hi, 1.0):.1f}{']' if hi > 1 else '['}   {a:5d} ({pct(a, len(vals)):>7s})   "
            f"{b:5d} ({pct(b, len(claims)):>7s})   {c:5d} ({pct(c, len(hv)):>7s})")
    out(f"history-union non nulle : n={len(hv)}")
    out(f"valeurs modales : {[(v, n, pct(n, len(vals))) for v, n in Counter(vals).most_common(8)]}")
    out(">=0.85 : " + f"{sum(1 for v in vals if v >= 0.85)} ({pct(sum(1 for v in vals if v >= 0.85), len(vals))}) ; "
        f">=0.9 : {sum(1 for v in vals if v >= 0.9)} ({pct(sum(1 for v in vals if v >= 0.9), len(vals))})")
    for v in ("confirm", "revise"):
        vv = [r["conviction"] for r in nz if r["verdict"] == v]
        out(f"  {v:8s} n={len(vv)} mediane {statistics.median(vv)} IQR "
            f"{[round(x, 3) for x in statistics.quantiles(vv, n=4)]} min {min(vv)} max {max(vv)}")
    out("claims par tranche large (calibration : >=30 resolus/tranche) : "
        + str({f'{lo}-{min(hi,1.0)}': sum(1 for v in claims.values() if lo <= v < hi)
               for lo, hi in [(0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 1.01)]}))
    gm = statistics.mean(vals)
    ss_tot = sum((v - gm) ** 2 for v in vals)
    ss_b = sum(len(g) * (statistics.mean(g) - gm) ** 2 for g in
               [[r["conviction"] for r in nz if r["verdict"] == vv] for vv in ("confirm", "revise", "retire")] if g)
    out(f"part de variance de la conviction non nulle expliquee par le verdict (eta²) : {ss_b / ss_tot:.2f}")
    # stabilite : meme valeur d'une eval a la suivante
    same = tot = 0
    for rs in by_key.values():
        for a, b in zip(rs, rs[1:]):
            if a["conviction"] > 0 and b["conviction"] > 0:
                tot += 1
                same += a["conviction"] == b["conviction"]
    out(f"deux evals consecutives non nulles d'une meme cle a conviction identique : {same}/{tot} ({pct(same, tot)})")

    # ---------------------------------------------------------------- Q5
    out("\n" + "=" * 78)
    out("Q5. CONDITION `kill` : OBSERVABLE ?")
    out("=" * 78)
    cur = [r for r in A if r["last_seen"] == iso(t_last)]
    out(f"[dernier snapshot, n={len(cur)} items] " + str(dict(Counter(kill_class(r['kill']) for r in cur))))
    out(f"[evaluations distinctes, kill = derniere valeur vue, n={len(A)}] "
        + str(dict(Counter(r['kill_class'] for r in A))))
    out(f"[evaluations distinctes, kill = valeur au 1er snapshot, n={len(A)}] "
        + str(dict(Counter(kill_class(r['kill_first']) for r in A))))
    kt = sorted({k for r in A for k in r["kill_all"] if k.strip()})
    out(f"[textes kill non vides distincts, n={len(kt)}] " + str(dict(Counter(kill_class(k) for k in kt))))
    cut = [k for k in kt if len(k) in (180, 200) and not k.endswith(".")]
    out(f"  longueur max {max(len(k) for k in kt)} ; coupes a la limite (180/200 car., sans point final) : {len(cut)} ; "
        f"commencent par « Monitor » : {sum(1 for k in kt if k.lower().startswith('monitor'))}")
    neg = re.compile(r"\b(kill|invalidat|refute|falsif|disprove|below|fall|drop|declin|decreas)", re.I)
    out(f"  mentionnent un sens de refutation/baisse (kill, below, fall, drop, declin, refute...) : "
        f"{sum(1 for k in kt if neg.search(k))}")
    for k in kt:
        if kill_class(k) == "mesurable":
            out(f"  MESURABLE (nombre+horizon) : {k!r}")
    chg = sum(1 for r in A if len(r["kill_all"]) > 1)
    out(f"kill reecrit apres coup pour un meme (key, ts) : {chg}/{len(A)} ({pct(chg, len(A))}) ; "
        f"max {max(len(r['kill_all']) for r in A)} valeurs differentes ; "
        f"vide au 1er snapshot puis rempli : "
        f"{sum(1 for r in A if not r['kill_first'].strip() and r['kill'].strip())}")
    for r in A:
        if r["kill_class"] == "mesurable":
            out(f"  evaluation a kill nombre+horizon : {r['key']} {r['ts']} {r['verdict']} {r['conviction']}")
    # briefs : « Kill condition »
    ok = [b for b in briefs.values() if b.get("status") == "ok" and not b.get("silent")]
    kc = []
    for b in ok:
        for m in re.finditer(r"Kill conditions?\s*:\s*(.+)", b.get("brief") or ""):
            kc.append((b["ts"], m.group(1)))
    nb = len({a for a, _ in kc})
    nnum = sum(1 for _, t in kc if NUM_RE.search(t))
    nboth = sum(1 for _, t in kc if NUM_RE.search(t) and HOR_RE.search(t))
    out(f"briefs ok non silencieux : {len(ok)} ; lignes « Kill condition » : {len(kc)} dans {nb} briefs ; "
        f"avec un nombre/seuil : {nnum} ({pct(nnum, len(kc))}) ; nombre + horizon : {nboth} "
        f"-> texte libre rattache a un brief, jamais a une these (aucun id de these)")

    # ---------------------------------------------------------------- Q6
    out("\n" + "=" * 78)
    out("Q6. BRIER CALCULABLE ?")
    out("=" * 78)
    meas = sum(1 for r in A if r["kill_class"] == "mesurable")
    out(f"evaluations avec resolution structuree (metric/op/threshold/deadline) : 0 / {len(A)}")
    out(f"evaluations avec kill nombre+horizon (texte libre) : {meas} / {len(A)}")
    out(f"evaluations dont la conviction est une probabilite d'evenement datee : 0 / {len(A)}")
    out("-> issues resolues utilisables pour un Brier : 0")


if __name__ == "__main__":
    sys.exit(main())
