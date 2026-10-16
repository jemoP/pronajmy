"""Formulář pohybu – jen převod vstupu; pravidla hlídá služba."""

from django import forms

from apps.core.formatting import parse_czk
from apps.money.models import EntryKind
from apps.money.services.entries import EntryInput

FIELDS = (
    "date",
    "kind",
    "amount",
    "account_id",
    "to_account_id",
    "category_id",
    "property_id",
    "note",
)


class EntryForm(forms.Form):
    date = forms.DateField(error_messages={"required": "Zadej datum.", "invalid": "Zadej datum."})
    kind = forms.ChoiceField(
        choices=EntryKind.choices,
        error_messages={"required": "Vyber druh pohybu.", "invalid_choice": "Vyber druh pohybu."},
    )
    amount = forms.CharField(error_messages={"required": "Zadej částku ve tvaru 1 234,50."})
    account_id = forms.IntegerField(required=False)
    to_account_id = forms.IntegerField(required=False)
    category_id = forms.IntegerField(required=False)
    property_id = forms.IntegerField(required=False)
    note = forms.CharField(required=False, max_length=500)

    def clean_amount(self) -> int:
        try:
            return parse_czk(self.cleaned_data["amount"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def to_input(self) -> EntryInput:
        data = self.cleaned_data
        return EntryInput(
            date=data["date"],
            kind=data["kind"],
            amount_cents=data["amount"],
            account_id=data["account_id"],
            to_account_id=data["to_account_id"],
            category_id=data["category_id"],
            property_id=data["property_id"],
            note=data["note"],
        )
