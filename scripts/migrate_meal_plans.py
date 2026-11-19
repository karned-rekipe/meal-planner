from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

from domain.models.enums import MealItemType, MealPlanStatus, SlotCode
from domain.models.meal_item import MealItem
from domain.models.meal_plan import MealPlan
from domain.models.recipe_snapshot import RecipeSnapshot

_LUNCH_CODES = {"1", "midi", "dej", "dejeuner"}
_DINNER_CODES = {"3", "soir", "diner"}
_FALLBACK_CODES = {"", "0", "2", "petit-dejeuner", "petit dej", "pdj", "breakfast", "gouter", "collation", "apero", "brunch"}


@dataclass(frozen=True)
class LegacyPlannerRow:
    legacy_id: int
    day: date
    repas: str
    corbeille: str
    headcount: int | None
    recipe_id: int | None
    ingredient_id: int | None
    commentaire: str
    raw: dict[str, object]


@dataclass(frozen=True)
class MigrationLine:
    legacy_id: int
    day: date | None
    repas: str
    recipe_id: int | None
    commentaire: str
    action: str
    entry_type: str | None
    meal_plan_uuid: str | None
    slot_code: str | None
    slot_inferred: bool
    reason_code: str | None
    reason_detail: str | None = None


def normalize_repas(value: object) -> tuple[SlotCode, bool]:
    normalized = _normalize_code("" if value is None else str(value))
    if normalized in _LUNCH_CODES:
        return "lunch", False
    if normalized in _DINNER_CODES:
        return "dinner", False
    if normalized in _FALLBACK_CODES:
        return "dinner", True
    return "dinner", True


def parse_planner_dump(path: Path) -> list[LegacyPlannerRow]:
    sql = path.read_text(encoding="utf-8")
    match = re.search(
        r"INSERT INTO `mkg_recipe__planner` \((?P<columns>.*?)\) VALUES (?P<values>.*?);",
        sql,
        flags=re.S,
    )
    if match is None:
        raise ValueError("mkg_recipe__planner INSERT statement not found")
    columns = [column.strip(" `") for column in match.group("columns").split(",")]
    rows: list[LegacyPlannerRow] = []
    for values in _iter_sql_tuples(match.group("values")):
        raw = dict(zip(columns, [_parse_sql_value(token) for token in _split_sql_values(values)], strict=True))
        if str(raw.get("corbeille") or "").upper() == "OUI":
            continue
        row_date = _parse_date(raw.get("date"))
        if row_date is None:
            continue
        rows.append(
            LegacyPlannerRow(
                legacy_id=int(raw["id"]),
                day=row_date,
                repas=str(raw.get("repas") or ""),
                corbeille=str(raw.get("corbeille") or ""),
                headcount=_positive_int_or_none(raw.get("nb_personne")),
                recipe_id=_positive_int_or_none(raw.get("recipe_id")),
                ingredient_id=_positive_int_or_none(raw.get("ingredient_id")),
                commentaire=str(raw.get("commentaire") or "").strip(),
                raw=raw,
            ),
        )
    return rows


def build_weekly_plans(
    rows: list[LegacyPlannerRow],
    recipe_mapping: dict[int, UUID],
) -> tuple[list[MealPlan], list[MigrationLine]]:
    grouped: dict[tuple[int, int], list[LegacyPlannerRow]] = defaultdict(list)
    for row in rows:
        iso = row.day.isocalendar()
        grouped[(iso.year, iso.week)].append(row)

    plans: list[MealPlan] = []
    report: list[MigrationLine] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    for (iso_year, iso_week), week_rows in sorted(grouped.items()):
        week_start = date.fromisocalendar(iso_year, iso_week, 1)
        week_end = date.fromisocalendar(iso_year, iso_week, 7)
        slots = MealPlan.empty_slots_for_period(week_start, week_end)
        slot_index = {(slot.date, slot.slot_code): index for index, slot in enumerate(slots)}
        rows_consumed = 0
        rows_quarantined = 0
        inferred_slots = 0
        anchor_id = min(row.legacy_id for row in week_rows)

        plan = MealPlan(
            name=f"Semaine {iso_week:02d} {iso_year} (legacy)",
            status=MealPlanStatus.DONE,
            date_start=week_start,
            date_end=week_end,
            slots=slots,
            migration_metadata={
                "source": "mkg_recipe__planner",
                "legacy_anchor_id": anchor_id,
                "iso_week": iso_week,
                "iso_year": iso_year,
                "generated_at": generated_at,
                "slots_with_inferred_code": 0,
                "rows_consumed": 0,
                "rows_quarantined": 0,
            },
        )

        for row in sorted(week_rows, key=lambda item: (item.day, item.legacy_id)):
            slot_code, inferred = normalize_repas(row.repas)
            inferred_slots += int(inferred)
            item, quarantine_reason = _row_to_item(row, recipe_mapping)
            if item is None:
                rows_quarantined += 1
                report.append(_report_line(row, "quarantined", None, str(plan.uuid), slot_code, inferred, quarantine_reason))
                continue
            slot = slots[slot_index[(row.day, slot_code)]]
            next_position = len(slot.items)
            item = item.model_copy(update={"position": next_position})
            slots[slot_index[(row.day, slot_code)]] = slot.model_copy(
                update={
                    "headcount": row.headcount if row.headcount is not None else slot.headcount,
                    "items": [*slot.items, item],
                },
            )
            rows_consumed += 1
            action = "quarantined" if quarantine_reason else "migrated"
            report.append(_report_line(row, action, item.item_type.value, str(plan.uuid), slot_code, inferred, quarantine_reason))

        metadata = dict(plan.migration_metadata or {})
        metadata.update(
            {
                "slots_with_inferred_code": inferred_slots,
                "rows_consumed": rows_consumed,
                "rows_quarantined": rows_quarantined,
            },
        )
        plans.append(plan.model_copy(update={"slots": slots, "migration_metadata": metadata}))
    return plans, report


def write_report(path: Path, lines: list[MigrationLine]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "legacy_id",
                "date",
                "repas",
                "id_recette",
                "commentaire",
                "action",
                "entry_type",
                "meal_plan_uuid",
                "slot_code",
                "slot_inferred",
                "reason_code",
                "reason_detail",
            ],
        )
        writer.writeheader()
        for line in lines:
            writer.writerow(
                {
                    "legacy_id": line.legacy_id,
                    "date": line.day.isoformat() if line.day is not None else "",
                    "repas": line.repas,
                    "id_recette": line.recipe_id or "",
                    "commentaire": line.commentaire,
                    "action": line.action,
                    "entry_type": line.entry_type or "",
                    "meal_plan_uuid": line.meal_plan_uuid or "",
                    "slot_code": line.slot_code or "",
                    "slot_inferred": int(line.slot_inferred),
                    "reason_code": line.reason_code or "",
                    "reason_detail": line.reason_detail or "",
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy mkg_recipe__planner rows into weekly MealPlan aggregates.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--sql-dump", type=Path, required=True)
    parser.add_argument("--recipe-mapping", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    mapping = {int(key): UUID(value) for key, value in json.loads(args.recipe_mapping.read_text(encoding="utf-8")).items()}
    rows = parse_planner_dump(args.sql_dump)
    plans, report = build_weekly_plans(rows, mapping)
    write_report(args.report_path, report)
    migrated_rows = sum(1 for line in report if line.action == "migrated")
    quarantined_rows = sum(1 for line in report if line.action == "quarantined")
    print(
        "total_legacy={total}, migrated_rows={migrated}, quarantined_rows={quarantined}, "
        "plans_built={plans}, dry_run={dry_run}, tenant_id={tenant_id}".format(
            total=len(rows),
            migrated=migrated_rows,
            quarantined=quarantined_rows,
            plans=len(plans),
            dry_run=args.dry_run,
            tenant_id=args.tenant_id,
        ),
    )
    if not args.dry_run:
        print("Persistence is delegated to the service repository in the deployment runbook.")


def _row_to_item(row: LegacyPlannerRow, recipe_mapping: dict[int, UUID]) -> tuple[MealItem | None, str | None]:
    if row.recipe_id is not None:
        if row.recipe_id in recipe_mapping:
            recipe_uuid = recipe_mapping[row.recipe_id]
            return (
                MealItem(
                    position=0,
                    item_type=MealItemType.RECIPE,
                    recipe_uuid=recipe_uuid,
                    recipe_snapshot=RecipeSnapshot(
                        recipe_uuid=recipe_uuid,
                        title=row.commentaire or f"Recette legacy {row.recipe_id}",
                        short_description=None,
                        servings_default=row.headcount or 1,
                        total_duration_min=None,
                        ingredients=[],
                        snapshot_taken_at=datetime.now(timezone.utc),
                        recipe_version=1,
                    ),
                    legacy_id=row.legacy_id,
                ),
                None,
            )
        note = row.commentaire or f"[recette legacy id={row.recipe_id} introuvable]"
        return (
            MealItem(position=0, item_type=MealItemType.MIXED, note=note, legacy_id=row.legacy_id),
            "recipe_missing",
        )
    if row.commentaire:
        return (
            MealItem(position=0, item_type=MealItemType.MIXED, note=row.commentaire, legacy_id=row.legacy_id),
            None,
        )
    if row.ingredient_id is not None:
        return (
            MealItem(
                position=0,
                item_type=MealItemType.MIXED,
                note=f"[ingredient legacy id={row.ingredient_id}]",
                legacy_id=row.legacy_id,
            ),
            None,
        )
    return None, "empty_row"


def _report_line(
    row: LegacyPlannerRow,
    action: str,
    entry_type: str | None,
    plan_uuid: str | None,
    slot_code: SlotCode,
    inferred: bool,
    reason_code: str | None,
) -> MigrationLine:
    return MigrationLine(
        legacy_id=row.legacy_id,
        day=row.day,
        repas=row.repas,
        recipe_id=row.recipe_id,
        commentaire=row.commentaire,
        action=action,
        entry_type=entry_type,
        meal_plan_uuid=plan_uuid,
        slot_code=slot_code,
        slot_inferred=inferred,
        reason_code=reason_code,
    )


def _normalize_code(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _iter_sql_tuples(values: str) -> list[str]:
    tuples: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    for char in values:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            current.append(char)
            escaped = True
            continue
        if char == "'":
            in_string = not in_string
            current.append(char)
            continue
        if char == "(" and not in_string:
            depth += 1
            if depth == 1:
                current = []
                continue
        if char == ")" and not in_string:
            depth -= 1
            if depth == 0:
                tuples.append("".join(current))
                current = []
                continue
        if depth >= 1:
            current.append(char)
    return tuples


def _split_sql_values(tuple_values: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    in_string = False
    escaped = False
    for char in tuple_values:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            current.append(char)
            escaped = True
            continue
        if char == "'":
            in_string = not in_string
            current.append(char)
            continue
        if char == "," and not in_string:
            values.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    values.append("".join(current).strip())
    return values


def _parse_sql_value(token: str) -> object:
    if token.upper() == "NULL":
        return None
    if token.startswith("'") and token.endswith("'"):
        return (
            token[1:-1]
            .replace("\\r", "\r")
            .replace("\\n", "\n")
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _positive_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    number = int(value)
    return number if number > 0 else None


if __name__ == "__main__":
    main()
