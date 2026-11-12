"""Live batch and bottle cost (roadmap 8.1; spec .agents/specs/live-cogs.md).

8.1a is the cost engine: ``cost_flows`` written by Core's stock writes (``flows.py``), manual and
free prices (``service.py``), the roll-up computed on read (``engine.py``), the backfill
(``backfill.py``) and the costing API (``routes.py``).
"""

FEATURE_KEY = "costing"
