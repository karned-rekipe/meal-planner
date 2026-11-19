# Quickstart

## Prérequis

- Python 3.13
- [uv](https://docs.astral.sh/uv/) installé (`pip install uv` ou `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- MongoDB local via la stack commune `/Users/killian/Karned/repos/Kommon/dev/docker-compose.yml`

```bash
docker compose -f /Users/killian/Karned/repos/Kommon/dev/docker-compose.yml up -d
```

## Installation

### 1. Créer ton projet depuis le template

Ce dépôt est un **template GitHub**. Ne le clone pas directement.

Sur GitHub, clique sur **"Use this template"** → **"Create a new repository"**, choisis ton nom de projet, puis clone ton nouveau dépôt :

```bash
git clone <url-de-ton-repo> mon-projet
cd mon-projet
```

### 2. Installer les dépendances

```bash
uv sync
```

`uv sync` crée automatiquement le `.venv` et installe toutes les dépendances déclarées dans `pyproject.toml`, dont `arclith` depuis PyPI.

## Lancer l'application

### API (FastAPI)

```bash
uv run python main_api.py
```

### MCP — SSE

```bash
uv run python main_mcp_sse.py
```

## Secrets et Vault

Par défaut les secrets (URI MongoDB, clé API LM…) sont lus depuis `secrets.yaml` (fichier local gitignored).
Pour utiliser HashiCorp Vault en dev ou en production : → [Configurer Vault et les secrets](vault.md)

Configuration locale attendue pour la persistance du planning :

```yaml
adapters:
  mongodb:
    uri: mongodb://localhost:5971
```

`meal-planner` écrit dans `recipe.meal_plan_entry` :

- `document_type: meal_plan` pour le plan perpétuel courant ;
- `document_type: legacy_entry` pour l'historique importé depuis recipe et projeté en lecture.

Les repas disponibles dans le calendrier sont globaux au tenant et stockés dans `tenant_preferences.meal_slots`. Par défaut : `Déjeuner` (`lunch`) et `Dîner` (`dinner`).

