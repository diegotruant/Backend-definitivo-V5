"""Authenticated principal and role-based access helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Iterable

VALID_ROLES = frozenset({"admin", "owner", "coach", "assistant_coach", "athlete"})

TEAM_WRITE_ROLES = frozenset({"admin", "owner", "coach"})
TEAM_READ_ROLES = frozenset({"admin", "owner", "coach", "assistant_coach"})
TEST_PROPOSE_ROLES = frozenset({"admin", "owner", "coach", "assistant_coach"})
TEST_CONFIRM_ROLES = frozenset({"admin", "owner", "coach"})


@dataclass(frozen=True)
class Principal:
    """Identity resolved from JWT or API key metadata."""

    subject: str
    roles: frozenset[str]
    team_id: str | None = None
    athlete_ids: frozenset[str] = frozenset()
    auth_method: str = "jwt"

    @classmethod
    def from_claims(cls, claims: dict) -> Principal:
        roles_raw = claims.get("roles") or claims.get("role") or []
        if isinstance(roles_raw, str):
            roles_raw = [roles_raw]
        roles = frozenset(str(r).strip().lower() for r in roles_raw if str(r).strip())
        unknown = roles - VALID_ROLES
        if unknown:
            raise ValueError(f"unknown roles: {sorted(unknown)}")

        athlete_ids: set[str] = set()
        if claims.get("athlete_id"):
            athlete_ids.add(str(claims["athlete_id"]).strip())
        for aid in claims.get("athlete_ids") or []:
            if aid:
                athlete_ids.add(str(aid).strip())

        return cls(
            subject=str(claims.get("sub") or claims.get("user_id") or ""),
            roles=roles,
            team_id=str(claims["team_id"]).strip() if claims.get("team_id") else None,
            athlete_ids=frozenset(athlete_ids),
            auth_method="jwt",
        )

    def has_any_role(self, allowed: AbstractSet[str]) -> bool:
        return bool(self.roles & allowed)

    def can_access_athlete(self, athlete_id: str) -> bool:
        if "admin" in self.roles:
            return True
        if athlete_id in self.athlete_ids:
            return True
        return False

    def resolve_athlete_id(self, header_value: str | None) -> str | None:
        """Return athlete scope for this request, enforcing role rules."""
        athlete_id = (header_value or "").strip()
        if "athlete" in self.roles and self.athlete_ids:
            own_id = next(iter(self.athlete_ids))
            if athlete_id and athlete_id != own_id:
                return None
            return own_id
        return athlete_id or None

    def can_access_path(self, path: str) -> bool:
        if path.startswith("/team/calibration/update"):
            return self.has_any_role(TEAM_WRITE_ROLES)
        if path.startswith("/team/calibration/apply"):
            return self.has_any_role(TEAM_READ_ROLES)
        if path.startswith("/test/propose"):
            return self.has_any_role(TEST_PROPOSE_ROLES)
        if path.startswith("/test/confirm") or path.startswith("/test/in-person"):
            return self.has_any_role(TEST_CONFIRM_ROLES)
        return True
