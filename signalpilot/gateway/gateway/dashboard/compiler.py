"""Compile the supported Lightdash-derived semantic query subset to MSSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gateway.dashboard.domain import AdHocSqlQuery, FilterRule, SemanticChartQuery
from gateway.models.dashboards import DashboardSemanticContext


class DashboardCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledDashboardQuery:
    sql: str
    parameters: list[Any]
    tables: list[str]
    semantic_definition: dict[str, Any]
    output_columns: list[dict[str, Any]]


def _quote(value: str) -> str:
    if not value or "\x00" in value:
        raise DashboardCompileError("Invalid MSSQL identifier")
    return "[" + value.replace("]", "]]") + "]"


def _quote_relation(value: str) -> str:
    parts = value.split(".")
    if not 1 <= len(parts) <= 3 or any(not part for part in parts):
        raise DashboardCompileError("Invalid MSSQL relation")
    return ".".join(_quote(part) for part in parts)


def _filter_rules(group) -> list[FilterRule]:
    if group is None:
        return []
    children = group.and_ if hasattr(group, "and_") else group.or_
    if hasattr(group, "or_"):
        raise DashboardCompileError("OR filter groups are not supported in Phase 1")
    rules: list[FilterRule] = []
    for child in children:
        if isinstance(child, FilterRule):
            rules.append(child)
        else:
            rules.extend(_filter_rules(child))
    return rules


def _period_start(now: datetime, unit: str) -> datetime:
    if unit == "days":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "weeks":
        return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "months":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if unit == "quarters":
        return now.replace(month=((now.month - 1) // 3) * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if unit == "years":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    raise DashboardCompileError(f"Unsupported date unit: {unit}")


def _past_start(now: datetime, amount: int, unit: str) -> datetime:
    if unit == "days":
        return now - timedelta(days=amount)
    if unit == "weeks":
        return now - timedelta(weeks=amount)
    if unit == "months":
        month_index = now.year * 12 + now.month - 1 - amount
        return now.replace(year=month_index // 12, month=month_index % 12 + 1)
    if unit == "quarters":
        return _past_start(now, amount * 3, "months")
    if unit == "years":
        return now.replace(year=now.year - amount)
    raise DashboardCompileError(f"Unsupported date unit: {unit}")


def _compile_predicate(
    *,
    expression: str,
    rule: FilterRule,
    parameters: list[Any],
    timezone: str,
    logical_type: str | None,
    now: datetime | None,
) -> str | None:
    values = list(rule.values or [])
    if rule.operator == "equals":
        if not values:
            return None
        if len(values) == 1:
            parameters.append(values[0])
            return f"{expression} = %s"
        parameters.extend(values)
        return f"{expression} IN ({', '.join('%s' for _ in values)})"
    if rule.operator == "isNull":
        return f"{expression} IS NULL"
    if rule.operator == "notNull":
        return f"{expression} IS NOT NULL"
    if rule.operator == "inBetween":
        if len(values) != 2:
            raise DashboardCompileError("inBetween filters require start and end values")
        if logical_type == "timestamp":
            try:
                zone = ZoneInfo(timezone)
                normalized_values: list[Any] = []
                for value in values:
                    if not isinstance(value, str):
                        normalized_values.append(value)
                        continue
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    normalized_values.append(
                        parsed.replace(tzinfo=zone).astimezone(UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
                    )
                values = normalized_values
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise DashboardCompileError("Invalid timestamp range or dashboard timezone") from exc
        parameters.extend(values)
        return f"{expression} >= %s AND {expression} < %s"

    settings = rule.settings
    unit = settings.unitOfTime if settings else None
    if not unit:
        raise DashboardCompileError(f"{rule.operator} filters require a unitOfTime")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise DashboardCompileError(f"Unknown dashboard timezone: {timezone}") from exc
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    if rule.operator == "inThePast":
        if len(values) != 1 or isinstance(values[0], bool) or not isinstance(values[0], (int, float)):
            raise DashboardCompileError("inThePast filters require one numeric value")
        start = _past_start(local_now, int(values[0]), unit)
        end = local_now
    elif rule.operator in {"inTheCurrent", "inPeriodToDate"}:
        start = _period_start(local_now, unit)
        end = local_now if rule.operator == "inPeriodToDate" else _past_start(start, -1, unit)
    else:
        raise DashboardCompileError(f"Unsupported filter operator: {rule.operator}")
    parameters.extend([start.astimezone(UTC), end.astimezone(UTC)])
    return f"{expression} >= %s AND {expression} < %s"


def compile_metric_query(
    query: SemanticChartQuery,
    context: DashboardSemanticContext,
    *,
    runtime_filters: list[FilterRule] | None = None,
    drill_dimensions: list[str] | None = None,
    now: datetime | None = None,
) -> CompiledDashboardQuery:
    explore = next((item for item in context.explores if item.name == query.exploreName), None)
    if explore is None:
        raise DashboardCompileError(f"Unknown explore: {query.exploreName}")
    dimensions = {field.field_id: field for field in explore.dimensions}
    metrics = {field.field_id: field for field in explore.metrics}
    selected_dimensions = drill_dimensions if drill_dimensions is not None else query.dimensions
    unknown_dimensions = [field_id for field_id in selected_dimensions if field_id not in dimensions]
    unknown_metrics = [field_id for field_id in query.metrics if field_id not in metrics]
    if unknown_dimensions or unknown_metrics:
        raise DashboardCompileError(f"Unknown semantic fields: {unknown_dimensions + unknown_metrics}")

    select_parts = [f"{_quote(dimensions[field_id].column)} AS {_quote(field_id)}" for field_id in selected_dimensions]
    aggregation_sql = {
        "sum": "SUM",
        "count": "COUNT",
        "count_distinct": "COUNT(DISTINCT",
        "average": "AVG",
        "min": "MIN",
        "max": "MAX",
    }
    for field_id in query.metrics:
        metric = metrics[field_id]
        function = aggregation_sql[metric.aggregation]
        expression = (
            f"COUNT(DISTINCT {_quote(metric.column)})"
            if metric.aggregation == "count_distinct"
            else f"{function}({_quote(metric.column)})"
        )
        select_parts.append(f"{expression} AS {_quote(field_id)}")

    parameters: list[Any] = []
    predicates: list[str] = []
    for rule in [*_filter_rules(query.filters.dimensions), *(runtime_filters or [])]:
        field = dimensions.get(rule.target.fieldId)
        if field is None:
            raise DashboardCompileError(f"Unknown filter field: {rule.target.fieldId}")
        predicate = _compile_predicate(
            expression=_quote(field.column),
            rule=rule,
            parameters=parameters,
            timezone=query.timezone or "UTC",
            logical_type=field.logical_type,
            now=now,
        )
        if predicate:
            predicates.append(predicate)
    if query.filters.metrics is not None:
        raise DashboardCompileError("Post-aggregation metric filters are not supported in Phase 1")

    sql = f"SELECT {', '.join(select_parts)} FROM {_quote_relation(explore.relation)}"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if selected_dimensions:
        sql += " GROUP BY " + ", ".join(_quote(dimensions[field_id].column) for field_id in selected_dimensions)
    if query.sorts:
        order_parts: list[str] = []
        outputs = {*selected_dimensions, *query.metrics}
        for sort in query.sorts:
            if sort.fieldId not in outputs:
                continue
            order_parts.append(f"{_quote(sort.fieldId)} {'DESC' if sort.descending else 'ASC'}")
        sql += " ORDER BY " + ", ".join(order_parts)

    return CompiledDashboardQuery(
        sql=sql,
        parameters=parameters,
        tables=[explore.relation],
        semantic_definition={
            "explore": explore.name,
            "relation": explore.relation,
            "dimensions": [dimensions[field_id].model_dump() for field_id in selected_dimensions],
            "metrics": [metrics[field_id].model_dump() for field_id in query.metrics],
            "project_id": query.projectId,
            "commit_sha": query.commitSha,
        },
        output_columns=[
            {
                "name": field.field_id,
                "logical_type": field.logical_type,
                "nullable": True,
            }
            for field in [
                *(dimensions[field_id] for field_id in selected_dimensions),
                *(metrics[field_id] for field_id in query.metrics),
            ]
        ],
    )


def compile_custom_sql_query(
    query: AdHocSqlQuery,
    *,
    runtime_filters: list[FilterRule] | None = None,
    timezone: str = "UTC",
    now: datetime | None = None,
) -> CompiledDashboardQuery:
    bindings = {binding.dashboardFieldId: binding for binding in query.outputBindings}
    parameters: list[Any] = []
    predicates: list[str] = []
    for rule in runtime_filters or []:
        binding = bindings.get(rule.target.fieldId)
        if binding is None:
            raise DashboardCompileError(f"Custom SQL filter has no declared output binding: {rule.target.fieldId}")
        predicate = _compile_predicate(
            expression=f"[sp_dashboard].{_quote(binding.outputColumn)}",
            rule=rule,
            parameters=parameters,
            timezone=timezone,
            logical_type=binding.logicalType,
            now=now,
        )
        if predicate:
            predicates.append(predicate)
    sql = f"SELECT * FROM ({query.sqlTemplate.rstrip().rstrip(';')}) AS [sp_dashboard]"
    if predicates:
        sql += " WHERE " + " AND ".join(f"({predicate})" for predicate in predicates)
    return CompiledDashboardQuery(
        sql=sql,
        parameters=parameters,
        tables=[],
        semantic_definition={
            "kind": "custom_sql",
            "output_bindings": [binding.model_dump() for binding in query.outputBindings],
        },
        output_columns=[
            {
                "name": binding.outputColumn,
                "logical_type": binding.logicalType,
                "nullable": True,
            }
            for binding in query.outputBindings
        ],
    )


def compile_distinct_values_query(
    *,
    explore_name: str,
    field_id: str,
    context: DashboardSemanticContext,
    search: str | None = None,
    limit: int = 100,
) -> CompiledDashboardQuery:
    explore = next((item for item in context.explores if item.name == explore_name), None)
    if explore is None:
        raise DashboardCompileError(f"Unknown explore: {explore_name}")
    field = next((item for item in explore.dimensions if item.field_id == field_id), None)
    if field is None:
        raise DashboardCompileError(f"Unknown dimension: {field_id}")
    column = _quote(field.column)
    parameters: list[Any] = []
    predicate = f" WHERE {column} IS NOT NULL"
    if search:
        predicate += f" AND CAST({column} AS NVARCHAR(4000)) LIKE %s"
        parameters.append(f"%{search}%")
    sql = (
        f"SELECT DISTINCT TOP {max(1, min(limit, 100))} {column} AS [value] "
        f"FROM {_quote_relation(explore.relation)}{predicate} ORDER BY [value]"
    )
    return CompiledDashboardQuery(
        sql=sql,
        parameters=parameters,
        tables=[explore.relation],
        semantic_definition={"explore": explore.name, "dimension": field.model_dump()},
        output_columns=[
            {
                "name": "value",
                "logical_type": field.logical_type,
                "nullable": True,
            }
        ],
    )
