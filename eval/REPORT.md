# Évaluation de Hermes — état au 19 octobre 2026

## Verdict

**Sur tout ce qui est mesurable avec les données publiques, les veilles de Hermes n'apportent aucune information détectable.**

- **Taux de réussite.** Elles tiennent 23,9 % du temps (IC 95 % : 19,9–28,4 %, n = 389).
- **Test de permutation.** On redistribue au hasard les mouvements réellement observés entre les mêmes prédicats. On obtient 23,3 % contre 22,4 % pour Hermes (n = 107, p = 0,69).
- **Sens du mouvement.** Il est juste dans 51,4 % des cas, contre 51,3 % attendus si l'agent tirait le sens au hasard.

Le test décisif n'a pas encore pu être refait : le seul benchmark sur les mêmes prédicats donnait 49,1 % à la règle sans LLM contre 25,0 % au cerveau L4. Il date du 4 août et demande DefiLlama, bloqué dans cet environnement. Le script `regrade.py` est prêt.

## Ce qui a été mesuré, et d'où

| Source | Contenu | Limite |
|---|---|---|
| A. Compteurs publiés (`watch_stats.csv`) | totaux tenues / cassées par source, à chacun des 1 033 snapshots depuis le 2026-08-03 | pas de détail par veille |
| B. Registre reconstruit (`watches.jsonl`) | 579 veilles, 292 tranchées avec seuil, valeur à l'échéance, verdict | 75 % des verdicts publiés seulement (voir Couverture) |
| C. Veilles `delta_pct` avec mouvement observé | 107 veilles (94 L4, 23 L3), échéances du 2026-07-22 au 2026-10-13 | rien pour les seuils absolus sans base, ni pour L3 en majorité |

Rien n'est recalculé par un LLM. Les deux scripts sont déterministes : graine fixe, sortie identique à chaque exécution.

## Résultats

### 1. Couverture et cohérence interne
- **Verdicts retrouvés :** 292 des 389 verdicts publiés (75,1 %). 139 veilles échues ne sont jamais apparues tranchées dans un snapshot : le tableau de bord ne montre qu'environ 109 veilles sur ~600, en priorité les ouvertes.
- **Biais de sélection possible :** en septembre–octobre, la part retrouvée tombe sous 50 % (57 sur 122, puis 24 sur 54). Pour les taux globaux, les compteurs publiés (source A) font foi.
- **Cohérence des verdicts :** le correcteur de Hermes est cohérent avec ses propres mesures. Sur 289 veilles vérifiables, chaque verdict correspond à la valeur enregistrée. Aucune veille n'a changé de verdict après avoir été tranchée.
- **Moment de décision :** toutes les décisions tombent le jour de l'échéance, à 00 h 45 UTC. Le prédicat est donc évalué à l'échéance, pas « à un moment avant ».

### 2. Taux de réussite publiés (registre complet)

| | Cumul | IC 95 % | n |
|---|---|---|---|
| Toutes | 23,9 % | 19,9–28,4 | 389 |
| L3 (brief scripté) | 27,1 % | 20,9–34,3 | 166 |
| L4 (agent autonome) | 20,0 % | 15,1–26,0 | 205 |
| NEWS | 37,5 % | 18,5–61,4 | 16 |

Par mois de décision : 14,1 % avant le 3 août (n = 71), puis 22,5 % en août (n = 142), 31,1 % en septembre (n = 122) et 24,1 % en octobre jusqu'au 19 (n = 54). Il y a une amélioration depuis juillet, mais les intervalles de septembre et d'octobre se chevauchent largement.

### 3. Détail sur le registre reconstruit (n = 292)
- **Par métrique :**
  - fees : 26,6 % (n = 199) ;
  - **tvl : 7,5 % (5 sur 67, IC 3,2–16,3)** ;
  - open interest : 40,0 % (n = 15) ;
  - stablecoin_flow : 0 sur 8.
- **L3 face à L4 :** +6,0 points en faveur de L3 (IC bootstrap −4,1 à +16,4). La différence n'est pas significative.
- **Par horizon :** 20,4 % à 10 jours ou moins (n = 235), 28,1 % au-delà (n = 57).
- **Par sens :** 20,4 % pour les baisses annoncées (n = 152), 23,6 % pour les hausses (n = 140).
- **Prédicats mal formés :** 18 seuils ne sont pas à l'échelle de la métrique (ex. `Lido tvl <= 15.5`, `Sanctum tvl <= -0.15`, `Aave V3 fees <= 1.5`). Ce sont des pourcentages ou des milliards écrits comme des dollars. Les retirer ne change presque rien : 22,6 % au lieu de 21,9 %.

### 4. Test du hasard sur la même population (n = 107)
Pour chaque veille en variation (%), on calcule la part des mouvements réellement observés sur les autres veilles (même métrique, même classe d'horizon) qui l'auraient satisfaite.

| | Taux |
|---|---|
| Hermes | 22,4 % (IC 15,6–31,2) |
| Attendu si le choix de l'entité ne porte aucune information | 23,3 % |
| Écart | −0,9 point, p = 0,69 (2 000 permutations) |

- **Sens annoncé :** 22 % d'appels haussiers, alors que 48 % des mouvements réalisés étaient haussiers. Le sens est juste 54 fois sur 105 (51,4 %), pour 51,3 % attendu (p = 0,53).
- **Puissance du test :** avec n = 107, il détecterait 8 fois sur 10 un avantage d'environ 10 points (test unilatéral à 5 %). Un avantage plus petit reste possible, mais il n'est pas visible.

## Ce qui n'a pas pu être fait

1. **Re-notation indépendante et taux de base par entité** (`regrade.py`). La politique réseau de l'environnement refuse `api.llama.fi`. Le script est écrit et testé sur une série synthétique (bons verdicts, aucune donnée postérieure à l'émission). Il n'a pas été exécuté sur les vraies données : aucun chiffre DefiLlama n'apparaît dans ce rapport.
2. **Reproduction du benchmark du 4 août** (règle 49,1 %). Même blocage. La fenêtre exacte et l'univers de la règle sont des hypothèses, documentées dans `regrade.py`.
3. **Veilles à seuil absolu.** 172 veilles tranchées n'ont pas de valeur de base enregistrée : impossible d'évaluer la difficulté du seuil sans série externe.
4. **Code de l'agent.** Le repo `hermes-defi` n'a pas été lu.

## Recommandations, par ordre d'impact

1. **Ouvrir `api.llama.fi`**, lancer `python3 eval/regrade.py` et exiger d'abord qu'il retrouve environ 49 % pour la règle sur la fenêtre du benchmark. Sinon, corriger l'hypothèse avant de lire le reste.
2. **Faire tourner l'évaluation sur le VPS**, à partir de `watch_ledger.jsonl` complet plutôt que des snapshots. Cela élimine le trou de 25 % et le biais de sélection.
3. **Enregistrer la valeur de base à l'émission pour toutes les veilles**, pas seulement pour les `delta_pct`. Sans elle, la difficulté d'un seuil absolu est invisible.
4. **Suspendre ou refondre les veilles TVL** (5 sur 67) tant qu'un test ne montre pas qu'elles battent leur taux de base.
5. **Rejeter à l'émission les seuils hors d'échelle** : un contrôle déterministe suffit, `analyze.malformed()` en donne un.
6. **Ajouter une probabilité p à chaque veille.** Le score de Brier comparé au taux de base deviendrait alors la métrique principale, à la place du simple taux de réussite.

## Reproduire

```bash
python3 eval/reconstruct.py   # relit l'historique git -> eval/data/watches.jsonl, watch_stats.csv
python3 eval/analyze.py       # -> eval/data/analysis.json + résumé
python3 eval/regrade.py       # nécessite api.llama.fi -> eval/data/regrade_summary.json
```
