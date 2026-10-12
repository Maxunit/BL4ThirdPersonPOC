# 0.3.9.41 – Spieltest

Spiel vollständig beenden, alte Mod und __pycache__ entfernen, .41 installieren.
Omni aktiv, normales TPS ohne ADS, Ground Slam Extra Distance 150 cm.

1. Bekannter 180°-Fall: Kamera gegenüber der Figur, langer Slam. Heading in der
   Luft muss erhalten bleiben. Beim Exit prüfen: kein schnelles Oberkörper-
   Zucken UND komplette Slam-/Exit-Bewegung weiterhin sichtbar.
2. Kamera 30–45° aus dieser Position herausdrehen, Figurenrichtung behalten;
   langen und kurzen Slam wiederholen. Kameraabstand vor Aufschlag, Grounded-
   Body-Height und das akzeptierte Exit-„oomph“ prüfen.
3. Nach Ende normales Laufen, Sprung, Sprint, freies Umschauen und ggf. zügig
   einen zweiten Slam testen. Native Pose außerhalb des eigenen Slams/Exit-
   Blends muss wieder von regulärem Omni übernommen werden.
4. Omni aus, ADS/TPS↔FPS und Mod-Abschaltung kurz gegenprüfen.

Bitte getrennt berichten, ob Zucken und vollständige Pose korrekt sind. Ein
ruhiger aber unvollständiger Oberkörper ist kein erfolgreicher Fix.

Bei Fehlern enthält probes/ground_slam_idle_inputs_capture.py jetzt .40/.41-
Unterstützung und zusätzliche begrenzte native Scalar-Beobachtung für den exakt
geprüften IdleTurns-Code. Aktuelle Datei nach sdk_mods kopieren, pyexec starten,
Konsole schließen, einen Slam erfassen, bis ruhige TPS warten, F10. JSON/ZIP aus
settings/BL4ThirdPersonPOC_reports senden. Erwartete freie Gates: Luft
(1,1,0,0,0,0), Exit/eigene Rückkehr (1,1,1,1,0,0). Nicht die alte .40-only-Kopie
verwenden. Die Probe verändert keine Spiel-/Animationsvorgaben.
