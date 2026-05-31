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
