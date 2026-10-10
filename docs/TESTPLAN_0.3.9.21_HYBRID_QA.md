# 0.3.9.21 Hybrid QA – Spieltest

1. Laufende Proben stoppen, Spiel beenden und Mod/Caches wie gewohnt frisch
   ersetzen. SDKMOD muss BL4ThirdPersonPOC.sdkmod heißen, ohne Download-Zusätze.
2. Mit derselben Waffe, denselben Kamera-/ADS-Zoom-Einstellungen und derselben
   Position TPS-ADS bei Hybrid aus und an vergleichen. Jeden Versuch aus
   regulärem TPS ohne gehaltenes ADS beginnen. Nach dem ADS-Blend müssen die
   Kameraposition und der beabsichtigte TPS-Zoom gleich sein. Für Sniper den
   normalen Sniper-ADS-Modus auf TPS stellen, damit beide Versuche TPS nutzen.
3. Bei Hybrid an ADS halten → konfigurierte Sprint-Taste kurz drücken/loslassen
   → FPS-ADS → erneut Sprint drücken/loslassen → TPS-ADS. Der Rückweg darf
   keinen extra Schritt nach vorne und keinen zweiten Zoom-in hinzufügen.
4. Waffenwechsel aus FPS-ADS bei gehaltenem ADS wie in .20 testen: neue Waffe
   landet in TPS-ADS; nach abgeschlossener Übergabe muss Sprint wieder FPS-ADS
   erreichen, ohne ADS loszulassen. Mehrfach wiederholen.
5. Danach Eingaben loslassen und bl4tps_omni report ausführen; JSON und bei
   Auffälligkeiten den Mod-Log senden. Keine alten Dolly-/Handoff-Proben nötig.

Die reguläre Sniper-ADS-Einstellung gilt weiterhin bei Hybrid aus. Hybrid
beginnt bei allen Kategorien in TPS-ADS; Sprint schaltet nativ zu FPS-ADS.
