"""Compile the supported Lightdash-derived semantic query subset to MSSQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway.dashboard.domain import FilterRule, SemanticChartQuery
from gateway.models.dashboards import DashboardSemanticContext


class DashboardCompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledDashboardQuery:
    sql: str
    parameters: list[Any]
    tables: list[str]
    semantic_definition: dict[str, Any]


def _quote(value: str) -> str:
    if not value or "\x00" in value:
        raise DashboardCompileError("Invalid MSSQL identifier")
    return "[" + value.replace("]", "]]" ) + "]"


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


def compile_metric_query(query: SemanticChartQuery, context: DashboardSemanticContext) -> CompiledDashboardQuery:
    explore = next((item for item in context.explores if item.name == query.exploreName), None)
    if explore is None:
        raise DashboardCompileError(f"Unknown explore: {query.exploreName}")
    dimensions = {field.field_id: field for field in explore.dimensions}
    metrics = {field.field_id: field for field in explore.metrics}
    unknown_dimensions = [field_id for field_id in query.dimensions if field_id not in dimensions]
    unknown_metrics = [field_id for field_id in query.metrics if field_id not in metrics]
    if unknown_dimensions or unknown_metrics:
        raise DashboardCompileError(
            f"Unknown semantic fields: {unknown_dimensions + unknown_metrics}"
        )

    select_parts = [
        f"{_quote(dimensions[field_id].column)} AS {_quote(field_id)}"
        for field_id in query.dimensions
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
            f"COUNT(DISTINCT {_quote(metric.column)})"
            if metric.aggregation == "count_distinct"
            else f"{function}({_quote(metric.column)})"
        )
        select_parts.append(f"{expression} AS {_quote(field_id)}")

    parameters: list[Any] = []
    predicates: list[str] = []
    for rule in _filter_rules(query.filters.dimensions):
        field = dimensions.get(rule.target.fieldId)
        if field is None:
            raise DashboardCompileError(f"Unknown filter field: {rule.target.fieldId}")
        if rule.operator == "equals":
            if not rule.values or len(rule.values) != 1:
                raise DashboardCompileError("equals filters require exactly one value")
            predicates.append(f"{_quote(field.column)} = %s")
            parameters.append(rule.values[0])
        elif rule.operator == "isNull":
            predicates.append(f"{_quote(field.column)} IS NULL")
        elif rule.operator == "notNull":
            predicates.append(f"{_quote(field.column)} IS NOT NULL")
        else:
            raise DashboardCompileError(f"Filter operator is not supported in Phase 1: {rule.operator}")
    if query.filters.metrics is not None:
        raise DashboardCompileError("Post-aggregation metric filters are not supported in Phase 1")

    sql = f"SELECT {', '.join(select_parts)} FROM {_quote_relation(explore.relation)}"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if query.dimensions:
        sql += " GROUP BY " + ", ".join(_quote(dimensions[field_id].column) for field_id in query.dimensions)
    if query.sorts:
        order_parts: list[str] = []
        outputs = {*query.dimensions, *query.metrics}
        for sort in query.sorts:
            if sort.fieldId not in outputs:
                raise DashboardCompileError(f"Unknown sort field: {sort.fieldId}")
            order_parts.append(f"{_quote(sort.fieldId)} {'DESC' if sort.descending else 'ASC'}")
        sql += " ORDER BY " + ", ".join(order_parts)

    return CompiledDashboardQuery(
        sql=sql,
        parameters=parameters,
        tables=[explore.relation],
        semantic_definition={
            "explore": explore.name,
            "relation": explore.relation,
            "dimensions": [dimensions[field_id].model_dump() for field_id in query.dimensions],
            "metrics": [metrics[field_id].model_dump() for field_id in query.metrics],
            "project_id": query.projectId,
            "commit_sha": query.commitSha,
        },
    )
