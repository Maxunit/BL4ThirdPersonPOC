# Lokale Prüfung – 0.3.9.19 Hybrid QA

10.10.2026. Separate Variante der regulären 0.3.9.19 QA.

- Im gesamten Mod-Paket genau eine geänderte Quellzeile gegenüber der regulären
  QA: `HYBRID_ADS_AVAILABLE` von False auf True. Datei- und Asset-Bestand identisch.
- `python -m unittest discover -s tests -v`: 332 Tests erfolgreich, davon 4
  bestehende umgebungsabhängige Tests übersprungen. Der bisherige Hybrid-Loader-Test
  erwartet nun korrekt Off→On→Off statt der Sperre der regulären QA.
- SDKMOD-Lader zusätzlich auf tatsächliche Konsolen-Aktivierung und anschließendes
  Ausschalten geprüft: `hybrid on` setzt True; `hybrid off` setzt False. Bericht
  landet außerhalb des Archivs; nach Mod-Deaktivierung bleiben keine SDK-Hooks.
- SDKMOD-Integrität, passender Stammordner, bytegleiche Übereinstimmung mit den
  Varianten-Quellen und unveränderte übrige Mod-Dateien geprüft.

Die GameThread-/SDK-/Windows-APIs der Tests sind simuliert. Die Aktivierbarkeit ist
lokal geprüft; Zoom- und Scope-Verhalten benötigen den Gameplay-Reproduktionslauf.
Keine Hybrid-Bugfixes in dieser Diagnosevariante. Der ursprüngliche Nachweis für
Performance-/Fahrzeug-Integration steht separat in `VALIDATION_0.3.9.19.md`.
