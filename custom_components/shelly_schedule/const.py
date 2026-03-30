"""Constants for the Shelly Schedule integration.

Defines domain name, configuration keys, schedule day mappings,
and shared utility functions used across all platform modules.
"""

DOMAIN = "shelly_schedule"

# Interval in seconds between automatic sensor refreshes
SCAN_INTERVAL_SECONDS = 300

# Config entry option keys for per-device credential overrides
CONF_GEN2_PASSWORD = "gen2_password"      # Gen2/Gen3: Digest-Auth password
CONF_GEN1_USERNAME = "gen1_username"      # Gen1: Basic-Auth username
CONF_GEN1_PASSWORD = "gen1_password"      # Gen1: Basic-Auth password
CONF_DEVICE_CREDENTIALS = "device_credentials"  # Top-level key in options dict

# Mapping from UI weekday labels to Shelly cron day strings
TAGE_MAP = {
    "Täglich": "*",
    "Werktags (Mo-Fr)": "MON,TUE,WED,THU,FRI",
    "Wochenende (Sa-So)": "SAT,SUN",
    "Montag": "MON",
    "Dienstag": "TUE",
    "Mittwoch": "WED",
    "Donnerstag": "THU",
    "Freitag": "FRI",
    "Samstag": "SAT",
    "Sonntag": "SUN",
}

TAGE_OPTIONS = list(TAGE_MAP.keys())
AKTION_OPTIONS = ["Einschalten", "Ausschalten", "Öffnen", "Schließen", "Stoppen", "Position"]


def device_name_to_slug(name: str) -> str:
    """Convert a device display name to a clean slug (alphanumeric + underscore)."""
    slug = name.lower().replace(" ", "_").replace("-", "_")
    return "".join(c for c in slug if ("a" <= c <= "z") or ("0" <= c <= "9") or c == "_")
