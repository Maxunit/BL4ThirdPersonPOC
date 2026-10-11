# 0.3.9.24 – lokale Validierung

385 Tests: 381 erfolgreich, dieselben 4 bestehenden übersprungen.

Acht neue Tests simulieren das native HUD-Modell, führen aber die tatsächlichen
ADS-Ein-/Ausstiegs-, Equip- und Publikationsanforderungsfunktionen aus:

- Ein verbliebener Equip-POST nach ADS-Wiedereinstieg stellt ein im nativen Body
  verstecktes Modell wieder her; keine zwei weiteren Callbacks nötig.
- ADS-Einstieg nach PRE innerhalb desselben Equip-Body wird von POST übernommen.
- Ein späterer lokaler POST wird auch bei bereits gezähltem Paar verarbeitet.
- Vorübergehend fehlende Waffen-Readiness bleibt Pending und wird nach einer
  beobachteten Readiness-Änderung geprüft.
- Fremde Waffe/Collector, geänderte Kamera, FPS-Route und Native Exit verweigern
  die Veröffentlichung.

Die vier positiven Lifecycle-Fälle scheiterten vor der Korrektur mit .23.
Die Tests setzen das Verstecken des Modells durch den nativen Equip-Body als
simuliertes Ereignis voraus. Sie belegen diese konkrete Fehlerfolge im Python-
Code, nicht, dass genau diese Folge die beobachtete Live-Regression erklärt.

Der vorhandene Loader-Test wurde erweitert: echte Loader-Keybind-/Zoom-/Equip-
Callbacks, native Zustandsfolge, einziger verbleibender Equip-POST, reale
Publikationsdelegation, Rebind-Freigabe und Cleanup. Nur der native Publisher-
Aufruf wird dort durch ein Modell ersetzt. Der Schreibverweigerungs-/AST-Nachweis
gegen direkte ZoomState-Zuweisungen bleibt Teil der bestehenden Tests.

SDKMOD: 104 Dateien, genau ein Root `BL4ThirdPersonPOC`; Archiv-CRC, Python-Syntax
und jeder Payload gegen den Quellstand geprüft.
SHA-256: `567d1862567156359512f39db16a789f1e0ced077c2b71d8072c33e9491d2581`.

Gegen .23 geprüft: ausschließlich `__init__.py`, `pyproject.toml`,
`ads_handoff.py`, `ads_qa_snapshot.py` ändern Paketbytes. Alle übrigen Paketdateien
sind bytegleich. Keine neuen nativen Patches oder SDK-Hooks.

Kein Windows-Spieltest und keine FPS-Messung durchgeführt. Die Korrektur ist
gezielt, aber Live-Readiness, tatsächliche HUD-Zeichnung und der ursprüngliche
Hold-ADS-Wechsel müssen im Spiel geprüft werden.
