from django.db import migrations


def create_surveillance_profile(apps, schema_editor):
    """Create the default 'surveillance' grid profile if it doesn't exist."""
    Go2RTCGridProfile = apps.get_model("cameras", "Go2RTCGridProfile")
    Go2RTCGridProfile.objects.get_or_create(
        name="surveillance",
        defaults={
            "description": "Private surveillance grid (system default)",
            "is_active": True,
        },
    )


def remove_surveillance_profile(apps, schema_editor):
    """Reverse: remove the surveillance profile (if manually created)."""
    Go2RTCGridProfile = apps.get_model("cameras", "Go2RTCGridProfile")
    Go2RTCGridProfile.objects.filter(name="surveillance").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0014_go2rtcinstance_is_private"),
    ]

    operations = [
        migrations.RunPython(create_surveillance_profile, remove_surveillance_profile),
    ]
