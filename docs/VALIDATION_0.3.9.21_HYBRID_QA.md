# 0.3.9.21 Hybrid QA – lokale Validierung

- 344 Tests erfolgreich, davon 4 bestehende übersprungen; Loader-/SDKMOD-Szenarien
  laufen in dieser Suite. Alle 14 .20-Zoom-/Waffenübergabe-Tests bleiben enthalten.
- Aktualisierte Kameratests: Benutzer-Offsets bleiben über ADS-FOV-Fortschritt,
  ADS-Release und Hybrid-Aus unverändert; ein alter Dolly-Zustand wirkt nicht
  mehr und wird beim Reset entfernt. Konsolen-/Statusprüfung enthält keinen
  Dolly-Setter oder Dolly-Status mehr.
- Bestehende Scope-Offset-/FOV-Überblendung und .15-Rückweg-Tests erfolgreich;
  Rückweg-Ziel nun reguläre TPS-Position statt zusätzlicher +35 cm.
- Die native Übergabe-/Modifier-Korrektur aus .20 und alle Omni-/Fahrzeugmodule
  aus .19 bleiben byte-identisch. Keine neue native Patchstelle.
- SDKMOD: genau ein passender Root, 102 Dateien. Python-Syntax, Archivintegrität
  und exakte Paket-Payload werden bei der finalen Paketierung geprüft.

Linux-Prüfung mit SDK-Objekten und nativen Windows-Blättern als Substitute.
Eine Bestätigung der visuellen Gleichheit im BL4-Spiel folgt erst im Spieltest.
