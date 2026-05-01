from __future__ import annotations

from src.domain.models import AgentHaltStatus
from src.storage.db import session_scope
from src.storage.repositories import AccountHealthRepository


def get_active_halt():
    with session_scope() as session:
        halt = AccountHealthRepository(session).latest_active_halt()
        if halt is None:
            return None
        return AgentHaltStatus(
            halt_id=halt.id,
            reason_code=halt.reason_code,
            reason=halt.reason,
            created_at=halt.created_at,
            thresholds=halt.thresholds_json or {},
            observed=halt.observed_json or {},
        )


def operation_blocked_result(command: str):
    halt = get_active_halt()
    if halt is None:
        return None
    log_blocked_operation(command, halt)
    return {
        "status": "halted",
        "command": command,
        "halt_id": halt.halt_id,
        "reason_code": halt.reason_code,
        "reason": halt.reason,
        "created_at": halt.created_at.isoformat(),
    }


def log_blocked_operation(command: str, halt: AgentHaltStatus):
    with session_scope() as session:
        AccountHealthRepository(session).log_event(
            "operation_blocked_by_halt",
            {
                "command": command,
                "halt_id": halt.halt_id,
                "reason_code": halt.reason_code,
                "reason": halt.reason,
                "created_at": halt.created_at.isoformat(),
                "thresholds": halt.thresholds,
                "observed": halt.observed,
            },
        )


def resume_agent(resolved_by: str = "manual", note: str | None = None):
    with session_scope() as session:
        repo = AccountHealthRepository(session)
        halt = repo.resolve_active_halt(resolved_by=resolved_by, note=note)
        if halt is None:
            return {"status": "not_halted"}
        repo.log_event(
            "agent_resumed",
            {
                "halt_id": halt.id,
                "reason_code": halt.reason_code,
                "resolved_by": resolved_by,
                "resolution_note": note,
                "resolved_at": halt.resolved_at.isoformat() if halt.resolved_at else None,
            },
        )
        return {
            "status": "resumed",
            "halt_id": halt.id,
            "reason_code": halt.reason_code,
            "resolved_at": halt.resolved_at.isoformat() if halt.resolved_at else None,
        }
