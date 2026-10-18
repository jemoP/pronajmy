"""Formuláře předpisů plateb dodavatelům (ZM-006)."""

from typing import Any

from django import forms

from apps.money.models import Payable
from apps.rentals.forms import DateInput, StyledForm, StyledModelForm, account_queryset


class PayableForm(StyledModelForm):
    class Meta:
        model = Payable
        fields = [
            "name",
            "supplier",
            "method",
            "account",
            "frequency_months",
            "due_day",
            "valid_from",
            "valid_to",
            "bank_code",
            "variable_symbol",
            "specific_symbol",
            "auto",
            "note",
        ]
        widgets = {
            "valid_from": DateInput(),
            "valid_to": DateInput(),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "valid_from": "Od tohoto měsíce vznikají splátky (čtvrtletní apod. po N měsících).",
            "valid_to": "Prázdné = na dobu neurčitou.",
            "due_day": "Den v měsíci; u kratšího měsíce poslední den.",
            "auto": "Pro trvalý příkaz, inkaso nebo SIPO – náklad vznikne sám v den splatnosti."
            " Bez zaškrtnutí čeká splátka v seznamu K zaplacení.",
            "specific_symbol": "U SIPO spojovací číslo.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = self.instance.account if self.instance.account_id else None
        self.fields["account"].queryset = account_queryset(current)  # type: ignore[attr-defined]

    def clean_due_day(self) -> int:
        day: int = self.cleaned_data["due_day"]
        if not 1 <= day <= 31:
            raise forms.ValidationError("Zadej den 1–31.")
        return day


class PayDuesForm(StyledForm):
    """Zaplacení splátek; označené splátky přichází zvlášť (dues / single)."""

    date_mode = forms.ChoiceField(
        choices=[("due", "podle splatnosti"), ("day", "jedno datum")], initial="due"
    )
    day = forms.DateField(label="Datum", required=False, widget=DateInput())
    note = forms.CharField(label="Poznámka", required=False, max_length=200)

    def clean(self) -> dict[str, Any]:
        super().clean()
        data = self.cleaned_data
        if data.get("date_mode") == "day" and not data.get("day") and "day" not in self.errors:
            self.add_error("day", "Zadej datum platby.")
        return data


class ChangeFromForm(StyledForm):
    day = forms.DateField(label="Změna platí od", widget=DateInput())
