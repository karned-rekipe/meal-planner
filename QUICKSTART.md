# Quickstart — meal-planner

## Rôle

`meal-planner` est le service métier du volet planification de `rekipe`.

## Ports locaux

- API REST : `8010`
- MCP HTTP / SSE : `8011`
- Probes : `9010`

## Installation

```bash
cd /Users/killian/Karned/projets/Rekipe/meal-planner
uv sync --group dev
```

## Lancement

```bash
MODE=api uv run python main.py
MODE=mcp_http uv run python main.py
MODE=all uv run python main.py
```

## Configuration

- Keycloak : [config/adapters/input/keycloak.yaml](/Users/killian/Karned/projets/Rekipe/meal-planner/config/adapters/input/keycloak.yaml)
- MongoDB : [config/adapters/output/mongodb.yaml](/Users/killian/Karned/projets/Rekipe/meal-planner/config/adapters/output/mongodb.yaml)
- Tenant : [config/adapters/input/tenant.yaml](/Users/killian/Karned/projets/Rekipe/meal-planner/config/adapters/input/tenant.yaml)

Par défaut, le repository reste en `memory` dans `config/adapters/adapters.yaml`. La configuration MongoDB multi-tenant est préparée pour la suite.
