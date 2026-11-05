"""Einstellungen je Profil mit festen Vorgaben (z. B. ob Fixkosten automatisch angelegt werden).

Automatik ist standardmäßig aus: neue Profile bekommen nur Vorschläge. `dry_run` protokolliert,
was automatisch übernommen worden wäre, ohne etwas zu ändern.
"""

from typing import Any

from sqlmodel import Session, select

from app.errors import Invalid
from app.models import ProfileSetting, User

AUTOMATION = ("off", "suggest", "dry_run", "auto")

# Schlüssel → (Vorgabe, erlaubte Werte oder Typ)
DEFAULTS: dict[str, tuple[Any, tuple | type]] = {
    "automation.fixed_cost": ("suggest", AUTOMATION),
    "automation.fixed_cost_change": ("suggest", AUTOMATION),
    "automation.rules": ("suggest", AUTOMATION),
    "automation.split_templates": ("suggest", AUTOMATION),
    "ai.enabled": (True, bool),
    "forecast.horizon_days": (45, int),
    "household.cross_profile_matching": (False, bool),
}


def _check(key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise Invalid(f"Unbekannte Einstellung: {key}", code="setting_unknown", details={"key": key})
    _, allowed = DEFAULTS[key]
    if isinstance(allowed, tuple):
        ok = value in allowed
    elif allowed is int:
        ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 366
    else:
        ok = isinstance(value, allowed)
    if not ok:
        raise Invalid(f"Ungültiger Wert für {key}", code="setting_invalid", details={"key": key, "value": value})


def all_settings(session: Session, user_id: int) -> dict[str, Any]:
    stored = {s.key: s.value for s in session.exec(select(ProfileSetting).where(ProfileSetting.user_id == user_id))}
    return {key: stored.get(key, default) for key, (default, _) in DEFAULTS.items()}


def get(session: Session, user_id: int, key: str) -> Any:
    row = session.get(ProfileSetting, (user_id, key))
    return row.value if row is not None else DEFAULTS[key][0]


def update(session: Session, user: User, changes: dict[str, Any]) -> dict[str, Any]:
    for key, value in changes.items():
        _check(key, value)
    for key, value in changes.items():
        row = session.get(ProfileSetting, (user.id, key))
        if row is None:
            session.add(ProfileSetting(user_id=user.id, key=key, value=value))
        else:
            row.value = value
    session.flush()
    return all_settings(session, user.id)
