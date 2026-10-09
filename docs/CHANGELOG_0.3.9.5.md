# BL4ThirdPersonPOC 0.3.9.5 – Messrunde für die einheitliche Rear-Blocker-Korrektur

Basis ist 0.3.9.4 (im Spiel bestätigt). **Keine Änderung am Spielverhalten.** Diese Version bringt nur zwei Konsolenbefehle, die ausschließlich lesen. Testplan: `TESTPLAN_0.3.9.5.md`.

## Ausgangslage
- **Problem:** Steht ein Gegner oder Objekt dicht hinter der Figur, also zwischen Kamera und Figur, fliegen Projektile nach hinten, oder die Kamera dreht sich weg. Das passiert mit Maus und mit Gamepad.
- **Warum der Beam-Fix nicht greift:** Der vorhandene Beam-Fix (`native_beam_rear_blocker.py` und `native_beam_collision.py`) sitzt in Code, den nur Beam-Waffen ausführen:
  - Capture-Site `0xA65AF1` in der Beam-Kollisionsabfrage (Sweep mit Radius 20)
  - Receiver-Modus 5
  - Identität `FireBeam`-Slot `0x410 = 0x4344586`
  - Projektil- und Hitscan-Waffen erreichen diese Stelle nie.
- **Entscheidung:** native Ziel-Korrektur wie beim Beam (Weg A), also unsichtbar für den Spieler. Dafür muss erst der Zielpfad dieser Waffen gefunden werden.

## Neu
- **`bl4tps_weapon_probe`** misst die ausgerüstete Waffe und schreibt `weapon_probe_<Klasse>_<Zeit>.json` nach `sdk_mods/settings/BL4ThirdPersonPOC_reports/`. Die neuesten 12 Dateien bleiben erhalten. Der Report enthält:
  - die Use-Mode-Tabelle und alle Behaviors der Waffe mit Klasse und Vtable;
  - für das aktive Feuer-Behavior die überschriebenen Vtable-Slots, also die Slots, die es mit keinem anderen Behavior der Waffe teilt, und `0x410`;
  - Unterobjekte wie Receiver und Targeting mit ihren Slots. Die Beam-Receiver-Slots `0x300`, `0x308` und `0x368` werden mitgelesen;
  - eine begrenzte statische Code-Ernte ab diesen Einstiegen: höchstens 360 Funktionen, Tiefe 3, je 0x700 Bytes;
  - Marker für Lesezugriffe auf den Kamera-Cache (`Manager +0x1910`, gemessen über die Beam-Guards) und Aufrufe des bekannten Beam-Query-Helfers `0x38F90E`.
- **`bl4tps_native_dump <rva> [<rva> …] [--length 0x800]`** liest bis zu 32 Codefenster mit je höchstens 0x4000 Bytes. Damit kann ich in den nächsten Runden gezielt nachfordern, ohne dass ein neuer Build nötig ist.

## Sicherheit
- Beide Befehle nutzen ausschließlich `ReadProcessMemory`. Es gibt keine Schreibzugriffe, keine Hooks und keine Patches. Ein Test prüft das am Quelltext.
- Ein anderer Build als `steam-2026-09-14` wird vor jedem Code-Lesezugriff abgelehnt.
- Codefenster bleiben innerhalb der ausführbaren Sektionen des Spiels.

## Tests
- 129 Python-Tests, davon 9 neu, mit einem synthetischen Speicherabbild. Geprüft wird:
  - der Projektilpfad mit Override-Slots, Receiver-Slot und Marken;
  - die Ablehnung fremder Builds ohne Code-Lesezugriff;
  - die Budgetgrenze;
  - dass lokale Sprünge nicht verfolgt werden;
  - Dateiname und Aufräumen der Reports;
  - die Grenzen des Dumps;
  - die Befehlsregistrierung.
- Im Loader-Harness enden beide Befehle sauber mit Fehlermeldung, wenn kein Spiel oder keine Waffe da ist.
