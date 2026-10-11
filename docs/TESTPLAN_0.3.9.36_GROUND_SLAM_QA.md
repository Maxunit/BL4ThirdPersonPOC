# 0.3.9.36 – kurzer Spieltest

Alte Distanzprobe beenden, Spiel vollständig schließen und wie gewohnt die
Mod-Dateien inklusive __pycache__ ersetzen. Nur BL4ThirdPersonPOC installieren;
die archivierten Proben müssen nicht gestartet werden.

1. TPS und Omni aktivieren. Kamera hinter, seitlich und vor die Figur drehen.
   Jeweils kurzen und langen Ground Slam ausführen. Besonders die Vorderansicht
   mit geneigter Kamera prüfen: Oberkörper, Arme und Slam-Pose sollen ihren
   nativen Ablauf behalten, einschließlich Aufschlag und Ausklang.
2. Nach dem Slam freies Umschauen: seitliches Mitdrehen bis zur bisherigen
   Grenze, weiche Neutralisierung bei weiterem Umlauf und Pitch nur von hinten.
   Normale Sprünge und Luft-Dashes separat gegenprüfen.
3. CAMERA → Ground Slam Extra Distance: Standard 150 cm. Langer Slam soll
   herauszoomen, oben halten und vor dem Aufschlag weich zurückfahren. Kurzer
   Slam darf weniger herauszoomen. Kein Ruck beim Eintritt in GroundSlamExit
   oder bei der späteren Rückkehr in TPS.
4. Distanz 0, 150 und 250 sowie Omni aus/an und Motion aus/an prüfen. Distanz
   soll auch ohne Omni und bei ausgeschalteter Grounded Body Height wirken.
   CAMERA-Reset stellt 150 wieder her; ADS-Reset verändert den Distanzwert nicht.
5. Zwei Slams hintereinander, schräge Böden und Kanten testen. Danach ADS,
   FPS/TPS-Wechsel, Fahrzeug und Save-Load/Kartenwechsel: kein Restabstand.
   Geländer-/Root-Höhenkorrektur und das zusätzliche Landeeindruck weiterhin
   gegenprüfen.

Zunächst reichen Rückmeldung zur Vorderansicht und ein langer Slam mit 150 cm.
Bei Fehlern Session-Log mit der genauen Situation sichern; keine neue Probe
zusätzlich zur integrierten Funktion laufen lassen.
