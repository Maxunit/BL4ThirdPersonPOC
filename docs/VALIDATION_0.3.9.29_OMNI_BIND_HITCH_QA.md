# 0.3.9.29 – lokale Validierung

461 Tests: 457 erfolgreich, dieselben vier bestehenden übersprungen.
Befehl: `python -m unittest discover -s tests -p 'test_*.py'`.

18 neue Tests (`tests/test_omni_bind_hitch_0_3_9_29.py`):

- Gestaffeltes Binden: genau ein Schritt pro RUN-Update in der früheren
  Reihenfolge, Pipeline erst danach; Pause-Updates laufen unverändert; Fehler
  stoppt mit eigenem Grund ohne Pipeline; Sessions ohne `install()` behalten das
  alte Verhalten.
- Ruckler-Logger: schneller Callback ohne Eintrag; langsamer Callback mit
  sortierten Schritten und Konsolenzeile; Konsolen-Limit bei weiterlaufender
  Zählung; Schritt außerhalb eines Callbacks ist wirkungslos.
- Knochen: Produktion nur `GetBoneIndex` für die fünf Knochen, kein Katalog;
  fehlender Knochen bricht weiter ab; mit Pose-Diagnose voller Katalog.
- Movement-Schema einmal pro Klasse; andere Klasse scannt neu.
- Tastenleser: gleicher Controller und vollständig wird übernommen, sonst
  voller Scan.
- Handler-Prüfung und Kampf-Auswertung einmal pro Callback.
- Granaten-Scan: geladene Klasse per Identität ohne Pfadnamen; nicht geladene
  Klasse über Pfad, ab der ersten Instanz per Identität.

Kostenbudget um Laufen und Laufen mit Kameradrehung erweitert. Angepasst:
Versionsprüfungen, Granaten-Test-Helfer (geteiltes Klassen-Objekt).

Native-Installationen laufen unter Linux nicht; die Kosten des Bindens sind
deshalb nicht gezählt. Zeiten, Ruckler und FPS zeigt erst der Spieltest.
