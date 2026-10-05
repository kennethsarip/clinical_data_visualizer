"""Row shape -> viz type table; spec + meta assembly; LLM title + notes (CLAUDE.md §7.2, §7.4)."""

from collections.abc import Mapping

from app.aggregators.registry import RowShape

# Python picks the viz type from the aggregator's declared row shape (decided 2026-10-04): each
# shape has exactly one fitting type, so an LLM choice would add a failure mode and no choice.
VIZ_TYPE: Mapping[RowShape, str] = {
    RowShape.CATEGORICAL: "bar_chart",
    RowShape.TWO_CATEGORICAL: "grouped_bar_chart",
    RowShape.TEMPORAL: "time_series",
    RowShape.PER_TRIAL_NUMERIC: "scatter_plot",
    RowShape.BINNED_NUMERIC: "histogram",
    RowShape.GRAPH: "network_graph",
}
