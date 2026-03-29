DOMAIN = "shelly_schedule"
SCAN_INTERVAL_SECONDS = 300

CONF_GEN2_PASSWORD = "gen2_password"
CONF_GEN1_USERNAME = "gen1_username"
CONF_GEN1_PASSWORD = "gen1_password"
CONF_DEVICE_CREDENTIALS = "device_credentials"

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
