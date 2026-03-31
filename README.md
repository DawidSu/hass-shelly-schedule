# Shelly Schedule

Home Assistant Custom Integration zum Konfigurieren von Aufgaben (Zeitplänen) direkt auf Shelly-Geräten — ohne die Shelly-App, direkt aus der HA-Oberfläche.

Wenn dir die Integration gefällt, freue ich mich über eine Spende: [![PayPal](https://img.shields.io/badge/PayPal-Spende-blue?logo=paypal)](https://www.paypal.com/paypalme/dawidSuchy)

Unterstützt **Gen2/Gen3** (Digest-Auth, RPC-API) und **Gen1** (Basic-Auth) Geräte.

## Zweck

Shelly-Geräte bieten eine eingebaute Zeitplanfunktion, mit der Aktionen (Ein/Aus, Öffnen/Schließen) zu bestimmten Uhrzeiten oder bei Sonnenauf-/-untergang ausgeführt werden können. Diese Integration ermöglicht es, diese Aufgaben direkt aus Home Assistant heraus zu verwalten — ohne die Shelly-App oder das Web-Interface jedes Geräts manuell aufzurufen.

## Features

- Automatische Geräteerkennung und Zugangsdaten aus der bestehenden Shelly-Integration
- Automatische Profilerkennung (Switch / Cover) pro Gerät
- Aufgaben anzeigen, erstellen, bearbeiten, aktivieren/deaktivieren und löschen
- Toggle-Switch zum schnellen Aktivieren/Deaktivieren einzelner Aufgaben
- Unterstützung für feste Uhrzeiten sowie Sonnenauf-/-untergang mit Offset
- Wochentag-Auswahl per Checkboxen (Mo Di Mi Do Fr Sa So)
- Aktionsauswahl gefiltert nach Geräteprofil (Ein/Aus für Switches, Öffnen/Schließen/Stoppen/Position für Cover)
- Web-UI-Link mit automatischem Passwort in die Zwischenablage
- Zwei native Lovelace-Karten — keine Drittanbieter-Karten nötig:
  - `shelly-schedule-card` — Entität per Editor konfiguriert
  - `shelly-schedule-card-inline` — Entitätsauswahl direkt in der Karte
- Periodische Aktualisierung alle 5 Minuten

## Voraussetzungen

- Home Assistant 2024.4 oder neuer
- Shelly-Integration in HA eingerichtet und Geräte konfiguriert

## Getestete Geräte

| Gerät | Generation |
|-------|-----------|
| Shelly Plug S | Gen1 |
| Shelly Plug E | Gen1 |
| Shelly Plus 2PM | Gen2 |
| Shelly Plus Plug S | Gen2 |
| Shelly Plug S Gen3 | Gen3 |
| Shelly 1PM Mini Gen4 | Gen4 |
| Shelly 2PM Gen4 | Gen4 |

## Installation

### Über HACS (empfohlen)

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories
2. URL: `https://github.com/DawidSu/hass-shelly-schedule` → Typ: Integration
3. Integration installieren und HA neu starten
4. Integration unter **Einstellungen → Integrationen → + Integration hinzufügen → Shelly Schedule** einrichten

### Manuell

1. Ordner `custom_components/shelly_schedule` in `/config/custom_components/` kopieren
2. Home Assistant neu starten
3. Integration unter **Einstellungen → Integrationen → + Integration hinzufügen → Shelly Schedule** einrichten

## Einrichtung

Die Integration benötigt **keine manuelle Konfiguration** in `configuration.yaml`. Zugangsdaten und Geräteliste werden automatisch aus der bestehenden Shelly-Integration ausgelesen.

Nach dem Neustart:
- Alle Shelly Gen2/Gen3 und Gen1 Geräte werden automatisch erkannt
- Für jedes Gerät wird ein Sensor `sensor.shelly_<name>_schedule` erstellt und dem jeweiligen Shelly-Gerät in der HA Device Registry zugeordnet
- Das Geräteprofil (Switch/Cover) wird automatisch ermittelt

## Lovelace-Karten

Die Integration bringt zwei eigene Lovelace-Karten mit. Karte hinzufügen:

1. Dashboard bearbeiten → **+ Karte hinzufügen**
2. Kartentyp auswählen (s. u.)

---

### Karte 1: `shelly-schedule-card`

Klassische Variante — die Sensor-Entität wird einmalig im Editor konfiguriert.

```yaml
type: custom:shelly-schedule-card
entity: sensor.shelly_wohnzimmer_licht_schedule
title: Wohnzimmer Licht
```

| Option | Beschreibung | Standard |
|--------|-------------|---------|
| `entity` | Sensor-Entität (`sensor.shelly_*_schedule`) | — |
| `title` | Kartentitel | `Shelly Schedules` |
| `hide_title` | Kartentitel ausblenden | `false` |
| `device_name` | Angezeigter Gerätename (überschreibt automatischen Namen) | — |
| `icon` | Icon (z.B. `mdi:calendar-clock`) | — |
| `color` | Akzentfarbe (Hex) | HA Primärfarbe |
| `device_icon` | Icon neben dem Gerätenamen | — |
| `badge_mode` | Badge-Stil: `id` · `icon` · `none` | `id` |
| `day_display` | Tagesanzeige: `text` · `chips` | `text` |
| `hide_webui` | Web-UI-Link ausblenden | `false` |
| `hide_action` | Aktion ausblenden | `false` |
| `hide_run_button` | Ausführen-Button ausblenden | `false` |

---

### Karte 2: `shelly-schedule-card-inline`

Inline-Variante — die Entitätsauswahl erscheint direkt in der Karte als Dropdown. Kein Editor-Entitätsfeld nötig. Die Auswahl wird im Browser gespeichert und bleibt nach einem Reload erhalten.

```yaml
type: custom:shelly-schedule-card-inline
title: Shelly Schedules
```

Unterstützt dieselben Darstellungsoptionen wie `shelly-schedule-card` (außer `entity` und `device_name`).

Optional: `storage_key` setzen, um mehrere Inline-Karten mit demselben Titel unabhängig voneinander zu halten:

```yaml
type: custom:shelly-schedule-card-inline
title: Shelly Schedules
storage_key: karte-wohnzimmer
```

---

### Kartenansicht (beide Karten)

- **Geräteheader** mit Anzahl der Aufgaben, **Web-UI**-Link (Passwort wird automatisch in die Zwischenablage kopiert) und **+ Neu**-Button
- **Aufgabenliste** mit Uhrzeit bzw. Sonnenauf-/-untergang, Wochentagen, Aktion und Toggle-Switch zum Aktivieren/Deaktivieren
- **Bearbeiten- und Löschen-Buttons** pro Aufgabe
- **Erstellen/Bearbeiten-Dialog** mit Zeittyp (Uhrzeit / Sonnenaufgang / Sonnenuntergang), Offset, Wochentag-Checkboxen, Aktion und Aktiviert-Checkbox
- Bei leerer Liste: **+ Neu**-Button direkt neben „Keine Zeitpläne"

## Verfügbare Services

| Service | Parameter | Beschreibung |
|---------|-----------|-------------|
| `shelly_schedule.reload_devices` | — | Geräteliste neu laden |
| `shelly_schedule.update_sensors` | — | Alle Sensoren aktualisieren |
| `shelly_schedule.create_schedule` | `device`, `timespec`, `enable`, `calls` | Aufgabe erstellen (Gen2/Gen3) |
| `shelly_schedule.delete_schedule` | `device`, `schedule_id` | Aufgabe löschen (Gen2/Gen3) |
| `shelly_schedule.enable_schedule` | `device`, `schedule_id` | Aufgabe aktivieren (Gen2/Gen3) |
| `shelly_schedule.disable_schedule` | `device`, `schedule_id` | Aufgabe deaktivieren (Gen2/Gen3) |
| `shelly_schedule.replace_schedule` | `device`, `schedule_id`, `timespec`, `enable`, `calls` | Aufgabe ersetzen (Gen2/Gen3) |
| `shelly_schedule.gen1_set_schedule` | — | Aufgabe setzen (Gen1) |
| `shelly_schedule.gen1_delete_schedule` | — | Aufgabe löschen (Gen1) |
| `shelly_schedule.gen1_enable_scheduling` | — | Zeitplanung aktivieren (Gen1) |
| `shelly_schedule.gen1_disable_scheduling` | — | Zeitplanung deaktivieren (Gen1) |

### Service-Parameter

- **`device`**: Gerätename aus der HA Device Registry (z.B. `Rollladen Wohnzimmer`)
- **`schedule_id`**: ID der Aufgabe (integer, von Shelly vergeben)
- **`timespec`**: Cron-Format `"0 <min> <stunde> * * <tage>"` (z.B. `"0 30 7 * * MON,TUE,WED,THU,FRI"`) oder Sonnenformat (z.B. `"@sunset-0h30m * * MON,TUE,WED,THU,FRI"`)
- **`enable`**: `true` / `false`
- **`calls`**: Liste von RPC-Aufrufen, z.B. `[{"method": "Switch.Set", "params": {"id": 0, "on": true}}]`

## Sensor-Attribute

Jeder `sensor.shelly_*_schedule` enthält folgende Attribute:

| Attribut | Beschreibung |
|----------|-------------|
| `jobs` | Liste der aktuellen Aufgaben (Gen2/Gen3) |
| `schedule_rules` | Liste der Zeitplanregeln (Gen1) |
| `hostname` | IP-Adresse des Geräts |
| `device_name` | Gerätename (exakter Key für Service-Aufrufe) |
| `device_profile` | `switch` oder `cover` |
| `login_user` | Web-UI Benutzername |
| `login_password` | Web-UI Passwort |
