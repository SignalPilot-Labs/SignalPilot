"""Compile the governed dashboard query subset for registered connectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gateway.connectors.registry import get_dashboard_dialect
from gateway.dashboard.dialects import DashboardDialect, DashboardDialectError
from gateway.dashboard.domain import AdHocSqlQuery, FilterRule, SemanticChartQuery
from gateway.governance.bindings import BoundQuery
from gateway.models.dashboards import DashboardSemanticContext


class DashboardCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledDashboardQuery:
    bound_query: BoundQuery
    tables: list[str]
    semantic_definition: dict[str, Any]
    output_columns: list[dict[str, Any]]

    @property
    def sql(self) -> str:
        return self.bound_query.render().sql

    @property
    def parameters(self) -> list[Any]:
        return list(self.bound_query.parameters)


def _dialect(value: str | DashboardDialect) -> DashboardDialect:
    if isinstance(value, DashboardDialect):
        return value
    try:
        return get_dashboard_dialect(value)
    except ValueError as exc:
        raise DashboardCompileError(f"Unsupported dashboard connection type: {value}") from exc


def _quote(dialect: DashboardDialect, value: str) -> str:
    try:
        return dialect.quote_identifier(value)
    except DashboardDialectError as exc:
        raise DashboardCompileError(str(exc)) from exc


def _quote_relation(dialect: DashboardDialect, value: str) -> str:
    try:
        return dialect.quote_relation(value)
    except DashboardDialectError as exc:
        raise DashboardCompileError(str(exc)) from exc


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
    dialect: DashboardDialect,
) -> str | None:
    values = list(rule.values or [])
    if rule.operator == "equals":
        if not values:
            return None
        if len(values) == 1:
            placeholder = dialect.parameter(len(parameters))
            parameters.append(values[0])
            return f"{expression} = {placeholder}"
        placeholders = [dialect.parameter(len(parameters) + index) for index in range(len(values))]
        parameters.extend(values)
        return f"{expression} IN ({', '.join(placeholders)})"
    if rule.operator == "isNull":
        return f"{expression} IS NULL"
    if rule.operator == "notNull":
        return f"{expression} IS NOT NULL"
    if rule.operator == "inBetween":
        if len(values) != 2:
            raise DashboardCompileError("inBetween filters require start and end values")
        if logical_type in {"date", "timestamp"}:
            try:
                zone = ZoneInfo(timezone)
                normalized_values: list[Any] = []
                for value in values:
                    if not isinstance(value, str):
                        normalized_values.append(value)
                        continue
                    if logical_type == "date":
                        normalized_values.append(date.fromisoformat(value))
                    else:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        normalized_values.append(
                            parsed.replace(tzinfo=zone).astimezone(UTC)
                            if parsed.tzinfo is None
                            else parsed.astimezone(UTC)
                        )
                values = normalized_values
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise DashboardCompileError("Invalid date range or dashboard timezone") from exc
        start = dialect.parameter(len(parameters))
        end = dialect.parameter(len(parameters) + 1)
        parameters.extend(values)
        return f"{expression} >= {start} AND {expression} < {end}"

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
    start_parameter = dialect.parameter(len(parameters))
    end_parameter = dialect.parameter(len(parameters) + 1)
    parameters.extend([start.astimezone(UTC), end.astimezone(UTC)])
    return f"{expression} >= {start_parameter} AND {expression} < {end_parameter}"


def compile_metric_query(
    query: SemanticChartQuery,
    context: DashboardSemanticContext,
    *,
    runtime_filters: list[FilterRule] | None = None,
    drill_dimensions: list[str] | None = None,
    now: datetime | None = None,
) -> CompiledDashboardQuery:
    dialect = _dialect(context.connection_type)
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

    select_parts = [
        f"{_quote(dialect, dimensions[field_id].column)} AS {_quote(dialect, field_id)}"
        for field_id in selected_dimensions
    ]
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
            f"COUNT(DISTINCT {_quote(dialect, metric.column)})"
            if metric.aggregation == "count_distinct"
            else f"{function}({_quote(dialect, metric.column)})"
        )
        select_parts.append(f"{expression} AS {_quote(dialect, field_id)}")

    parameters: list[Any] = []
    predicates: list[str] = []
    for rule in [*_filter_rules(query.filters.dimensions), *(runtime_filters or [])]:
        field = dimensions.get(rule.target.fieldId)
        if field is None:
            raise DashboardCompileError(f"Unknown filter field: {rule.target.fieldId}")
        predicate = _compile_predicate(
            expression=_quote(dialect, field.column),
            rule=rule,
            parameters=parameters,
            timezone=query.timezone or "UTC",
            logical_type=field.logical_type,
            now=now,
            dialect=dialect,
        )
        if predicate:
            predicates.append(predicate)
    if query.filters.metrics is not None:
        raise DashboardCompileError("Post-aggregation metric filters are not supported in Phase 1")

    sql = f"SELECT {', '.join(select_parts)} FROM {_quote_relation(dialect, explore.relation)}"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if selected_dimensions:
        sql += " GROUP BY " + ", ".join(
            _quote(dialect, dimensions[field_id].column) for field_id in selected_dimensions
        )
    if query.sorts:
        order_parts: list[str] = []
        outputs = {*selected_dimensions, *query.metrics}
        for sort in query.sorts:
            if sort.fieldId not in outputs:
                continue
            order_parts.append(f"{_quote(dialect, sort.fieldId)} {'DESC' if sort.descending else 'ASC'}")
        sql += " ORDER BY " + ", ".join(order_parts)

    return CompiledDashboardQuery(
        bound_query=BoundQuery(sql, tuple(parameters), dialect.db_type, dialect.parameter_style),
        tables=[explore.relation],
        semantic_definition={
            "explore": explore.name,
            "relation": explore.relation,
            "dimensions": [dimensions[field_id].model_dump() for field_id in selected_dimensions],
            "metrics": [metrics[field_id].model_dump() for field_id in query.metrics],
            "project_id": query.projectId,
            "commit_sha": query.commitSha,
            "connection_type": dialect.db_type,
        },
        output_columns=[
            {
                "name": field.field_id,
                "logical_type": field.logical_type,
                "nullable": True,
                "label": field.label or field.field_id.rsplit(".", 1)[-1].replace("_", " ").title(),
                "format": getattr(field, "format", None),
                "currency_code": (
                    field.format.split(":", 1)[1]
                    if getattr(field, "format", None) and field.format.startswith("currency:")
                    else None
                ),
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
    dialect: str | DashboardDialect,
    runtime_filters: list[FilterRule] | None = None,
    timezone: str = "UTC",
    now: datetime | None = None,
) -> CompiledDashboardQuery:
    dialect = _dialect(dialect)
    bindings = {binding.dashboardFieldId: binding for binding in query.outputBindings}
    parameters: list[Any] = []
    predicates: list[str] = []
    for rule in runtime_filters or []:
        binding = bindings.get(rule.target.fieldId)
        if binding is None:
            raise DashboardCompileError(f"Custom SQL filter has no declared output binding: {rule.target.fieldId}")
        predicate = _compile_predicate(
            expression=f"{_quote(dialect, 'sp_dashboard')}.{_quote(dialect, binding.outputColumn)}",
            rule=rule,
            parameters=parameters,
            timezone=timezone,
            logical_type=binding.logicalType,
            now=now,
            dialect=dialect,
        )
        if predicate:
            predicates.append(predicate)
    alias = _quote(dialect, "sp_dashboard")
    sql = f"SELECT * FROM ({query.sqlTemplate.rstrip().rstrip(';')}) AS {alias}"
    if predicates:
        sql += " WHERE " + " AND ".join(f"({predicate})" for predicate in predicates)
    return CompiledDashboardQuery(
        bound_query=BoundQuery(sql, tuple(parameters), dialect.db_type, dialect.parameter_style),
        tables=[],
        semantic_definition={
            "kind": "custom_sql",
            "output_bindings": [binding.model_dump() for binding in query.outputBindings],
            "connection_type": dialect.db_type,
        },
        output_columns=[
            {
                "name": binding.outputColumn,
                "logical_type": binding.logicalType,
                "nullable": True,
                "label": binding.outputColumn.replace("_", " ").title(),
                "format": None,
                "currency_code": None,
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
    dialect = _dialect(context.connection_type)
    explore = next((item for item in context.explores if item.name == explore_name), None)
    if explore is None:
        raise DashboardCompileError(f"Unknown explore: {explore_name}")
    field = next((item for item in explore.dimensions if item.field_id == field_id), None)
    if field is None:
        raise DashboardCompileError(f"Unknown dimension: {field_id}")
    column = _quote(dialect, field.column)
    parameters: list[Any] = []
    predicate = f" WHERE {column} IS NOT NULL"
    if search:
        predicate += " AND " + dialect.search_predicate(column, dialect.parameter(len(parameters)))
        parameters.append(f"%{search}%")
    sql = dialect.distinct_values_sql(
        column=column,
        relation=_quote_relation(dialect, explore.relation),
        predicate=predicate,
        alias=_quote(dialect, "value"),
        limit=max(1, min(limit, 100)),
    )
    return CompiledDashboardQuery(
        bound_query=BoundQuery(sql, tuple(parameters), dialect.db_type, dialect.parameter_style),
        tables=[explore.relation],
        semantic_definition={
            "explore": explore.name,
            "dimension": field.model_dump(),
            "connection_type": dialect.db_type,
        },
        output_columns=[{"name": "value", "logical_type": field.logical_type, "nullable": True}],
    )
