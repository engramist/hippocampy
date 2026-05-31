"""Procedure maturity lifecycle management.

Stages:
  nascent (0-2 applications) → developing (3-9) → mature (10+)
  → degraded (success_rate drops below 0.4) → archived (manual or decay)
"""
import logging
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
        result = db.execute(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "RETURN p.procedure_id, p.application_count, p.success_rate, p.maturity_stage"
        )
        
        procedures = []
        while result.has_next():
            row = result.get_next()
            procedures.append({
                "procedure_id": row[0],
                "application_count": row[1] or 0,
                "success_rate": row[2] or 0.0,
                "current_stage": row[3] or "nascent",
            })
        
        for proc in procedures:
            new_stage = _compute_stage(
                proc["application_count"],
                proc["success_rate"],
                proc["current_stage"],
            )
            if new_stage != proc["current_stage"]:
                await db.execute_write(
                    "MATCH (p:Procedure {procedure_id: $pid}) "
                    "SET p.maturity_stage = $stage",
                    {"pid": proc["procedure_id"], "stage": new_stage},
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
