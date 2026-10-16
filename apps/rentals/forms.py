"""Formuláře pronájmů. Částky se zadávají v Kč („1 234,50“) a ukládají v haléřích."""

from typing import Any

from django import forms
from django.db.models import QuerySet

from apps.core.formatting import format_amount_input, parse_czk
from apps.money.models import Account
from apps.rentals.models import ChargeKind, Lease, LeaseAmendment, LeaseStatus, RentCharge, Tenant


class CzkField(forms.CharField):
    """Částka v Kč → haléře (int)."""

    def __init__(self, *, allow_negative: bool = False, **kwargs: Any) -> None:
        self.allow_negative = allow_negative
        kwargs.setdefault("widget", forms.TextInput(attrs={"inputmode": "decimal"}))
        super().__init__(**kwargs)

    def prepare_value(self, value: Any) -> Any:
        return format_amount_input(value) if isinstance(value, int) else value

    def to_python(self, value: Any) -> int | None:  # type: ignore[override]
        text = super().to_python(value)
        if not text:
            return None
        try:
            return parse_czk(text, allow_negative=self.allow_negative)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(format="%Y-%m-%d", **kwargs)


class StyledMixin:
    """Třídy Tailwindu a aria-invalid pro pole s chybou."""

    fields: dict[str, forms.Field]
    errors: Any

    def style(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.DateInput) and not isinstance(widget, DateInput):
                field.widget = widget = DateInput()
            if not isinstance(widget, forms.CheckboxInput | forms.CheckboxSelectMultiple):
                widget.attrs["class"] = "input"

    def mark_invalid(self) -> None:
        for name in self.errors:
            if name in self.fields:
                self.fields[name].widget.attrs["aria-invalid"] = "true"


class StyledModelForm(StyledMixin, forms.ModelForm):  # type: ignore[type-arg]
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.style()

    def full_clean(self) -> None:
        super().full_clean()
        self.mark_invalid()


class StyledForm(StyledMixin, forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.style()

    def full_clean(self) -> None:
        super().full_clean()
        self.mark_invalid()


def account_queryset(current: Account | None = None) -> QuerySet[Account]:
    """Aktivní účty; neaktivní jen pokud je už vybraný."""
    qs = Account.objects.filter(active=True)
    if current is not None:
        qs = qs | Account.objects.filter(pk=current.pk)
    return qs.order_by("name")


class TenantForm(StyledModelForm):
    class Meta:
        model = Tenant
        fields = ["name", "phone", "email", "address", "birth_date", "active", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3}), "birth_date": DateInput()}
        help_texts = {"birth_date": "Nepovinné. Rodné číslo ani číslo dokladu se neukládá."}


def tenant_queryset(keep: list[Tenant]) -> QuerySet[Tenant]:
    return (
        Tenant.objects.filter(active=True) | Tenant.objects.filter(pk__in=[t.pk for t in keep])
    ).order_by("name")


class LeaseForm(StyledModelForm):
    rent_cents = CzkField(label="Nájem (Kč/měsíc)")
    services_cents = CzkField(label="Zálohy na služby (Kč/měsíc)", required=False)
    deposit_cents = CzkField(label="Jistota (Kč)", required=False)
    main_tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        label="Nájemce",
        error_messages={"required": "Vyber nájemce."},
    )
    co_tenants = forms.ModelMultipleChoiceField(
        queryset=Tenant.objects.none(),
        label="Spolunájemci",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Lease
        fields = [
            "number",
            "signed_date",
            "start_date",
            "end_date",
            "rent_cents",
            "services_cents",
            "due_day",
            "deposit_cents",
            "variable_symbol",
            "account",
            "status",
            "charges_from",
            "terminated_on",
            "termination_reason",
            "note",
        ]
        widgets = {
            "signed_date": DateInput(),
            "start_date": DateInput(),
            "end_date": DateInput(),
            "charges_from": DateInput(),
            "terminated_on": DateInput(),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "end_date": "Prázdné = na dobu neurčitou.",
            "charges_from": "Prázdné = od začátku nájmu. U historických smluv datum, od kdy"
            " chceš sledovat předpisy a dluhy; dřív se smlouva jen eviduje.",
            "due_day": "Den v měsíci, do kdy má být nájem zaplacený.",
            "account": "Účet, na který chodí nájem (výchozí pro zápis platby).",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        current = list(self.instance.tenants.all()) if self.instance.pk else []
        tenants = tenant_queryset(current)
        self.fields["main_tenant"].queryset = tenants  # type: ignore[attr-defined]
        self.fields["co_tenants"].queryset = tenants  # type: ignore[attr-defined]
        self.fields["account"].queryset = account_queryset(self.instance.account)  # type: ignore[attr-defined]
        self.fields["status"].choices = LeaseStatus.choices  # type: ignore[attr-defined]
        if self.instance.pk:
            roles = list(self.instance.lease_tenants.select_related("tenant"))
            main = next((lt.tenant for lt in roles if lt.role == "MAIN"), None)
            self.initial.setdefault("main_tenant", main)
            self.initial.setdefault("co_tenants", [lt.tenant for lt in roles if lt.role != "MAIN"])

    def clean_services_cents(self) -> int:
        return self.cleaned_data.get("services_cents") or 0

    def clean_deposit_cents(self) -> int:
        return self.cleaned_data.get("deposit_cents") or 0

    def clean_due_day(self) -> int:
        day: int = self.cleaned_data["due_day"]
        if not 1 <= day <= 31:
            raise forms.ValidationError("Zadej den 1–31.")
        return day

    def clean(self) -> dict[str, Any]:
        super().clean()
        data = self.cleaned_data
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "Konec nájmu nemůže být před jeho začátkem.")
        return data


class AmendmentForm(StyledModelForm):
    rent_cents = CzkField(label="Nový nájem (Kč/měsíc)", required=False)
    services_cents = CzkField(label="Nové zálohy (Kč/měsíc)", required=False)

    class Meta:
        model = LeaseAmendment
        fields = [
            "number",
            "signed_date",
            "effective_date",
            "rent_cents",
            "services_cents",
            "end_date",
            "description",
        ]
        widgets = {
            "signed_date": DateInput(),
            "effective_date": DateInput(),
            "end_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "rent_cents": "Prázdné pole = beze změny.",
            "services_cents": "Prázdné pole = beze změny.",
            "end_date": "Prázdné pole = beze změny.",
        }


class EndLeaseForm(StyledForm):
    terminated_on = forms.DateField(label="Ukončena ke dni", widget=DateInput())
    reason = forms.CharField(label="Důvod ukončení", required=False, max_length=300)
    confirm = forms.BooleanField(
        label="Ukončit i přes nevyrovnané saldo nebo nevypořádanou jistotu", required=False
    )


class PaymentForm(StyledForm):
    day = forms.DateField(label="Datum", widget=DateInput())
    amount = CzkField(label="Nájem a zálohy (Kč)", required=False)
    deposit_amount = CzkField(label="z toho navíc jistota (Kč)", required=False)
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), label="Na účet", error_messages={"required": "Vyber účet."}
    )
    note = forms.CharField(label="Poznámka", required=False, max_length=200)

    def __init__(self, *args: Any, account: Account | None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = account_queryset(account)  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        super().clean()
        data = self.cleaned_data
        if not (data.get("amount") or data.get("deposit_amount")) and not self.errors:
            self.add_error("amount", "Zadej částku.")
        return data


class PayOutForm(StyledForm):
    day = forms.DateField(label="Datum", widget=DateInput())
    amount = CzkField(label="Částka (Kč)")
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), label="Z účtu", error_messages={"required": "Vyber účet."}
    )
    note = forms.CharField(label="Poznámka", required=False, max_length=200)

    def __init__(self, *args: Any, account: Account | None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = account_queryset(account)  # type: ignore[attr-defined]


class OffsetForm(StyledForm):
    day = forms.DateField(label="Datum", widget=DateInput())
    amount = CzkField(label="Započíst (Kč)")
    note = forms.CharField(label="Poznámka", required=False, max_length=200)


class ChargeForm(StyledModelForm):
    """Ruční předpis (vyúčtování, poplatek) nebo úprava automatického (sleva)."""

    amount_cents = CzkField(
        label="Částka (Kč)",
        allow_negative=True,
        help_text="Záporná částka = přeplatek nebo sleva ve prospěch nájemníka.",
    )

    class Meta:
        model = RentCharge
        fields = ["kind", "due_date", "amount_cents", "note"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["kind"].disabled = True
        else:
            self.fields["kind"].choices = [  # type: ignore[attr-defined]
                (ChargeKind.SETTLEMENT.value, "Vyúčtování (nedoplatek / přeplatek)"),
                (ChargeKind.OTHER.value, "Ostatní"),
            ]
