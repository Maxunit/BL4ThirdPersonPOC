# 0.3.9.40 – Spieltest

Spiel komplett beenden, alte Mod und __pycache__ entfernen, .40 installieren.
Omni aktivieren, normale TPS ohne ADS; Ground Slam Extra Distance 150 cm.

1. Bekannter Gegenrichtungsfall: Kamera Norden, Figur Süden. Einen langen Slam
   durchführen. Luftausrichtung soll wie in .39 korrekt bleiben; beim Aufschlag
   und bis zur ruhigen TPS sollen keine sichtbaren Root-Richtungssprünge mehr
   auftreten. Vollständige Oberkörper-/Slam-/Exit-Animation prüfen.
2. Seitliche und hintere Kameraausrichtung sowie einen kurzen Slam testen.
   Kameraabstand soll vor dem Aufschlag zurückfahren; die Grounded-Body-Height-
   Korrektur und das akzeptierte Exit-„oomph“ sollen erhalten bleiben.
3. Nach dem Exit gehen, springen, sprinten und frei umschauen. Normales Omni
   und die begrenzte Oberkörperbewegung sollen wieder übernehmen. Wenn möglich
   zügig einen zweiten Slam nach dem ersten ausführen.
4. Omni aus sowie ADS/TPS↔FPS und Mod-Abschaltung kurz gegenprüfen.

Bei verbleibendem Fehler bitte Phase und sichtbaren Effekt beschreiben. Die
aktualisierte `probes/ground_slam_exit_capture.py` aus diesem Paket kann .40
aufzeichnen: nach sdk_mods kopieren, `pyexec ground_slam_exit_capture.py`,
Konsole schließen, bekannten Slam durchführen, bis ruhige TPS warten, F10.
JSON aus `settings/BL4ThirdPersonPOC_reports` senden. Der vorher heruntergeladene
.39-only-Scriptstand muss dafür ersetzt werden.

Erwartete freie Slam-Gates: Luft (1,1,0,0,0,0); Exit/eigene Rückkehr (1,1,1,0,0,0).
Der neue Root-Guard ist bewusst keine IdleUpdate- oder Aim-Unterdrückung.
Lokale Tests ersetzen die sichtbare Animationsprüfung nicht.
