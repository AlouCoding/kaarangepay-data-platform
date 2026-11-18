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

---

# Phase 3b — Détection de fraude en temps réel (Spark Structured Streaming)

## 9. Le motif de fraude à attraper

Le générateur simule une **prise de contrôle de compte** (le motif de PaySim) :

```
 victime ──TRANSFER (presque tout son solde)──▶ mule ──CASH_OUT (presque tout, 2 à 30 min après)──▶ agent
```

| Idée de règle | Est-ce qu'elle attrape la mule ? |
|---|---|
| « Trop de transactions en 10 min » (vélocité) | ❌ La mule ne fait que **2** opérations |
| « Montant très élevé » | ❌ Une victime peut avoir un petit solde |
| **« L'argent entre puis ressort en cash presque en entier, très vite »** | ✅ C'est **le lien** entre les deux opérations |

Ce lien est une **jointure entre deux événements du même flux**, sur le compte de la mule, limitée dans le temps.

## 10. Le workflow du job `lake fraud`

```
 Kafka: kaarangepay.public.transactions
          │  (JSON Debezium)
          ▼
 décoder l'enveloppe ──────────── même code que le silver (cdc.parse_changes)
          │
          ▼
 event time = occurred_at + watermark 45 min
          │
          ├──▶ entrées : TRANSFER complétés ≥ 5 000 XOF    (compte = destinataire)
          ├──▶ sorties : CASH_OUT complétés                  (compte = émetteur)
          ▼
 JOINTURE stream-stream : même compte
                          ET cash-out entre 0 et 30 min après le transfert
                          ET cash-out entre 90 % et 100 % du montant reçu
          │
          ├──▶ topic Kafka kaarangepay.fraud.alerts   (pour réagir en temps réel)
          └──▶ table Delta gold/fraud_alerts           (pour analyser et mesurer)
               chaque sortie a son checkpoint sur S3
```

## 11. Event time, watermark, état : les 3 notions clés du streaming

| Notion | Définition simple | Chez nous |
|---|---|---|
| **Event time** | L'heure où l'événement s'est **produit** (pas l'heure où on le reçoit) | `occurred_at` (ADR 0004 de la phase 1 !) |
| **État** | Ce que Spark doit garder en mémoire entre deux micro-batchs | Les TRANSFER récents qui attendent peut-être leur CASH_OUT |
| **Watermark** | « Je n'attends plus d'événements plus vieux que *max vu − délai* » | 45 min : au-delà, Spark **oublie** les vieux transferts → mémoire bornée |

**Sans watermark**, Spark garderait *tous* les transferts depuis le début pour toujours : la mémoire exploserait.

**Pourquoi 45 min et pas 10 ?** En backfill, le générateur envoie le cash-out de la mule juste après le transfert,
mais **daté jusqu'à 30 min plus tard**. Le « max vu » avance donc d'un coup de 30 min. Avec un watermark de 10 min,
les transactions normales suivantes (datées normalement) seraient jugées « en retard » et **jetées**.
45 min = 30 min d'avance possible + une marge.

## 12. Checkpoint et garanties

Le **checkpoint** (`s3a://gold/_checkpoints/...`) contient : les offsets Kafka lus, l'état de la jointure, les
micro-batchs validés. Après un arrêt, `lake fraud` reprend **exactement** là où il s'était arrêté.

| Sortie | Garantie | Pourquoi |
|---|---|---|
| Table Delta | **Exactly once** | Delta note quels micro-batchs sont déjà écrits |
| Topic Kafka | **At least once** | Un doublon est possible après un plantage → `alert_id` = id du cash-out, déterministe, pour dédoublonner |

C'est la même logique que le bronze-writer : on accepte la relivraison, et on rend son effet inoffensif.

## 13. Mesurer au lieu d'affirmer : précision et rappel

Le générateur écrit la **vérité terrain** dans `data/labels/fraud_labels.jsonl` (l'API ne la voit jamais).
`lake fraud-eval` compare les alertes à ces labels :

| Mesure | Question | Formule |
|---|---|---|
| **Précision** | Quand on alerte, a-t-on raison ? | vraies fraudes signalées / transactions signalées |
| **Rappel** | Attrape-t-on les fraudes ? | vraies fraudes signalées / toutes les fraudes |
| Cas détectés | Combien de prises de contrôle repérées ? | transferts frauduleux signalés / transferts frauduleux |

Compromis classique : baisser le seuil (par ex. 80 % au lieu de 90 %) augmente le rappel mais baisse la précision.
**Faux positifs attendus :** un client honnête qui reçoit de l'argent d'un proche et le retire aussitôt en entier
ressemble à une mule. Ce n'est pas un bug, c'est la limite d'une règle sans contexte → phase 5 (ML).

## 14. Lancer la phase 3b

```bat
set COMPOSE_PROFILES=cdc,bronze,lake
docker compose build lake
docker compose run --rm lake fraud
docker compose run --rm lake fraud-eval
```

- `lake fraud` lit **tout** le topic depuis le début, écrit les alertes, puis s'arrête (`availableNow`).
- `lake fraud --continuous` reste allumé (un micro-batch toutes les 10 s) : lance le trafic live à côté et regarde
  les alertes arriver dans Kafka UI (http://localhost:8090, topic `kaarangepay.fraud.alerts`).
- Relancer `lake fraud` ne re-traite rien : le checkpoint sait où il en est.
- Interface Spark pendant un job : `docker compose run --rm --service-ports lake fraud --continuous` puis http://localhost:4040
  (onglet *Structured Streaming* : débit, latence de chaque micro-batch).

## 15. Ce que tu dois savoir expliquer

| Question | Réponse courte |
|---|---|
| Batch vs streaming ? | Même code (fonction pure sur DataFrame). En streaming, Spark garde un état entre micro-batchs. |
| Pourquoi un watermark ? | Pour borner l'état : sans lui, la mémoire grandit à l'infini. |
| Event time vs processing time ? | On raisonne sur l'heure réelle de l'opération ; le retard du réseau ne doit pas changer le résultat. |
| Exactly once ? | Oui vers Delta ; at-least-once vers Kafka, rendu inoffensif par une clé déterministe. |
| Ta règle est-elle bonne ? | Je ne l'affirme pas, je la mesure : précision et rappel contre des labels. |
