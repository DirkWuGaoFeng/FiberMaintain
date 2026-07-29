"""
Batch processor sub-graph: Send Map-Reduce for parallel fiber processing.

This sub-graph is invoked by the batch_dispatcher which returns Send objects.
Each Send targets the batch_worker node for parallel execution.
Results are aggregated by batch_aggregator.

Note: This is not a standalone sub-graph but rather a set of nodes
used directly in the main graph via Send mechanism.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The batch processor nodes are defined in src/nodes/:
#   - batch_dispatcher.py: splits fiber IDs into chunks, returns list[Send]
#   - batch_worker.py: processes a single chunk (called via Send)
#   - batch_aggregator.py: merges all chunk results
#
# These are wired directly in main_graph.py rather than as a separate sub-graph
# because LangGraph's Send mechanism requires nodes to be in the same graph.
#
# Flow in main graph:
#   batch_dispatcher -> [Send x N] -> batch_worker (parallel) -> batch_aggregator
