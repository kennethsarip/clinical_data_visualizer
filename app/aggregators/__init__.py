"""One module per aggregator family (CLAUDE.md §7.4).

Importing this package registers every aggregator into `registry.REGISTRY`.
"""

from app.aggregators import categorical, comparison, network, numeric, time_trend

__all__ = ["categorical", "comparison", "network", "numeric", "time_trend"]
