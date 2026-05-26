from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import UserMapSettings


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "username", "autofocus": True}
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "current-password"}
        )
    )


def _coerce_nullable_bool(value: str) -> bool | None:
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "null"}:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


class UserMapSettingsForm(forms.ModelForm):
    popup_close_on_mouseout = forms.TypedChoiceField(
        label="Popup close on mouse out",
        required=False,
        coerce=_coerce_nullable_bool,
        choices=(
            ("", "Use global default"),
            ("true", "Enabled"),
            ("false", "Disabled"),
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = UserMapSettings
        fields = (
            "disable_clustering_at_zoom",
            "marker_limit",
            "status_stale_minutes",
            "popup_close_on_mouseout",
        )
        widgets = {
            "disable_clustering_at_zoom": forms.NumberInput(attrs={"class": "form-control", "min": 2, "max": 18}),
            "marker_limit": forms.NumberInput(attrs={"class": "form-control", "min": 100, "max": 5000}),
            "status_stale_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 1440}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = getattr(self.instance, "popup_close_on_mouseout", None)
        if current is True:
            self.initial["popup_close_on_mouseout"] = "true"
        elif current is False:
            self.initial["popup_close_on_mouseout"] = "false"
        else:
            self.initial["popup_close_on_mouseout"] = ""
        self.fields["disable_clustering_at_zoom"].required = False
        self.fields["marker_limit"].required = False
        self.fields["status_stale_minutes"].required = False

