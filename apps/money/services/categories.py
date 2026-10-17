"""Číselník účelů (P03)."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models import Count

from apps.core.formatting import czech_sort_key
from apps.money.models import Category, CategoryKind

KIND_ORDER = list(CategoryKind.values)


def sort_key(category: Category) -> tuple[int, int, tuple[str, str]]:
    return KIND_ORDER.index(category.kind), category.sort, czech_sort_key(category.name)


def list_categories() -> list[tuple[Category, int]]:
    """Všechny účely s počtem pohybů, seřazené podle druhu a pořadí."""
    qs = Category.objects.annotate(used=Count("entry"))
    return [(c, c.used) for c in sorted(qs, key=sort_key)]


def category_choices(keep_ids: set[int] | None = None) -> list[Category]:
    """Účely do výběru ve formuláři; neaktivní jen pokud jsou už vybrané."""
    keep = keep_ids or set()
    return sorted((c for c in Category.objects.all() if c.active or c.id in keep), key=sort_key)


@dataclass(frozen=True)
class CategoryInput:
    name: str
    kind: str
    sort: int
    active: bool
    taxable: bool = True


def save_category(category: Category | None, data: CategoryInput) -> Category:
    errors: dict[str, str] = {}
    name = data.name.strip()
    if not name:
        errors["name"] = "Zadej název účelu."
    elif (
        Category.objects.filter(name__iexact=name)
        .exclude(pk=category.pk if category else 0)
        .exists()
    ):
        errors["name"] = f"Účel „{name}“ už existuje."
    if data.kind not in CategoryKind.values:
        errors["kind"] = "Vyber druh účelu."
    elif category is not None and category.kind != data.kind:
        if category.code:
            errors["kind"] = "Výchozímu účelu nejde změnit druh."
        elif category.entry_set.exists():
            errors["kind"] = "Účel už má pohyby, druh nejde změnit."
    if errors:
        raise ValidationError(errors)
    category = category or Category()
    category.name = name
    category.kind = data.kind
    category.sort = data.sort
    category.active = data.active
    category.taxable = data.taxable
    category.save()
    return category


def delete_category(category: Category) -> None:
    if category.code:
        raise ValidationError("Výchozí účel nejde smazat – můžeš ho deaktivovat.")
    if category.entry_set.exists():
        raise ValidationError("Účel má pohyby, nejde smazat – můžeš ho deaktivovat.")
    category.delete()
