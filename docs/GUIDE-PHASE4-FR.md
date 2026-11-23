# Guide phase 4 — dbt, l'entrepôt et l'appli (Vue métier + Console fraude)

> Objectif : que des **utilisateurs finaux** voient le travail des phases 1 à 3.
> Direction → tableau de bord. Analyste fraude → console d'alertes en direct.

## 1. Le chemin complet de la donnée

```
 PostgreSQL ─CDC─▶ Kafka ─▶ bronze ─Spark─▶ silver (Delta) ─┐
                     │                                      │  analytics pipeline
                     └─Spark streaming─▶ gold/fraud_alerts ─┤   1. load  (delta-rs → DuckDB raw.*)
                                              │             │   2. dbt build (modèles + tests)
                                              │             │   3. publier (renommage atomique)
                                              │             ▼
                                              │      kaarangepay.duckdb ──▶ Vue métier
                                              └──────── lu en direct ─────▶ Console fraude ─▶ décisions (SQLite)
```

## 2. Pourquoi dbt ?

dbt = **du SQL versionné, testé et documenté**. Chaque fichier `.sql` est un modèle ; dbt calcule l'ordre
(`ref()`), crée les tables et lance les tests. C'est l'outil standard du métier d'*analytics engineer*.

| Couche dbt | Fichiers | Rôle |
|---|---|---|
| `raw` | (chargé par Python) | Copie exacte du silver et des alertes |
| `staging` (vues) | `stg_*.sql` | Renommer, typer, dédoublonner. Une source = un modèle |
| `marts` (tables) | `fct_*`, `dim_*`, `agg_*` | Ce que les utilisateurs lisent |

## 3. Le modèle en étoile (ton cours de BI !)

```
                 dim_date (jour, jour de semaine, période de paie)
                     │
 dim_account ── fct_transactions ── dim_account
 (émetteur)     1 ligne = 1 tentative    (destinataire)
                (montant, frais, statut, heure, alerte fraude ?)
```

- **Fait** = un événement mesurable (une transaction), au grain le plus fin, en **event time**.
- **Dimensions** = le contexte pour filtrer et regrouper (qui, quand).
- **Agrégats** (`agg_daily_kpis`…) = pré-calculés pour que l'appli soit instantanée.

## 4. Les tests : la règle « on ne publie pas de faux chiffres »

| Type | Exemple | Ce qu'il attrape |
|---|---|---|
| `unique`, `not_null` | `fct_transactions.transaction_id` | Doublons, lignes cassées |
| `accepted_values` | type ∈ {FLOAT_TOPUP, CASH_IN, CASH_OUT, TRANSFER, PAYMENT} | Une nouvelle valeur inconnue |
| `relationships` | chaque transaction pointe vers un compte et un jour connus | Données orphelines |
| **Singuliers** (`dbt/tests/`) | débits = crédits ; somme des soldes = 0 ; un échec ne rapporte rien ; total journalier = total des faits | Un événement perdu entre le lac et l'entrepôt |

Les invariants du ledger sont maintenant vérifiés **trois fois** : dans PostgreSQL (API), dans Spark (silver),
et dans dbt (entrepôt).

## 5. Publication atomique

```
 build dans kaarangepay.building.duckdb ──▶ dbt build OK ? ──oui──▶ renommer en kaarangepay.duckdb
                                                        └──non──▶ ne rien publier (l'appli garde l'ancien)
```
Le test `test_a_broken_ledger_is_not_published` retire une écriture : dbt échoue, **l'ancien entrepôt reste en ligne**.

**Bug trouvé par un test :** dbt lancé *dans le même processus* gardait DuckDB ouvert ; les dernières écritures
étaient encore dans le fichier `.wal`. Après le renommage, les tables `marts` avaient disparu. Correction : dbt
tourne dans **un processus séparé** (DuckDB vide son WAL à la fermeture), et le pipeline refuse de publier si
un `.wal` traîne encore.

## 6. L'appli

| Page | Pour qui | Source | Rafraîchissement |
|---|---|---|---|
| **Vue métier** | Direction | Entrepôt dbt | À chaque `analytics pipeline` |
| **Console fraude** | Analyste | Table gold Delta, lue **en direct** | Toutes les 10 s |

Dans la console : sélectionne une alerte → chemin de l'argent **victime → mule → agent**, montants, délai →
**« Confirmer la fraude »** ou **« Faux positif »**. Les décisions vont dans un fichier SQLite séparé, jamais écrasé
par le pipeline : en phase 5, ce seront des **étiquettes** pour entraîner un modèle.

## 7. Lancer la phase 4

```bat
set COMPOSE_PROFILES=cdc,bronze,lake,analytics
docker compose up -d seaweedfs
docker compose build analytics dashboard
docker compose run --rm analytics pipeline
docker compose up -d dashboard
```
Puis ouvre **http://localhost:8501**.

Démo temps réel (optionnel) : trafic live + `docker compose run --rm lake fraud --continuous` dans une autre
fenêtre → les nouvelles alertes apparaissent dans la console sans recharger la page.

## 8. Ce que tu dois savoir expliquer

| Question | Réponse courte |
|---|---|
| Pourquoi dbt plutôt que des scripts SQL ? | Ordre automatique, tests intégrés au build, documentation, revue de code possible. |
| Pourquoi DuckDB ? | Base analytique dans un fichier, sans serveur ; parfait pour ce volume. En entreprise : même modèle dbt sur Snowflake/BigQuery. |
| Fait vs dimension ? | Fait = l'événement mesuré (transaction). Dimension = le contexte (compte, jour). |
| Que se passe-t-il si un test échoue ? | Rien n'est publié : les utilisateurs gardent les derniers chiffres justes. |
| Pourquoi la console lit-elle Delta et pas l'entrepôt ? | Pour être en temps réel : l'entrepôt n'est reconstruit qu'à la demande. |
| Où sont gardées les décisions des analystes ? | À part (SQLite), parce qu'elles ne doivent jamais être écrasées par un rebuild. |
