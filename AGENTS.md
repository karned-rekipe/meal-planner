# AGENTS.md — `meal-planner/`

Document d'entrée pour tout agent de codage qui intervient sur ce repo.
Lecture obligatoire avant toute modification.

Pour le contexte global du projet et les conventions transverses, voir `../AGENTS.md` à la racine du workspace.

---

## 1. Rôle

`meal-planner/` est le **backend du domaine planification de repas** de Rekipe. Il détient :

- les plans de repas (`MealPlan`) et leurs slots (`MealSlot`) ;
- les éléments planifiés dans un slot (`MealItem`) ;
- les snapshots de recettes et d'ingrédients (`RecipeSnapshot`, `IngredientSnapshot`) — figés au moment de la planification, pour que la modification ultérieure d'une recette ne casse pas un plan déjà établi ;
- les préférences par tenant (`TenantPreferences`) — exclusions, contraintes, headcount par défaut.

Le service **consomme** `recipe/` via HTTP (adapter `adapters/output/http`) pour récupérer les recettes éligibles (filtre `meal_planner_eligible=true`). Il **expose** ses entités via REST + MCP au frontend `gwel` et à l'agent `meal-planner-agent`.

## 2. Stack et ports

| Élément | Valeur |
|---|---|
| Langage | Python 3.13 |
| Gestionnaire deps | `uv` (lock : `uv.lock`) |
| Framework de base | `arclith` |
| Web | FastAPI |
| MCP | FastMCP |
| Stockage prod | MongoDB (port `5971` en local) |
| Stockages alternatifs | `memory` (tests), `duckdb` (alt) |
| Auth | Keycloak (port `5990` en local) |
| REST | `8010` |
| MCP HTTP | `8011` |
| Probes (health/ready/metrics) | `9010` |
| Source de données externe | `recipe/` (REST `8301` via pont) |

**Ne jamais changer ces ports** sans mettre à jour `start_services.sh`, `gwel/vite.config.ts`, et `meal-planner-agent/config.yaml`.

## 3. Architecture locale

Architecture hexagonale (mêmes principes que `recipe/`) :

```
domain/
  models/                              # MealPlan, MealSlot, MealItem, snapshots, TenantPreferences, enums
  exceptions.py                        # Exceptions métier
  ports/
    output/
      meal_plan_repository.py          # Persistence des plans
      tenant_preferences_repository.py # Persistence des préférences
      recipe_client.py                 # Lecture recettes depuis recipe/

application/                           # Services + use cases

adapters/
  input/
    fastapi/                           # Routers REST par entité
    fastmcp/                           # Tools MCP par entité
    schemas/                           # Schémas pydantic in/out
  output/
    mongodb/repositories/              # Adapter prod
    memory/repositories/               # Adapter tests
    duckdb/repositories/               # Adapter alt
    http/                              # Client HTTP vers recipe/

infrastructure/
  containers/                          # DI par entité
  container.py                         # Façade DI
  logging_setup.py

config/                                # Configuration YAML
tests/units/                           # Tests par couche
main.py                                # Entry point unique (MODE env var)
```

### Modes de lancement

`main.py` lit la variable d'environnement `MODE` :

| MODE | Transports actifs |
|---|---|
| `api` | FastAPI REST + probes |
| `mcp_http` | MCP streamable-HTTP + probes |
| `mcp_sse` | MCP SSE + probes |
| `all` | API + MCP HTTP + probes (dev / POC) |

## 4. Règles de développement

### Règles transverses (rappel — voir `../AGENTS.md` §4)

- Architecture hexagonale stricte. `domain/` ne dépend que de `arclith` + `pydantic`.
- MongoDB est le seul adaptateur de production.
- Les recettes ne sont **jamais dupliquées en base**. Le meal-planner lit `recipe/` via HTTP au moment du choix, puis fige un **snapshot léger** (UUID + champs nécessaires) dans le `MealItem`.
- Filtrer les recettes côté `recipe/` avec `meal_planner_eligible=true` pour exclure les drafts.

### Règles spécifiques à ce repo

- **Snapshots vs. références** : un `MealItem` contient un `RecipeSnapshot` figé (titre, UUID, ingrédients essentiels au moment T). Cela protège le plan d'une mutation ultérieure de la recette. Ne pas remplacer par une simple référence UUID.
- **Tout nouveau tool MCP** doit être enregistré dans `adapters/input/fastmcp/register.py`.
- **Toute nouvelle route REST** doit être enregistrée dans `adapters/input/fastapi/register.py`.
- **Couverture de tests ≥ 80 %** : `make coverage`.
- **Pre-commit** : `make precommit` avant tout push.
- **Aucun secret** dans `config/*.yaml` versionné. Vault uniquement (cf. `docs/vault.md`).

### Qualité

```bash
make lint typecheck security complexity
make test test-unit test-e2e
make coverage
make quality      # CI complète
make precommit    # pre-push rapide
```

## 5. Commandes utiles

### Lancement local manuel

```bash
uv sync --group dev
MODE=all uv run python main.py
```

(Préférer `./start_services.sh up meal-planner` depuis la racine pour rester cohérent.)

### Vérifier la connexion à `recipe/`

```bash
curl -fsS http://127.0.0.1:8301/recipe/v1/?meal_planner_eligible=true | jq '.[0:3]'
```

Le meal-planner doit recevoir une réponse `200` avec des recettes non-draft.

## 6. Fichiers à lire en premier

1. `main.py` — entry point, modes.
2. `domain/models/meal_plan.py` — modèle métier central.
3. `domain/models/meal_slot.py` + `meal_item.py` — composition d'un plan.
4. `domain/models/recipe_snapshot.py` — comprendre la stratégie snapshot.
5. `domain/ports/output/recipe_client.py` — contrat avec `recipe/`.
6. `adapters/output/http/` — implémentation du client HTTP vers `recipe/`.
7. `application/services/` — services métier.
8. `adapters/input/fastapi/register.py` + `adapters/input/fastmcp/register.py` — câblages.
9. `infrastructure/container.py` — DI globale.
10. `config/` — configuration.

Pour ajouter une fonctionnalité, lire en plus :

- `docs/new-entity.md`
- `docs/http-conventions.md`
- `docs/implementation.md`
- `docs/vault.md`

## 7. Règle du journal — rappel

Toute modification non triviale doit être consignée dans `journal/YYYY-MM-DD-slug.md` à la **racine du workspace**. Voir `../AGENTS.md` §6 et `../journal/README.md`.

Cas spécifiques à ce repo qui exigent une entrée journal :

- changement de schéma `MealPlan` / `MealSlot` / `MealItem` / `*Snapshot` ;
- changement du contrat avec `recipe/` (champs lus, filtres) ;
- ajout / retrait d'un adapter ;
- changement de port (REST, MCP, probes).

## 8. Hors scope

- Le **choix automatique** de recettes (suggestion, scoring) vit dans `meal-planner-agent/`. Ce repo n'embarque pas de logique LLM.
- La **liste de courses** dérive d'un plan, mais elle est gérée dans `shopping/`. Pas de génération de courses ici.
- Les **recettes elles-mêmes** restent la propriété de `recipe/`. Ce repo en lit des projections.
