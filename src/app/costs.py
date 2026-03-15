from typing import Optional


class BudgetTracker:
    """Lightweight in-memory token/cost tracker.

    Records tokens used and a simple estimated cost if provided by adapters.
    Not persisted; intended for local development and monitoring.
    """

    def __init__(self):
        self.tokens = 0
        self.cost = 0.0
        # per-adapter breakdown: name -> {tokens, cost, calls}
        self.adapters: dict[str, dict] = {}

    def add_tokens(self, n: int):
        try:
            self.tokens += int(n)
        except Exception:
            pass

    def add_cost(self, amount: float):
        try:
            self.cost += float(amount)
        except Exception:
            pass

    def snapshot(self) -> dict:
        return {"tokens": self.tokens, "cost": self.cost, "adapters": self.adapters}

    def add_adapter_usage(self, adapter_name: str, tokens: int = 0, cost: float = 0.0):
        try:
            tokens = int(tokens)
            cost = float(cost)
        except Exception:
            return
        self.add_tokens(tokens)
        self.add_cost(cost)
        stat = self.adapters.get(adapter_name) or {"tokens": 0, "cost": 0.0, "calls": 0}
        stat["tokens"] += tokens
        stat["cost"] += cost
        stat["calls"] += 1
        self.adapters[adapter_name] = stat


# Module-level singleton for easy access from routers/executor
BUDGET = BudgetTracker()

def get_budget_snapshot() -> dict:
    return BUDGET.snapshot()

def reset_budget():
    BUDGET.tokens = 0
    BUDGET.cost = 0.0
    return BUDGET.snapshot()
