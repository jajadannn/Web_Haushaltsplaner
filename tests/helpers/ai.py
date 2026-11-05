"""Test-Hilfen für die KI-Anbindung (bewusst nicht im Anwendungscode)."""

from app.services import ai_gateway


def reset_ai_health() -> None:
    """Ausfallzustand der KI-Server zwischen Tests zurücksetzen."""
    ai_gateway._down.clear()
