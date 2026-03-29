from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class LongContextMetrics:
    accuracy: float
    avg_tokens_used: float
    context_size: int
    variant: str  # "baseline" or "sidequests"

def calculate_accuracy(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    correct = sum(1 for r in results if r.get("correct", False))
    return correct / len(results)

def calculate_token_efficiency(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    total_tokens = sum(r.get("tokens_used", 0) for r in results)
    return total_tokens / len(results)

def aggregate_metrics(results: List[Dict[str, Any]], context_size: int, variant: str) -> LongContextMetrics:
    return LongContextMetrics(
        accuracy=calculate_accuracy(results),
        avg_tokens_used=calculate_token_efficiency(results),
        context_size=context_size,
        variant=variant
    )
