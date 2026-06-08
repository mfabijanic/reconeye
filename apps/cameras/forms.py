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
    path = forms.CharField(
        required=False,
        max_length=255,
        label="Path",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. go2rtc or app/go2rtc"}
        ),
    )
    group_label = forms.CharField(
        required=False,
        max_length=255,
        label="Group / FQDN",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. nvr.example.com (optional)"}
        ),
    )

    def clean_path(self) -> str:
        # Normalize to a clean relative path without leading/trailing slashes
        # and without an accidental full URL or scheme.
        raw = (self.cleaned_data.get("path") or "").strip()
        raw = raw.strip("/")
        return raw


class Go2RTCBulkAddForm(forms.Form):
    profile_id = forms.ChoiceField(
        required=True,
        choices=(),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    stream_names = forms.MultipleChoiceField(
        required=True,
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(
        self,
        *args,
        stream_choices: list[tuple[str, str]] | None = None,
        profile_choices: list[tuple[str, str]] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["stream_names"].choices = stream_choices or []
        self.fields["profile_id"].choices = profile_choices or []


class Go2RTCGridProfileForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        label="Profile name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Public Wall"}),
    )
    description = forms.CharField(
        required=False,
        max_length=255,
        label="Description",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
    )


class Go2RTCImportForm(forms.Form):
    """Upload a CSV file or paste CSV text to import go2rtc instances."""

    # Reject pathological uploads early (CSV instance lists are tiny).
    MAX_FILE_BYTES = 5 * 1024 * 1024

    csv_file = forms.FileField(
        required=False,
        label="CSV file",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".csv,text/csv"}
        ),
    )
    csv_text = forms.CharField(
        required=False,
        label="Or paste CSV",
        widget=forms.Textarea(
            attrs={
                "class": "form-control font-monospace",
                "rows": 6,
                "placeholder": "name,host,scheme,port,path,group_label",
                "spellcheck": "false",
            }
        ),
    )

    def clean_csv_file(self):
        f = self.cleaned_data.get("csv_file")
        if f and f.size and f.size > self.MAX_FILE_BYTES:
            raise forms.ValidationError("CSV file is too large.")
        return f

    def clean(self):
        cleaned = super().clean()
        has_file = bool(cleaned.get("csv_file"))
        has_text = bool((cleaned.get("csv_text") or "").strip())
        if not has_file and not has_text:
            raise forms.ValidationError("Provide a CSV file or paste CSV text.")
        return cleaned

    def get_content(self) -> str | bytes:
        """Return the raw CSV payload (file wins over pasted text)."""
        f = self.cleaned_data.get("csv_file")
        if f:
            return f.read()
        return self.cleaned_data.get("csv_text", "")
