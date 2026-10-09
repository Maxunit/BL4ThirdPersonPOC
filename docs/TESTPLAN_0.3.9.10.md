# Gameplay-Nachtest 0.3.9.10

Spiel vollständig beenden, alte Mod-Dateien und deren Cache entfernen, neue
`BL4ThirdPersonPOC`-Mod installieren. Die einzelnen Handoff-QA-Proben nicht starten:
die geprüfte Logik ist jetzt Teil der Mod. Omni für diese Tests aktivieren.

1. Normale Schusswaffe: aus seitlichem/rückwärtigem Sprint feuern; gedrückt
   halten und kurz antippen. Danach weiter sprinten.
2. Leeres Magazin: aus dem Sprint feuern, loslassen und weiter sprinten.
3. Geprüfte Charge-Assault-Rifle: aus dem Sprint vollständig aufladen und feuern;
   außerdem während des Aufladens vor dem ersten Schuss loslassen.
4. Waffenwechsel, Nachladen, TPS/FPS-Wechsel, Fahrzeug und Save-Load prüfen.
5. Throwable ausrüsten; fehlendes Zoom-Mapping darf Omni nicht abschalten.
6. `bl4tps_aim status`: nach frischem Start Margin 70; beide Schultern, ADS,
   Wandkante und sehr nahe Ziele prüfen.

Bei Auffälligkeiten Session-Log und `bl4tps_omni report` sichern. Unbekannte
Feuerverhalten sind im Report als nicht unterstützt markiert; sie benötigen
eigene native Messungen, bevor derselbe Handoff erweitert werden kann.
