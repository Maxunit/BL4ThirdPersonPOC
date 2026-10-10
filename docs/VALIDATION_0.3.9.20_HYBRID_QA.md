# 0.3.9.20 Hybrid QA – lokale Validierung

- SDKMOD gebaut: 102 Dateien, genau ein Root `BL4ThirdPersonPOC`.
- Unit-/Regression-Suite: 345 Tests, erfolgreich; 4 bestehende Tests übersprungen.
  Die Loader-/SDKMOD-Szenarien laufen innerhalb dieser Suite.
- 14 gezielte neue Tests: tatsächliche Python-ADS-Migration, Callback-Paar vor
  oder nach Migration, wiederholte Wechsel bei gehaltenem ADS, laufende Blends,
  Kamera-/Waffen-/Collector-Abweichungen, Spezialzustände, nativer Fehler,
  fehlende Look-Übernahme, überschriebenes Ticket, Cleanup und Zoom-Einstellungen.
- Zoomprüfung: nativer Waffenzoom, globaler Multiplikator, eigener Kategorie-Wert,
  Einstellungsänderung während ADS; bestehende FOV-Rückweg-Tests weiterhin erfolgreich.
- Native Aktivierungs-/Restore-Implementierung, Modifier-Initializer/Byte-Guards,
  native Patch-Templates sowie alle Omni-/Fahrzeugmodule identisch zur .19-Basis.
- Alle Python-Dateien des Gameplay-Pakets parsebar. Archiv- und Payload-Abgleich
  werden nach finaler Paketierung geprüft.

Umgebung: Linux, SDK-Objekte und ausführbare Windows-Native-Blätter substituiert.
Die Prüfungen belegen Python-Zustandslogik und lokale Verdrahtung, nicht das
visuelle Verhalten von Scope/HUD/Kamera oder native Ausführung im Spiel.
Der gezielte Windows-Spieltest folgt gemäß TESTPLAN_0.3.9.20_HYBRID_QA.md.
