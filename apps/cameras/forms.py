from __future__ import annotations

from django import forms


class Go2RTCCameraForm(forms.Form):
    stream_name = forms.CharField(
        max_length=255,
        label="Stream name",
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "e.g. front_door"}),
    )
    title = forms.CharField(
        required=False,
        max_length=255,
        label="Display title",
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Optional display title"}),
    )


class Go2RTCInstanceForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        label="Instance name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. HQ NVR"}),
    )
    scheme = forms.ChoiceField(
        choices=(("http", "http"), ("https", "https")),
        initial="http",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    host = forms.CharField(
        max_length=255,
        label="Host",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "127.0.0.1"}),
    )
    port = forms.IntegerField(
        min_value=1,
        max_value=65535,
        initial=1984,
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "1984"}),
    )


class Go2RTCBulkAddForm(forms.Form):
    stream_names = forms.MultipleChoiceField(
        required=True,
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, stream_choices: list[tuple[str, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stream_names"].choices = stream_choices or []
