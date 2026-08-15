"""Quick standalone proof that CopperleafEnvironment checks real DB state,
not a random draw. Run directly: python planning/test_grounded_environment.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planning_lab.algorithms.environment import CopperleafEnvironment

env = CopperleafEnvironment()

print("=== Case 1: no concrete fields (should fail, score 0.0) ===")
print(env.evaluate("We should probably order more tomatoes soon."))

print("\n=== Case 2: real item, wrong supplier (should fail, score 0.1) ===")
print(env.evaluate("Order item_id=1 quantity=10kg from supplier_id=999."))

print("\n=== Case 3: real, valid standard order (should succeed) ===")
print(env.evaluate("Place a standard order: item_id=1 supplier_id=1 quantity=10kg."))

print("\n=== Case 4: expedited, likely over capacity if run repeatedly ===")
print(env.evaluate("Expedite item_id=1 supplier_id=1 quantity=10kg."))