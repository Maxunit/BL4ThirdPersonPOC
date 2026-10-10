# 0.3.9.20 – Hybrid QA

## Verhalten

- Hybrid-TPS-ADS folgt dem nativen optischen Waffenzoom und dem bestehenden
  globalen oder eigenen Kategorie-Multiplikator. Der zusätzliche 1,35×-Deckel
  wurde aus ADS-Start, Waffenwechsel und laufendem Einstellungswechsel entfernt.
- FPS-ADS → Waffenwechsel → TPS-ADS bei gehaltenem ADS: Ein auf Controller,
  Pawn, Kamera, Waffe und Collector gebundener Auftrag kann den Abschluss am
  aktiven Waffen-/Zoomzustand und an der erfolgreichen nativen Look-Übernahme
  erkennen. Er wartet nicht ausschließlich auf bereits vergangene Equip-Callbacks.
- Die Sperre bleibt bei laufendem Blend, Equipping/PuttingDown, Zoom-loser Waffe,
  anderen Identitäten, aktiven Latches, Spezialzuständen oder Native-Failure zu.
  Native-Aktivierung bleibt mit ihren bisherigen Build-/Byte-/Stack-/Owner-Guards
  geschützt. Nach Native-Failure kein Wiederholen pro Frame.
- Der zustandsbasierte Abschluss liefert auch der bestehenden Wiederherstellung
  nativer Zoom-Modifier einen eigenen Identitätsnachweis. Keine gefälschten
  Callback-Zähler und keine neuen Zoom-Latch-Writes.
- Der alte Konsolenbefehl `hybrid zoom <x>` verweist auf ADS ZOOM; er setzt
  keinen separaten Deckel mehr. Status zeigt `zoom_source=ads_zoom_settings`.
- F10-ADS-Snapshot enthält Zoom-Multiplikator und den Abschlussnachweis.

## Bedienung und Umfang

Hybrid bleibt optional, Standard aus. Alle Kategorien beginnen im Hybrid mit
TPS-ADS, einschließlich Sniper; Sprint gemäß Spielbelegung toggelt FPS-ADS.
Ein Waffenwechsel setzt FPS-ADS weiterhin auf TPS-ADS zurück. Die reguläre
Sniper-ADS-Option gilt bei Hybrid aus. Die Optionsbeschreibung erklärt dies.
Die Optimierungen, Fahrzeugkorrekturen und nativen Templates aus .19 bleiben.
Keine neuen Timer, physischen Eingaben oder Patchstellen.

Es ist eine lokale QA-Korrektur, noch keine Bestätigung des Windows-Spieltests.
