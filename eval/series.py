#!/usr/bin/env python3
"""Extrait les observations chiffrees de data.json (historique git) vers un CSV.

Lancer depuis la racine du repo :  python3 eval/series.py
Ecrit :  eval/data/series.csv  et  eval/data/series_coverage.json
Bibliotheque standard uniquement.

Colonnes CSV : as_of,entity,metric,value,block,field
- as_of : `as_of` du bloc (UTC, ISO 8601 a la seconde). Exception : les points
  dates des historiques (rwa.v.history, robinhood.v.history) prennent leur propre
  date `d` (minuit UTC), sinon chaque point d'un meme snapshot partagerait le
  meme horodatage et serait ecrase a la deduplication.
- value : valeur exacte (Decimal), converties en USD quand l'unite est Md$ ou M$.
- Deduplication sur (as_of, entity, metric, block, field). En cas de valeurs
  differentes pour une meme cle, la version du snapshot le plus recent est gardee.
"""

import csv
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = "data.json"
SINCE = datetime(2026, 8, 3, tzinfo=timezone.utc)
BLOCKS = ["movers", "curator", "macro", "prices", "battery", "robinhood", "rwa"]
OUT_DIR = os.path.join(REPO, "eval", "data")
CSV_PATH = os.path.join(OUT_DIR, "series.csv")
COV_PATH = os.path.join(OUT_DIR, "series_coverage.json")
CSV_HEADER = ["as_of", "entity", "metric", "value", "block", "field"]

# macro.sectors : `tvl` est toujours en Md$, la colonne `yard` dit ce qu'il mesure.
SECTOR_METRIC = {"TVL": "tvl_usd", "VOLUME": "volume_usd", "OI/VOL": "oi_or_vol_usd"}
# battery.candidates[].size : texte arrondi, par ex. "$742M" ou "$9.9B".
SIZE_RE = re.compile(r"^\$(\d+(?:\.\d+)?)([MB])$")


# --- acces git -------------------------------------------------------------

def git_out(*args):
    return subprocess.run(["git", "-C", REPO, *args], check=True, capture_output=True).stdout


def list_commits():
    """Commits touchant data.json depuis SINCE, du plus ancien au plus recent."""
    commits = []
    for line in git_out("log", "--reverse", "--format=%H %cI", "--", DATA_FILE).decode().splitlines():
        sha, cdate = line.split(" ", 1)
        when = datetime.fromisoformat(cdate)
        if when >= SINCE:
            commits.append((sha, when))
    commits.sort(key=lambda c: c[1])  # tri stable : garde l'ordre git a egalite
    return commits


def read_blobs(shas):
    """Lit data.json de chaque commit avec un seul `git cat-file --batch`.

    Produit (sha, octets) ou (sha, None) si le fichier manque dans ce commit.
    """
    proc = subprocess.Popen(["git", "-C", REPO, "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha in shas:
            proc.stdin.write(f"{sha}:{DATA_FILE}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if not header:
                raise RuntimeError("git cat-file --batch : fin de flux inattendue")
            if len(header) < 3:  # "<sha>:data.json missing"
                yield sha, None
                continue
            size = int(header[2])
            data = proc.stdout.read(size)
            if len(data) != size:
                raise RuntimeError(f"{sha}: lecture tronquee")
            proc.stdout.read(1)  # saut de ligne terminal
            yield sha, data
    finally:
        proc.stdin.close()
        proc.wait()


# --- normalisation ---------------------------------------------------------

def num(x):
    """Nombre fini (int ou float, hors bool), sinon None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return x


def lst(x):
    return x if isinstance(x, list) else []


def iso_utc(s):
    """Horodatage ISO (Z, +00:00 ou microsecondes) -> '%Y-%m-%dT%H:%M:%SZ' en UTC."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_iso(d):
    """'YYYY-MM-DD' -> minuit UTC au format ISO."""
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unix_iso(ts):
    """Secondes epoch -> ISO UTC."""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- collecte --------------------------------------------------------------

class Collector:
    def __init__(self):
        self.values = {}   # (as_of, entity, metric, block, field) -> valeur texte
        self.stats = Counter()
        self.conflicts = []

    def add(self, as_of, entity, metric, raw, exp, block, field):
        """Ajoute une observation valant raw * 10**exp, en notation fixe exacte."""
        x = num(raw)
        if x is None:
            self.stats["valeur_absente_ou_non_numerique"] += 1
            return
        if not isinstance(entity, str) or not entity:
            self.stats["entite_absente"] += 1
            return
        value = format(Decimal(repr(x)).scaleb(exp), "f")
        key = (as_of, entity, metric, block, field)
        old = self.values.get(key)
        if old is None:
            self.values[key] = value
        elif old == value:
            self.stats["doublon_identique"] += 1
        else:
            self.stats["conflit_meme_cle"] += 1
            if len(self.conflicts) < 10:
                self.conflicts.append((key, old, value))
            self.values[key] = value  # snapshot le plus recent


def _movers_rows(col, as_of, block, base, items):
    for p in lst(items):
        e = p.get("name")
        col.add(as_of, e, "tvl_usd", p.get("tvl_usd"), 0, block, f"{base}.tvl_usd")
        col.add(as_of, e, "tvl_chg_1d_pct", p.get("chg_1d"), 0, block, f"{base}.chg_1d")
        col.add(as_of, e, "tvl_chg_7d_pct", p.get("chg_7d"), 0, block, f"{base}.chg_7d")


def ex_movers(col, as_of, v):
    for side in ("gainers", "losers"):
        _movers_rows(col, as_of, "movers", f"movers.v.{side}[]", v.get(side))


def ex_curator(col, as_of, v):
    _movers_rows(col, as_of, "curator", "curator.v.movers[]", v.get("movers"))
    for w in lst(v.get("watchlist")):
        sym = w.get("sym")
        col.add(as_of, sym, "price_usd", w.get("price"), 0, "curator", "curator.v.watchlist[].price")
        col.add(as_of, sym, "price_chg_pct", w.get("change_pct"), 0, "curator",
                "curator.v.watchlist[].change_pct (periode non etiquetee)")


def ex_macro(col, as_of, v):
    B = "macro"
    for s in lst(v.get("sectors")):
        yard = s.get("yard")
        metric = SECTOR_METRIC.get(yard)
        if metric is None:
            col.stats[f"secteur_yard_inconnu:{yard}"] += 1
            continue
        col.add(as_of, s.get("name"), metric, s.get("tvl"), 9, B,
                f"macro.v.sectors[].tvl (yard={yard}, Md$ x1e9)")
    for f in lst(v.get("fee_yield")):
        col.add(as_of, f.get("name"), "fee_yield_pct", f.get("fy"), 0, B, "macro.v.fee_yield[].fy")
        col.add(as_of, f.get("name"), "tvl_usd", f.get("tvl_b"), 9, B, "macro.v.fee_yield[].tvl_b (Md$ x1e9)")
    for f in lst(v.get("flows")):
        col.add(as_of, f.get("chain"), "tvl_flow_7d_usd", f.get("d7"), 6, B, "macro.v.flows[].d7 (M$ x1e6)")
    for c in lst(v.get("chains")):
        col.add(as_of, c.get("n"), "tvl_usd", c.get("tvl_b"), 9, B, "macro.v.chains[].tvl_b (Md$ x1e9)")
    for cat in lst(v.get("by_category")):
        cname = cat.get("cat")
        for p in lst(cat.get("p")):
            col.add(as_of, p.get("n"), "tvl_usd", p.get("tvl_b"), 9, B,
                    f"macro.v.by_category[{cname}].p[].tvl_b (Md$ x1e9)")
            col.add(as_of, p.get("n"), "tvl_chg_7d_pct", p.get("chg"), 0, B,
                    f"macro.v.by_category[{cname}].p[].chg (7j, deduit)")
    agg = v.get("agg") if isinstance(v.get("agg"), dict) else {}
    col.add(as_of, "DeFi TVL", "tvl_usd", agg.get("defi_tvl_b"), 9, B, "macro.v.agg.defi_tvl_b (Md$ x1e9)")
    col.add(as_of, "Stables mcap", "stable_mcap_usd", agg.get("stable_mcap_b"), 9, B,
            "macro.v.agg.stable_mcap_b (Md$ x1e9)")
    col.add(as_of, "Stables mcap", "stable_mcap_chg_7d_pct", agg.get("stable_d7_pct"), 0, B,
            "macro.v.agg.stable_d7_pct (7j)")
    col.add(as_of, "DEX vol 24 h", "volume_usd", agg.get("dex_vol_24h_b"), 9, B,
            "macro.v.agg.dex_vol_24h_b (Md$ x1e9)")


def ex_prices(col, as_of, v):
    for it in lst(v.get("items")):
        sym = it.get("sym")
        col.add(as_of, sym, "price_usd", it.get("p"), 0, "prices", "prices.v.items[].p")
        col.add(as_of, sym, "price_chg_pct", it.get("d"), 0, "prices",
                "prices.v.items[].d (periode non etiquetee)")


def ex_battery(col, as_of, v):
    for c in lst(v.get("candidates")):
        e = c.get("entity")
        size = c.get("size")
        m = SIZE_RE.match(size) if isinstance(size, str) else None
        # `size` est la base du premier declencheur : une TVL ("tvl_7d ... sur $742M")
        # ou des frais sur 7 j ("fees_7d ... sur $2M/7j"), jamais les deux
        trig = str((lst(c.get("triggers")) or [""])[0])
        metric = "tvl_usd" if trig.startswith("tvl") else "fees_7d_usd" if trig.startswith("fees_7d") else None
        if m and metric:
            exp = 6 if m.group(2) == "M" else 9
            col.add(as_of, e, metric, float(m.group(1)), exp, "battery",
                    "battery.v.candidates[].size (texte arrondi, base du 1er declencheur)")
        elif m:
            col.stats["battery_size_base_inconnue"] += 1
        elif size is not None:
            col.stats["battery_size_non_parse"] += 1
        col.add(as_of, e, "tvl_chg_7d_pct", c.get("tvl_chg_7d"), 0, "battery",
                "battery.v.candidates[].tvl_chg_7d")


def ex_robinhood(col, as_of, v):
    E = "Robinhood Chain"
    col.add(as_of, E, "tvl_usd", v.get("tvl_m"), 6, "robinhood", "robinhood.v.tvl_m (M$ x1e6)")
    for h in lst(v.get("history")):
        try:
            t = unix_iso(h["d"])
        except (KeyError, TypeError, ValueError, OSError):
            col.stats["date_historique_invalide"] += 1
            continue
        col.add(t, E, "tvl_usd", h.get("v"), 6, "robinhood",
                "robinhood.v.history[].v (M$ x1e6; horodatage = d)")


def ex_rwa(col, as_of, v):
    E = "RWA (secteur)"
    col.add(as_of, E, "tvl_usd", v.get("tvl_b"), 9, "rwa", "rwa.v.tvl_b (Md$ x1e9)")
    col.add(as_of, E, "tvl_chg_1d_pct", v.get("chg_1d"), 0, "rwa", "rwa.v.chg_1d")
    col.add(as_of, E, "tvl_chg_7d_pct", v.get("chg_7d"), 0, "rwa", "rwa.v.chg_7d")
    for t in lst(v.get("top")):
        col.add(as_of, t.get("name"), "tvl_usd", t.get("tvl_b"), 9, "rwa", "rwa.v.top[].tvl_b (Md$ x1e9)")
    for side in ("up", "down"):
        for t in lst(v.get(side)):
            col.add(as_of, t.get("name"), "tvl_usd", t.get("tvl_m"), 6, "rwa",
                    f"rwa.v.{side}[].tvl_m (M$ x1e6)")
            col.add(as_of, t.get("name"), "tvl_chg_7d_pct", t.get("chg"), 0, "rwa",
                    f"rwa.v.{side}[].chg (7j, selon synthese)")
    for h in lst(v.get("history")):
        try:
            t = day_iso(h["d"])
        except (KeyError, TypeError, ValueError):
            col.stats["date_historique_invalide"] += 1
            continue
        col.add(t, E, "tvl_usd", h.get("v"), 9, "rwa", "rwa.v.history[].v (Md$ x1e9; horodatage = d)")


EXTRACTORS = {
    "movers": ex_movers,
    "curator": ex_curator,
    "macro": ex_macro,
    "prices": ex_prices,
    "battery": ex_battery,
    "robinhood": ex_robinhood,
    "rwa": ex_rwa,
}


def extract_snapshot(col, blocks):
    for name in BLOCKS:
        blk = blocks.get(name)
        if not isinstance(blk, dict) or not isinstance(blk.get("v"), dict):
            continue
        col.stats[f"bloc_present:{name}"] += 1
        if blk.get("err"):
            col.stats[f"bloc_en_erreur:{name}"] += 1
            continue
        try:
            as_of = iso_utc(blk["as_of"])
        except (KeyError, AttributeError, TypeError, ValueError):
            col.stats[f"as_of_invalide:{name}"] += 1
            continue
        EXTRACTORS[name](col, as_of, blk["v"])


# --- sorties ---------------------------------------------------------------

def write_outputs(values):
    rows = sorted(values.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2], kv[0][3], kv[0][4]))
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for (as_of, entity, metric, block, field), value in rows:
            w.writerow([as_of, entity, metric, value, block, field])

    cov = defaultdict(lambda: {"as_ofs": set(), "rows": 0, "blocks": Counter()})
    for (as_of, entity, metric, block, _field) in values:
        c = cov[(entity, metric)]
        c["as_ofs"].add(as_of)
        c["rows"] += 1
        c["blocks"][block] += 1
    entries = []
    for (entity, metric), c in cov.items():
        ts = sorted(c["as_ofs"])
        entries.append({
            "entity": entity,
            "metric": metric,
            "n": len(ts),
            "n_rows": c["rows"],
            "first_as_of": ts[0],
            "last_as_of": ts[-1],
            "blocks": dict(c["blocks"].most_common()),
        })
    entries.sort(key=lambda e: (-e["n"], e["entity"], e["metric"]))
    with open(COV_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return len(rows), len(entries)


def main():
    commits = list_commits()
    col = Collector()
    skipped = []
    shas = [sha for sha, _ in commits]
    for (sha, when), (_, data) in zip(commits, read_blobs(shas)):
        if data is None:
            col.stats["snapshot_fichier_absent"] += 1
            continue
        try:
            doc = json.loads(data)
        except ValueError:
            col.stats["snapshot_json_invalide"] += 1
            continue
        blocks = doc.get("blocks") if isinstance(doc, dict) else None
        if not isinstance(blocks, dict):
            col.stats["snapshot_format_sans_blocks"] += 1
            skipped.append(f"{sha[:8]} {when.isoformat()}")
            continue
        col.stats["snapshot_lu"] += 1
        extract_snapshot(col, blocks)

    n_rows, n_pairs = write_outputs(col.values)
    print(f"commits >= {SINCE.date()} : {len(commits)}")
    print(f"lignes CSV : {n_rows} ; couples (entity, metric) : {n_pairs}")
    print("stats :", dict(sorted(col.stats.items())))
    if skipped:
        print("snapshots ignores (format sans blocks) :", len(skipped))
        for s in skipped:
            print("   ", s)
    for key, old, new in col.conflicts:
        print("conflit (version la plus recente gardee) :", key, old, "->", new)


if __name__ == "__main__":
    main()
