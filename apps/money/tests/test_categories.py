import pytest
from django.core.exceptions import ValidationError

from apps.money.models import Account, Category, CategoryCode, CategoryKind, EntryKind
from apps.money.services.categories import (
    CategoryInput,
    delete_category,
    list_categories,
    save_category,
)
from apps.rentals.models import Property

from .conftest import add, category


def test_default_categories(db: None) -> None:
    rows = list_categories()
    assert len(rows) == len(CategoryCode)
    assert [c.name for c, _ in rows][:4] == [
        "Nájemné",
        "Zálohy na služby",
        "Vyúčtování služeb",
        "Ostatní příjmy",
    ]
    assert category(CategoryCode.DEPOSIT).kind == CategoryKind.NEUTRAL
    assert rows[-1][0].code == CategoryCode.DEPOSIT


def test_default_category_rename_but_not_kind_or_delete(db: None) -> None:
    rent = category(CategoryCode.RENT)
    save_category(rent, CategoryInput("Nájem", CategoryKind.INCOME, 5, True))
    assert Category.objects.get(code=CategoryCode.RENT).name == "Nájem"
    with pytest.raises(ValidationError, match="druh"):
        save_category(rent, CategoryInput("Nájem", CategoryKind.EXPENSE, 5, True))
    with pytest.raises(ValidationError, match="deaktivovat"):
        delete_category(rent)


def test_custom_category(db: None) -> None:
    own = save_category(None, CategoryInput("  Úroky z účtu ", CategoryKind.INCOME, 50, True))
    assert own.name == "Úroky z účtu" and own.code is None
    with pytest.raises(ValidationError, match="už existuje"):
        save_category(None, CategoryInput("úroky z účtu", CategoryKind.INCOME, 0, True))
    with pytest.raises(ValidationError, match="Zadej název"):
        save_category(None, CategoryInput(" ", CategoryKind.INCOME, 0, True))
    delete_category(own)
    assert not Category.objects.filter(pk=own.pk).exists()


def test_used_category_keeps_kind_and_cannot_be_deleted(bank: Account, flat: Property) -> None:
    own = Category.objects.create(name="Parkování", kind=CategoryKind.INCOME)
    entry = add(EntryKind.INCOME, 100, bank, code=CategoryCode.RENT, prop=flat)
    entry.category = own
    entry.save()
    with pytest.raises(ValidationError, match="druh nejde"):
        save_category(own, CategoryInput("Parkování", CategoryKind.EXPENSE, 0, True))
    with pytest.raises(ValidationError, match="má pohyby"):
        delete_category(own)
