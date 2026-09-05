from __future__ import annotations
"""Procedure maturity lifecycle management.

Stages:
  nascent (0-2 applications) → developing (3-9) → mature (10+)
  → degraded (success_rate drops below 0.4) → archived (manual or decay)
"""
import logging
from campy.brain.hippocampus.graph.gateway import get_gateway

def _row_val(row, idx: int, key: str):
    if isinstance(row, dict):
        return row.get(key)
    if isinstance(row, (list, tuple)) and idx < len(row):
        return row[idx]
    return getattr(row, key, None)
from typing import Optional

_logger = logging.getLogger(__name__)

MATURITY_THRESHOLDS = {
    "nascent": 0,       # 0-2 applications
    "developing": 3,    # 3-9 applications
    "mature": 10,       # 10+ applications
}
DEGRADED_SUCCESS_RATE = 0.4  # Below this → degraded


async def update_procedure_maturity(db, config: dict) -> tuple[int, int]:
    """Update maturity_stage for all Procedure nodes based on application_count and success_rate.
    
    Called during dreaming sweeps.
    
    Returns:
        (updated_count, error_count)
    """
    updated = 0
    errors = 0
    
    try:
        # Query all non-archived Procedures
        gw = get_gateway(db)
        rows = gw.run_sync("basal_ganglia.maturity_get_procedures")

        procedures = []
        for row in rows:
            procedures.append({
                "procedure_id": _row_val(row, 0, "p.procedure_id") or _row_val(row, 0, "procedure_id"),
                "application_count": _row_val(row, 1, "p.application_count") or _row_val(row, 1, "application_count") or 0,
                "success_rate": _row_val(row, 2, "p.success_rate") or _row_val(row, 2, "success_rate") or 0.0,
                "current_stage": _row_val(row, 3, "p.maturity_stage") or _row_val(row, 3, "maturity_stage") or "nascent",
            })
        
        for proc in procedures:
            new_stage = _compute_stage(
                proc["application_count"],
                proc["success_rate"],
                proc["current_stage"],
            )
            if new_stage != proc["current_stage"]:
                await gw.run(
                    "basal_ganglia.maturity_update_stage",
                    pid=proc["procedure_id"],
                    stage=new_stage,
                )
                _logger.info(
                    "[BasalGanglia] Procedure %s: %s → %s",
                    proc["procedure_id"], proc["current_stage"], new_stage,
                )
                updated += 1
    except Exception:
        _logger.exception("[BasalGanglia] maturity update failed")
        errors += 1
    
    return updated, errors


def _compute_stage(application_count: int, success_rate: float, current: str) -> str:
    """Determine the correct maturity stage."""
    if current == "archived":
        return "archived"  # Never auto-unarchive
    
    if success_rate < DEGRADED_SUCCESS_RATE and application_count >= MATURITY_THRESHOLDS["developing"]:
        return "degraded"
    
    if application_count >= MATURITY_THRESHOLDS["mature"]:
        return "mature"
    elif application_count >= MATURITY_THRESHOLDS["developing"]:
        return "developing"
    else:
        return "nascent"
