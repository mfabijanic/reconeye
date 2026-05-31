from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from .models import User, UserMapSettings


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


class UserMapSettingsForm(forms.ModelForm):
    popup_close_on_mouseout = forms.ChoiceField(
        label=_("Popup close on mouse out"),
        required=False,
        choices=(
            ("", _("Use global default")),
            ("true", _("Enabled")),
            ("false", _("Disabled")),
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
            self.fields["popup_close_on_mouseout"].initial = "true"
        elif current is False:
            self.fields["popup_close_on_mouseout"].initial = "false"
        else:
            self.fields["popup_close_on_mouseout"].initial = ""
        self.fields["disable_clustering_at_zoom"].required = False
        self.fields["marker_limit"].required = False
        self.fields["status_stale_minutes"].required = False


    def save(self, commit=True):
        instance = super().save(commit=False)
        # Convert string choice to boolean value
        value = self.cleaned_data.get("popup_close_on_mouseout")
        if value == "true":
            instance.popup_close_on_mouseout = True
        elif value == "false":
            instance.popup_close_on_mouseout = False
        else:
            instance.popup_close_on_mouseout = None
        if commit:
            instance.save()
        return instance

class UserPreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("preferred_language",)
        widgets = {
            "preferred_language": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "preferred_language": _("Interface language"),
        }

