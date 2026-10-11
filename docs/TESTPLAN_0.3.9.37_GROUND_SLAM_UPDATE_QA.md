# 0.3.9.37 – Spieltest

Spiel vollständig schließen, Mod und __pycache__ wie gewohnt ersetzen.
Keine Ground-Slam-Distanzprobe zusätzlich starten.

1. TPS an, TPS Ground Slam an, CAMERA → Ground Slam Extra Distance = 150 cm.
   Auf normalem Boden starten und einen längeren Slam ausführen: sichtbar
   herauszoomen, oben halten, bei Annäherung vor dem Aufschlag zurückfahren.
2. Danach einen kurzen Slam prüfen. Mit Distanz 0 und anschließend 150 cm
   wiederholen. Aus-/Anschalten muss ohne Mod-Neustart funktionieren.
3. Root-Höhenkorrektur und Motion jeweils aus/an gegenprüfen. Charakter zur
   Kamera drehen und Slam ausführen: Oberkörperkorrektur aus .36 mitprüfen.

Wenn kein Zoom zu sehen ist, F10 einmal im normalen TPS drücken und Session-
Log senden. Die Zeile `[BL4ThirdPersonPOC.SlamDistance]` enthält jetzt Zustand,
Abstand, Bodenkanal und Zeitdeltaquelle. Bei einem aktiven F10-Capture ist die
zusätzliche Statuszeile ebenfalls vorhanden, bevor die gewohnte Aktion läuft.
