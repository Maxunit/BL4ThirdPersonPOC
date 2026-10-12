# 0.3.9.39 – Spieltest

Spiel vollständig beenden, alte Mod und __pycache__ entfernen, .39 installieren.
Omni einschalten, normale TPS ohne ADS. Ground Slam Extra Distance: 150 cm.

1. Kamera Norden, Figur Süden: langer Slam aus der bekannten Höhe. Die Figur
   soll ihre Richtung durch Flug, Aufschlag und Kamerarückkehr behalten.
   Die komplette Oberkörper-/Exit-Animation soll ohne Zittern laufen.
2. Wiederholen mit seitlicher Kamera sowie Blick hinter die Figur. Auch einen
   kurzen Slam testen. Distanz soll weiterhin vor dem Aufschlag zurückfahren;
   die angenommene Root-Höhenkorrektur und ihr Exit-„oomph“ sollen bestehen.
3. Während eines weiteren Slams die Kamera drehen. Nach Ende wieder gehen,
   springen, sprinten und die Kamera frei drehen. Die normale Omni-Ausrichtung
   und begrenzte Oberkörperbewegung sollen wieder übernehmen.
4. Omni aus: gewöhnlicher nativer Slam. TPS/FPS, ADS, Fahrzeug-Ein-/Ausstieg und
   Mod-Abschaltung kurz gegenprüfen; keine festgehaltene Sonderzustandsrichtung.

Bei Fehlern: Phase (Start / Flug / Aufschlag / TPS-Rückkehr), Kamera-/Figuren-
Richtung und sichtbaren Effekt beschreiben. Die enthaltene Facing-Probe kann
jetzt .39 aufzeichnen: `pyexec ground_slam_facing_capture.py`, Konsole schließen,
Slam durchführen, F10. Datei aus `settings/BL4ThirdPersonPOC_reports` senden.
Während eines freien Slams sollten Turn/TurnReplace = 1/1 und die vier
Idle-/Aim-Gates = 0/0/0/0 sein. Die alte Rotation-Probe ist nur für .38.

Lokale Tests können nicht bestätigen, ob native Animation/Root-Evaluation mit
gehaltenem Actor-Yaw sichtbar ruhig bleibt. Genau das ist Zweck dieser QA.
