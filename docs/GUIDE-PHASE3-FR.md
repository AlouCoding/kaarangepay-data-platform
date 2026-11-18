# Guide phase 3 — Spark et la couche silver (Delta Lake)

> Phase 3a : transformer le bronze (événements bruts) en tables propres, typées, à jour,
> et **re-prouver sur le lakehouse les invariants du ledger**.

## 1. Le problème que résout la couche silver

Dans le bronze, le compte d'Awa n'est pas *une* ligne mais *une histoire* :

| offset | op | balance (dans le JSON) |
|---|---|---|
| 12 | `c` (création) | 0 |
| 57 | `u` (mise à jour) | 10 000 |
| 203 | `u` | 7 000 |

Un analyste veut juste : **Awa = 7 000 XOF**. Le silver garde **la dernière version de chaque clé**,
avec de vraies colonnes typées (dates, entiers) au lieu d'un texte JSON.

```
bronze (événements, JSON brut)            silver (état actuel, colonnes typées)
┌────────┬────┬──────────────────┐        ┌──────┬─────────┬──────────┐
│ offset │ op │ payload (texte)  │  ───▶  │ id   │ balance │ _cdc_op  │
│ 12     │ c  │ {...balance:0}   │        │ awa  │ 7000    │ u        │
│ 57     │ u  │ {...10000}       │        └──────┴─────────┴──────────┘
│ 203    │ u  │ {...7000}        │
└────────┴────┴──────────────────┘
```

## 2. Le workflow du job `lake silver`

```
             pour chaque table (accounts, transactions, ledger_entries)
┌──────────────┐   ┌────────────────┐   ┌────────────────┐   ┌──────────┐   ┌──────────────┐
│ lire bronze  │──▶│ parse_changes  │──▶│ current_state  │──▶│ typer    │──▶│ écrire Delta │
│ (Parquet S3) │   │ JSON → colonnes│   │ dernière       │   │ dates,   │   │ overwrite    │
│              │   │ rejets comptés │   │ version / clé  │   │ montants │   │ atomique     │
└──────────────┘   └────────────────┘   └────────────────┘   └──────────┘   └──────────────┘
                                                                                  │
                                         ┌────────────────────────────────────────┘
                                         ▼
                       contrôles qualité (10) → exit 0 si tout OK, 1 sinon
```

| Étape | Fichier | Ce qui se passe |
|---|---|---|
| Lire | `cli.py` → `read_bronze` | Spark lit tous les `.parquet` sous `s3a://bronze/<table>/` |
| Décoder | `cdc.py` → `parse_changes` | `from_json` sur `payload` ; `after` pour c/r/u, `before` pour `d` ; JSON illisible → *rejected* |
| Dédoublonner | `cdc.py` → `current_state` | Fenêtre `row_number()` par clé, triée par offset décroissant ; on garde le rang 1 sauf si c'est un `d` |
| Typer | `silver.py` | Texte ISO-8601 → `TIMESTAMP` UTC ; `signed_amount` (+crédit / −débit) ; `occurred_date` |
| Écrire | `cli.py` → `write_silver` | `format("delta").mode("overwrite")`, partitionné par `occurred_date` |
| Contrôler | `quality.py` | Les 3 invariants du ledger + clés uniques, non-nuls, références, échecs sans écriture |

## 3. Pourquoi trier par **offset Kafka** et pas par date ?

Debezium utilise la **clé primaire comme clé Kafka**. Kafka envoie une même clé toujours dans
**la même partition** (hachage), et une partition garde l'ordre d'écriture. Donc toutes les versions
d'un compte sont dans une seule partition, dans l'ordre des commits PostgreSQL : l'offset le plus
grand est la version la plus récente. Une horloge, elle, peut avoir des égalités ou des décalages.

Le test `test_order_is_the_kafka_offset_not_the_arrival_in_the_file` le vérifie : même en mélangeant
les lignes, le résultat ne change pas.

## 4. Delta Lake en 30 secondes

Une table Delta = **des fichiers Parquet + un journal `_delta_log/`** (un fichier JSON par version).

```
s3a://silver/transactions/
├── _delta_log/
│   ├── 00000000000000000000.json   ← version 0 : "ajoute ces 12 fichiers"
│   └── 00000000000000000001.json   ← version 1 (2e run) : "retire les 12, ajoute ces 12"
├── occurred_date=2026-11-01/part-....parquet
└── occurred_date=2026-11-02/...
```

| Avantage | Ce que ça veut dire ici |
|---|---|
| **Atomique** | Un lecteur voit l'ancienne version ou la nouvelle, jamais un mélange à moitié écrit |
| **Schéma contrôlé** | Écrire une colonne du mauvais type échoue au lieu de corrompre la table |
| **Time travel** | `versionAsOf 0` relit le silver d'hier |

Pourquoi pas Iceberg ? Très bien aussi, mais il faut un **catalogue** (service en plus). Delta n'a besoin
que du stockage : moins de RAM, moins de pièces.

## 5. Les 10 contrôles qualité

| # | Contrôle | Attendu | Ce qu'il attrape |
|---|---|---|---|
| 1-3 | Clé primaire unique (3 tables) | 0 doublon | Un dédoublonnage raté |
| 4-5 | Colonnes obligatoires non nulles | 0 | Un JSON mal décodé |
| 6 | **Somme de tous les soldes = 0** | 0 | Une mise à jour de compte perdue |
| 7 | **Chaque transaction équilibrée** (débits = crédits) | 0 | Une écriture perdue |
| 8 | **Solde = somme des écritures**, par compte | 0 | Un écart entre `accounts` et `ledger_entries` |
| 9 | Les écritures pointent vers des lignes connues | 0 | Une transaction ou un compte manquant |
| 10 | Les transactions FAILED ne déplacent pas d'argent | 0 | Un bug métier |

Les contrôles 6, 7, 8 sont **exactement** ceux de `/api/v1/ledger/integrity` dans PostgreSQL.
S'ils passent aussi sur le lakehouse, la chaîne complète
**PostgreSQL → Debezium → Kafka → bronze → silver** n'a rien perdu.

⚠️ Lance-le **trafic arrêté** et bronze rattrapé (30 s après le dernier message) : sinon un solde
peut arriver avant ses écritures, et le contrôle 8 échoue *temporairement*.

## 6. Lancer la phase 3a

```bat
docker pull apache/spark:3.5.8-python3
set COMPOSE_PROFILES=cdc,bronze,lake
docker compose build lake
docker compose run --rm lake silver
```

Le premier build télécharge ~300 Mo de bibliothèques Java (Delta, S3A, SDK AWS) **une seule fois**.

Résultat attendu (forme) :
```
table               events      rows  rejected
accounts             2,172  (nb de comptes)   0
transactions       133,845   133,845         0
ledger_entries     309,668   309,668         0

[  OK] accounts: primary key unique ...
[  OK] ledger: sum of all balances = 0 ...
...
```

Voir les tables : http://localhost:8888/buckets/silver/ (dossier `_delta_log` dans chaque table).
Pendant le job, l'interface Spark est sur http://localhost:4040.

## 7. Tests (13, sans Docker)

| Test | Ce qu'il prouve |
|---|---|
| `test_latest_update_wins` | La dernière mise à jour gagne |
| `test_delete_removes_the_key...` | Un `d` supprime la clé ; la *tombstone* n'est pas une erreur |
| `test_key_recreated_after_delete_is_back` | Supprimé puis recréé → présent |
| `test_order_is_the_kafka_offset...` | L'ordre des fichiers ne compte pas |
| `test_undecodable_payloads_are_rejected...` | Le JSON cassé est compté, pas caché |
| `test_a_lost_event_is_caught` | **Retirer une seule écriture fait échouer 2 contrôles** |
| `test_a_stale_balance_is_caught` | Une mise à jour de solde perdue est détectée |
| `test_end_to_end_run_is_idempotent` | Deux runs = même résultat, aucun doublon |

## 8. Ce que tu dois savoir expliquer

| Question | Réponse courte |
|---|---|
| Bronze vs silver ? | Bronze = tout l'historique brut, jamais modifié. Silver = état actuel, propre, typé, recalculable depuis le bronze. |
| Pourquoi recalculer tout à chaque fois ? | Idempotent et simple ; à 450k événements c'est quelques secondes. `MERGE` incrémental quand le volume l'exige. |
| Comment gères-tu les deletes CDC ? | L'événement `d` porte l'image `before` ; si c'est la dernière version de la clé, la ligne disparaît du silver. |
| Comment sais-tu que ton silver est juste ? | Je re-vérifie les invariants comptables du système source sur le lakehouse. |
