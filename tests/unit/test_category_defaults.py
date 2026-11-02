"""Invarianten der Standardkategorien (reine Datenprüfung, ohne Datenbank)."""

import re
from collections import Counter
from collections.abc import Iterable, Iterator

from app.services.category_defaults import DEFAULT_CATEGORIES, DefaultCategory

TYPES = {"income", "expense"}
SYSTEM_KEYS = ["loan_fees", "loan_interest"]
COLOR_PATTERN = re.compile(r"#[0-9A-F]{6}")
ICON_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# Umbuchungen sind ein eigenes Feld (kind=transfer), Tilgung ein Transfer aufs Kreditkonto
FORBIDDEN_NAME_PARTS = ("umbuchung", "transfer", "tilgung")


def walk(categories: Iterable[DefaultCategory]) -> Iterator[DefaultCategory]:
    """Alle Kategorien flach durchlaufen, jede Hauptkategorie vor ihren Kindern."""
    for category in categories:
        yield category
        yield from walk(category.children)


ALL = tuple(walk(DEFAULT_CATEGORIES))


def duplicates(names: Iterable[str]) -> list[str]:
    return [name for name, count in Counter(names).items() if count > 1]


def test_types_are_income_or_expense():
    invalid = {c.name: c.type for c in ALL if c.type not in TYPES}
    assert not invalid


def test_children_have_type_of_parent():
    mismatched = [
        f"{child.name} ({child.type}) unter {parent.name} ({parent.type})"
        for parent in DEFAULT_CATEGORIES
        for child in parent.children
        if child.type != parent.type
    ]
    assert not mismatched


def test_at_most_two_levels():
    too_deep = [
        child.name
        for parent in DEFAULT_CATEGORIES
        for child in parent.children
        if child.children
    ]
    assert not too_deep


def test_names_are_not_empty_and_at_most_100_chars():
    invalid = [
        c.name
        for c in ALL
        if not c.name.strip() or c.name != c.name.strip() or len(c.name) > 100
    ]
    assert not invalid


def test_names_are_unique_per_sibling_group():
    assert not duplicates(c.name for c in DEFAULT_CATEGORIES)
    for parent in DEFAULT_CATEGORIES:
        assert not duplicates(c.name for c in parent.children), parent.name


def test_colors_have_valid_format():
    invalid = {
        c.name: c.color
        for c in ALL
        if c.color is not None and not COLOR_PATTERN.fullmatch(c.color)
    }
    assert not invalid


def test_main_categories_have_distinct_colors():
    missing = [c.name for c in DEFAULT_CATEGORIES if c.color is None]
    assert not missing
    names_by_color: dict[str | None, list[str]] = {}
    for c in DEFAULT_CATEGORIES:
        names_by_color.setdefault(c.color, []).append(c.name)
    shared = {color: names for color, names in names_by_color.items() if len(names) > 1}
    assert not shared


def test_icons_are_kebab_case_and_at_most_50_chars():
    invalid = {
        c.name: c.icon
        for c in ALL
        if c.icon is not None and (not ICON_PATTERN.fullmatch(c.icon) or len(c.icon) > 50)
    }
    assert not invalid


def test_system_keys_are_exactly_loan_interest_and_loan_fees_once_each():
    with_key = [c for c in ALL if c.system_key is not None]
    assert sorted(c.system_key for c in with_key) == SYSTEM_KEYS
    assert all(c.type == "expense" for c in with_key)


def test_no_transfer_like_categories():
    hits = [c.name for c in ALL if any(part in c.name.casefold() for part in FORBIDDEN_NAME_PARTS)]
    assert not hits


def test_has_income_and_expense_main_categories():
    assert TYPES <= {c.type for c in DEFAULT_CATEGORIES}
