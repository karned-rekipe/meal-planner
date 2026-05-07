# SKILLS.md — `meal-planner/`

Recettes paramétriques pour les tâches récurrentes sur le backend `meal-planner`.
Pour les tâches cross-repo, voir `../SKILLS.md` à la racine du workspace.

Format : chaque skill est identifiée `SK-MP##` (MP = Meal Planner).

---

## SK-MP01 — Ajouter une nouvelle entité métier

**Contexte :** ajouter une entité de domaine avec persistence et exposition REST + MCP.

### Référence canonique

`docs/new-entity.md` est le guide pas-à-pas complet. Mêmes étapes que `recipe/` (voir `../recipe/SKILLS.md` SK-R01 pour la version commentée).

### Checklist synthétique

1. **Domain** : `domain/models/<entity>.py` + `domain/ports/output/<entity>_repository.py`.
2. **Application** : `application/services/<entity>_service.py` + use cases si nécessaire.
3. **Adapters output (les trois)** : `memory`, `mongodb`, `duckdb`.
4. **Adapters input** : schéma + router REST + tools MCP.
5. **Infrastructure** : container DI + ré-export.
6. **Tests** : domain + memory repo, coverage ≥ 80 %.
7. **Documentation** : entrée `journal/` à la racine du workspace.

### Validation

```bash
make precommit
make coverage
MODE=all uv run python main.py
```

---

## SK-MP02 — Ajouter un tool MCP

**Contexte :** exposer une nouvelle opération via MCP (consommée par `meal-planner-agent` ou autre).

### Étapes

1. `adapters/input/fastmcp/tools/<entity>_tools.py` — méthode `@mcp.tool()` claire et orientée agent (la docstring est lue par le LLM consommateur).
2. Vérifier l'enregistrement dans `adapters/input/fastmcp/register.py` → `register_tools()`.
3. Schémas pydantic pour les structures complexes (`adapters/input/schemas/`).
4. Test : `tests/units/adapters/input/fastmcp/test_<entity>_tools.py`.

### Validation

```bash
make test-unit
MODE=mcp_http uv run python main.py
```

Le tool doit apparaître dans la liste exposée par MCP. Voir `../recipe/SKILLS.md` SK-R07 pour la commande d'inspection (transposable à ce repo).

---

## SK-MP03 — Étendre le contrat avec `recipe/`

**Contexte :** lire un nouveau champ d'une recette ou un nouveau filtre depuis `recipe/`.

### Étapes

1. Vérifier que le champ ou le filtre est bien exposé côté `recipe/`. Si non : intervenir d'abord dans `recipe/` (cf. `../recipe/SKILLS.md`).

2. Étendre le port `domain/ports/output/recipe_client.py` :
    - ajouter le champ au snapshot ou la signature de la méthode ;
    - garder le port indépendant de l'implémentation HTTP.

3. Mettre à jour l'implémentation HTTP `adapters/output/http/`.

4. Mettre à jour le **stub mémoire** utilisé en tests (s'il existe) pour refléter le nouveau contrat.

5. Si le champ est figé dans un snapshot : mettre à jour `domain/models/recipe_snapshot.py` et la **migration** des plans existants (cf. SK-MP05).

### Validation

```bash
make test-unit
# Démarrer recipe puis meal-planner :
./start_services.sh up recipe
./start_services.sh up meal-planner
# Lire un plan existant ; le nouveau champ doit apparaître dans la réponse REST.
```

---

## SK-MP04 — Ajouter un slot ou un type de slot

**Contexte :** introduire un nouveau type de repas (ex. `snack`, `breakfast`, `brunch`) en plus des `lunch` / `dinner` existants.

### Étapes

1. `domain/models/enums.py` — ajouter le code dans l'énumération des slots.

2. Vérifier toutes les occurrences :

   ```bash
   grep -rn "lunch\|dinner" domain/ application/ adapters/ tests/ | grep -v __pycache__
   ```

3. Mettre à jour les schémas REST et MCP (`adapters/input/schemas/`) si l'énumération est exposée.

4. Mettre à jour `meal-planner-agent` côté contraintes (si l'agent restreint son scoring à des slots connus).

5. Migration : décider si les plans existants doivent être recalculés ou laissés tels quels.

### Validation

```bash
make test-unit
# Créer un plan avec le nouveau slot via l'API.
```

---

## SK-MP05 — Migrer un schéma `MealPlan` ou `*Snapshot`

**Contexte :** changer la forme d'un document persisté en MongoDB (ex. ajout d'un champ obligatoire).

### Étapes

1. Préférer une **migration progressive** : champ optionnel d'abord, puis remplissage rétroactif, puis champ obligatoire.

2. Script de migration ad hoc dans `scripts/` (s'il existe) ou via une commande Python isolée. Toujours **idempotent**.

3. Snapshot Mongo avant migration (cf. `../SKILLS.md` SK-W03).

4. Tests : ajouter un cas qui charge un document de l'**ancien format** et vérifie que le repository renvoie une entité valide après migration en mémoire.

### Validation

```bash
make test-unit
make coverage
# Restaurer un dump pré-migration sur une base de test.
# Lancer le service avec les nouvelles entités, vérifier les lectures.
```

### Notes

- Toute migration mérite **deux entrées journal** : une pour la décision et l'introduction du champ optionnel, une pour le passage à obligatoire.

---

## SK-MP06 — Diagnostiquer un plan vide ou incomplet

**Contexte :** un plan retourne moins de slots ou des slots vides — comprendre pourquoi.

### Étapes

1. Vérifier que `recipe/` répond et qu'il y a des recettes éligibles :

   ```bash
   curl -fsS "http://127.0.0.1:8301/recipe/v1/?meal_planner_eligible=true" | jq 'length'
   ```

2. Vérifier les `TenantPreferences` du tenant concerné — exclusions, allergies, contraintes peuvent vider le pool.

3. Logs `meal-planner` : repérer les warnings `recipe_client` (timeout, 4xx, contenu vide).

4. Si l'agent est utilisé pour la suggestion : voir `../meal-planner-agent/SKILLS.md`.

### Validation

```bash
./start_services.sh logs meal-planner | tail -50
```

---

## SK-MP07 — Restaurer ou exporter la base MongoDB locale

**Contexte :** repartir d'un état connu, partager un dump.

Voir `../SKILLS.md` SK-W03. La base par défaut de ce repo est `meal-planner` (cf. `config/adapters/output/mongodb.yaml`).
