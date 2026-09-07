"""Standalone decomposition engine — Step 2.

Everything in this package must work from raw ticket-level data alone. It
must never import generator.bridge or generator.scenarios, and must never
read ground_truth/*.json — those exist purely to validate this engine from
the outside (see validate_engine.py), not to inform its logic.
"""
