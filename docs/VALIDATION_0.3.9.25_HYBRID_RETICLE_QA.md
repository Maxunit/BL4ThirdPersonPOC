# 0.3.9.25 – lokale Validierung

397 Tests ausgeführt: 393 erfolgreich, 4 bestehende übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.

12 neue Tests führen den tatsächlichen Reticle-Reader/Writer und Hybrid-
Einstieg über simuliertes Prozessmemory aus. WinAPI, immutable Codehashes und
SDK-Objekte sind Test-Doubles; es wird kein Windows-Spielprozess angesprochen.

- Sichtbares Modell wird bei Hold und Toggle genau am erfolgreichen Scope-
  Einstieg versteckt. Nur Visibility und Änderungszähler werden geschrieben.
- Bereits verstecktes Modell erzeugt keinen Write.
- Ausgehender Kameramodus während eines laufenden Blends wird unterstützt.
- Fremde Identität, ungültiger Zoom, Sonderzustand, Hybrid aus und FPS ohne
  aktiven Hybrid-Scope verweigern den Write.
- Unpassender Modelltext/Scope-Flag und zwischenzeitliche Identitätsänderungen
  verweigern den Write.
- Fehlgeschlagener Counter-Write repariert unter passender Identität den
  vorherigen Sichtbarkeitszustand; Native-Byte-Mismatch sperrt Initialisierung.
- TPS-Rückkehr kann den aktuellen validierten Modellzustand wieder publizieren.
- Kamera-Fehler und Refusal verstecken kein Modell. Der echte Rückweg publiziert
  einmal nach Ende des beobachteten Blends.

Regression-Nachweis: Derselbe Hold-/Toggle-Test mit dem originalen .24-
`hybrid_ads.py` scheitert in beiden Fällen mit Visibility 1 statt 0. Die restliche
Reader/Writer-Testumgebung war dabei identisch. Danach wurde der .25-Pfad
bytegenau wiederhergestellt.

Der Loader-Smoke-Test importiert die echte Mod, führt die ADS-/Equip-Dispatches
und die neue Hide-Wrapper-Verdrahtung mit substituiertem nativen Publisher aus.
Die vorhandenen .24-Equip-/Hold-Tests bestehen weiterhin.

Das ist kein Nachweis nativer HUD-Darstellung. Hybrid-FPS-ADS, native Scope-
Overlays und der TPS-Rückweg sind im Spieltest noch offen.
