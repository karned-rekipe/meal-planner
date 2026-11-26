# Configuration de la planification

Ce document décrit le contrat de configuration utilisé par `gwel` et par les agents MCP. La configuration active repose exclusivement sur des personnes nommées.

## Invariant métier

- Au moins une personne doit exister avant d'utiliser les écrans de planification.
- Une règle de présence contient de un à vingt `member_ids` connus.
- `headcount` est une donnée dérivée de `member_ids`; il n'est pas accepté dans une écriture de planning.
- Le mode public est toujours `schedule_mode: "members"`.
- Les anciennes données `headcount` peuvent être lues en interne pour compatibilité, mais elles ne pilotent plus le planning actif et doivent être reconfigurées avec des personnes.

## Contrat REST

Toutes les routes sont tenant-aware et utilisent les conventions de `docs/http-conventions.md`. Les mises à jour et suppressions existantes utilisent `If-Match` avec la version exposée par `ETag`.

| Besoin | Méthode et route |
|---|---|
| Lister les personnes | `GET /v1/household-members/` |
| Créer une personne | `POST /v1/household-members/` |
| Modifier une personne | `PUT /v1/household-members/{uuid}` |
| Modifier son avatar | `PUT /v1/household-members/{uuid}/avatar` |
| Supprimer une personne | `DELETE /v1/household-members/{uuid}` |
| Lire zone et présences | `GET /v1/household-schedule/` |
| Définir seulement la zone | `PUT /v1/household-schedule/school-zone` |
| Remplacer les règles de présence | `PUT /v1/household-schedule/` |
| Lister les périodes de vacances | `GET /v1/school-vacation-periods/` |
| Ajouter une période manuelle | `POST /v1/school-vacation-periods/` |
| Synchroniser le calendrier officiel | `POST /v1/school-vacation-periods/sync-official` |
| Modifier une période | `PUT /v1/school-vacation-periods/{uuid}` |
| Supprimer une période | `DELETE /v1/school-vacation-periods/{uuid}` |

Exemple minimal de règle de présence :

```json
{
  "school_zone": "A",
  "schedule_mode": "members",
  "rules": [
    {
      "week_parity": "even",
      "school_period_type": "regular",
      "day_of_week": "monday",
      "meal_slot_code": "dinner",
      "member_ids": ["019b1111-2222-7333-8444-555555555555"]
    }
  ]
}
```

Les valeurs exactes des enums sont publiées dans l'OpenAPI du service. Une mise à jour contenant une personne inconnue est rejetée.

## Outils MCP

L'agent dispose des outils suivants pour couvrir le même périmètre :

- `list_household_members`
- `create_household_member`
- `update_household_member`
- `update_household_member_avatar`
- `delete_household_member`
- `get_household_schedule`
- `set_household_school_zone`
- `update_household_schedule`
- `list_school_vacation_periods`
- `create_school_vacation_period`
- `sync_official_school_vacation_periods`
- `update_school_vacation_period`
- `delete_school_vacation_period`
- `get_tenant_preferences`
- `update_tenant_preferences`

Les outils d'écriture exigent une authentification. Les mises à jour et suppressions prennent `expected_version` pour le verrouillage optimiste.

## Calendrier scolaire officiel

La source par défaut est le jeu de données `fr-en-calendrier-scolaire` du portail open data de l'Éducation nationale. Deux variables permettent de surcharger la source sans stocker de secret :

- `SCHOOL_VACATION_CALENDAR_API_URL`
- `SCHOOL_VACATION_CALENDAR_DATASET`

La synchronisation utilise la zone configurée si le payload n'en fournit pas. Par défaut, elle couvre du 1er janvier de l'année courante au 31 décembre de l'année courante + 2.

Pour la plage demandée et la zone choisie, elle :

1. récupère et déduplique les périodes officielles par nom et dates ;
2. crée ou met à jour les périodes officielles ;
3. retire uniquement les périodes officielles devenues obsolètes ;
4. préserve toujours les périodes manuelles ;
5. refuse toute réconciliation si la source renvoie une liste vide.

Une indisponibilité ou une réponse invalide de la source est exposée en REST avec un statut `502` et remonte comme erreur MCP, sans fuite du payload brut du fournisseur.
