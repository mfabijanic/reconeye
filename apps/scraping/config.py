from __future__ import annotations

from django.conf import settings

# Complete list of countries available on Insecam, sorted by camera count.
# Source: http://www.insecam.org/en/jsoncountries/ (fetched 2026-05-26)
# To override, set INSECAM_COUNTRY_CODES in .env
DEFAULT_INSECAM_COUNTRY_CODES: tuple[str, ...] = (
    "US",  # United States (490)
    "JP",  # Japan (345)
    "IT",  # Italy (125)
    "DE",  # Germany (114)
    "RU",  # Russian Federation (73)
    "AT",  # Austria (66)
    "CZ",  # Czech Republic (55)
    "FR",  # France (53)
    "KR",  # Korea, Republic Of (43)
    "CH",  # Switzerland (34)
    "NO",  # Norway (33)
    "RO",  # Romania (32)
    "TW",  # Taiwan, Province Of (28)
    "CA",  # Canada (23)
    "ES",  # Spain (21)
    "SE",  # Sweden (20)
    "NL",  # Netherlands (20)
    "PL",  # Poland (18)
    "GB",  # United Kingdom (16)
    "UA",  # Ukraine (12)
    "RS",  # Serbia (12)
    "BG",  # Bulgaria (11)
    "DK",  # Denmark (10)
    "IN",  # India (9)
    "SK",  # Slovakia (9)
    "FI",  # Finland (9)
    "BE",  # Belgium (9)
    "HU",  # Hungary (6)
    "ZA",  # South Africa (6)
    "TR",  # Turkey (5)
    "GR",  # Greece (5)
    "BA",  # Bosnia And Herzegovina (5)
    "TH",  # Thailand (5)
    "BR",  # Brazil (4)
    "EG",  # Egypt (4)
    "NZ",  # New Zealand (4)
    "IE",  # Ireland (4)
    "AU",  # Australia (3)
    "ID",  # Indonesia (3)
    "CL",  # Chile (3)
    "AR",  # Argentina (3)
    "CN",  # China (3)
    "LT",  # Lithuania (3)
    "SI",  # Slovenia (2)
    "MX",  # Mexico (2)
    "KZ",  # Kazakhstan (2)
    "MD",  # Moldova, Republic Of (2)
    "EE",  # Estonia (2)
    "VN",  # Viet Nam (2)
    "FO",  # Faroe Islands (2)
    "HN",  # Honduras (2)
    "HK",  # Hong Kong (2)
    "IL",  # Israel (2)
    "BY",  # Belarus (2)
    "PE",  # Peru (1)
    "GU",  # Guam (1)
    "PA",  # Panama (1)
    "BD",  # Bangladesh (1)
    "AM",  # Armenia (1)
    "SG",  # Singapore (1)
    "NI",  # Nicaragua (1)
    "CO",  # Colombia (1)
    "-",   # Unknown / unresolved geolocation (7)
)


def get_insecam_country_codes() -> list[str]:
    configured = getattr(settings, "INSECAM_COUNTRY_CODES", DEFAULT_INSECAM_COUNTRY_CODES)
    seen: set[str] = set()
    result: list[str] = []
    for code in configured:
        normalized = str(code).strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result  # preserves order (popularity-sorted by default)


# Human-readable names for display in the UI
_COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "JP": "Japan", "IT": "Italy", "DE": "Germany",
    "RU": "Russia", "AT": "Austria", "CZ": "Czech Republic", "FR": "France",
    "KR": "South Korea", "CH": "Switzerland", "NO": "Norway", "RO": "Romania",
    "TW": "Taiwan", "CA": "Canada", "ES": "Spain", "SE": "Sweden",
    "NL": "Netherlands", "PL": "Poland", "GB": "United Kingdom", "UA": "Ukraine",
    "RS": "Serbia", "BG": "Bulgaria", "DK": "Denmark", "IN": "India",
    "SK": "Slovakia", "FI": "Finland", "BE": "Belgium", "HU": "Hungary",
    "ZA": "South Africa", "TR": "Turkey", "GR": "Greece", "BA": "Bosnia",
    "TH": "Thailand", "BR": "Brazil", "EG": "Egypt", "NZ": "New Zealand",
    "IE": "Ireland", "AU": "Australia", "ID": "Indonesia", "CL": "Chile",
    "AR": "Argentina", "CN": "China", "LT": "Lithuania", "SI": "Slovenia",
    "MX": "Mexico", "KZ": "Kazakhstan", "MD": "Moldova", "EE": "Estonia",
    "VN": "Vietnam", "FO": "Faroe Islands", "HN": "Honduras", "HK": "Hong Kong",
    "IL": "Israel", "BY": "Belarus", "PE": "Peru", "GU": "Guam",
    "PA": "Panama", "BD": "Bangladesh", "AM": "Armenia", "SG": "Singapore",
    "NI": "Nicaragua", "CO": "Colombia", "-": "Unknown",
}


def get_insecam_countries_with_labels() -> list[tuple[str, str]]:
    """Return list of (code, label) tuples for dropdown display."""
    return [
        (code, _COUNTRY_NAMES.get(code, code))
        for code in get_insecam_country_codes()
    ]


def is_allowed_insecam_country(code: str) -> bool:
    return code.strip().upper() in set(get_insecam_country_codes())
