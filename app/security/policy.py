"""Risk classification and fail-closed approval policy."""

from __future__ import annotations

from enum import IntEnum


class RiskLevel(IntEnum):
    READ_ONLY = 0
    LOW_IMPACT = 1
    MODIFICATION = 2
    EXTERNAL_ACTION = 3
    CRITICAL = 4


class PolicyDenied(PermissionError):
    pass


class PermissionPolicy:
    """Allow low-risk registered tools; require explicit approval for L2/L3."""

    def authorize(self, risk: RiskLevel, *, approved: bool = False) -> None:
        if risk is RiskLevel.CRITICAL:
            raise PolicyDenied("Critical actions are disabled by default")
        if risk >= RiskLevel.MODIFICATION and not approved:
            raise PolicyDenied("This action requires explicit user approval")
