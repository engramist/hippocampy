from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class CostTracker:
    """B180: Accumulates token usage and computes dollar cost per puzzle."""
    model_name: str
    input_price_per_m: float = 0.0
    output_price_per_m: float = 0.0
    budget_usd: float = float('inf')

    _tokens_in: int = 0
    _tokens_out: int = 0

    def record(self, tokens_in: int, tokens_out: int):
        self._tokens_in += tokens_in
        self._tokens_out += tokens_out

    @property
    def total_cost_usd(self) -> float:
        return (self._tokens_in * self.input_price_per_m + self._tokens_out * self.output_price_per_m) / 1_000_000

    @property
    def budget_exhausted(self) -> bool:
        return self.total_cost_usd >= self.budget_usd

    def summary(self) -> dict:
        return {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": self.total_cost_usd,
            "budget_usd": self.budget_usd,
            "budget_exhausted": self.budget_exhausted,
            "model": self.model_name
        }
