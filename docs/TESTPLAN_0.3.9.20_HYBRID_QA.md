# 0.3.9.20 Hybrid QA – gezielter Spieltest

1. Alle laufenden Proben stoppen. Spiel beenden, alte Mod und Caches entfernen.
   `BL4ThirdPersonPOC.sdkmod` installieren (bei Download-Zusätzen umbenennen).
   Omni und Hybrid einschalten. Keine früheren PyExec-Proben dazu starten.
2. Globalen ADS-Zoom zunächst auf 1, eigene Kategorie-Werte aus. Mit mindestens
   zwei Waffen unterschiedliche native Zoomstärken prüfen. Global 1,5 testen;
   danach für eine Kategorie einen eigenen Wert setzen und dessen Vorrang prüfen.
   Werte nach dem Test nach Wunsch zurückstellen. FPS-Scope verwendet weiterhin
   den nativen FPS-Pfad; die TPS-Zoom-Optionen gelten für TPS-ADS.
3. ADS halten → konfigurierte Sprint-Taste kurz drücken/loslassen → FPS-ADS →
   Waffe wechseln, ADS weiterhin halten → neue Waffe in TPS-ADS fertig ausrüsten
   lassen → Sprint erneut kurz drücken/loslassen. FPS-ADS muss wieder erreichbar
   sein, ohne ADS loszulassen. Auch Sniper→andere Kategorie und Rückweg testen.
4. Einige Waffenwechsel wiederholen; zusätzlich ADS während Wechsel/Blend
   loslassen. Auf Fadenkreuz, Waffenpose, Kamerarückweg und Omni achten.
5. Nach Eingaben loslassen `bl4tps_omni report` ausführen und JSON senden.
   Bei einem verbleibenden Blocker bitte Mod-Log mit `HELD_ADS_REARMED`,
   `HELD_ADS_REARM_FAILED`, `ADS_ZOOM_MODIFIERS`/`HANDOFF_REFUSED` mitsenden.
   F10 liefert zusätzlich einen ADS-Snapshot, benötigt aber keinen gehaltenen
   Sprint-Input. Keine erneuten kostenpflichtigen Respawn-Tests nötig.

Erwarteter Abschluss-Log: `HELD_ADS_REARMED source=hybrid_settled_weapon_handoff`.
Kurzzeitige Abweisungen während eines echten Waffen-/Kamerablends sind zulässig.
Eine dauerhafte Sperre nach abgeschlossener Übergabe ist ein Fehler.
