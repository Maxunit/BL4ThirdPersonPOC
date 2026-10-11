# 0.3.9.23 – ADS-Spieltest

Spiel beenden; alte ADS-Proben stoppen/entfernen. Genau eine Mod-Version
installieren: `dist/BL4ThirdPersonPOC.sdkmod` nach `sdk_mods/`, oder alternativ den
Quellordner. Vorhandene Einstellungen beibehalten. Zunächst TPS an, Omni/Hybrid
ADS aus, normale Waffe; anschließend Sniper und optional Hybrid testen.

| Probe | Erwarteter Verlauf |
|---|---|
| Hold: kurz drücken, dann halten/loslassen | Native ADS-Ein-/Ausstiege steuern Kamera und FOV; keine hängenbleibende Mod-ADS-Darstellung |
| Toggle: drücken/loslassen, erneut drücken | ADS bleibt nach Release; zweiter Press beendet es mit dem nativen Zoom-Ausstieg |
| Toggle: ADS aktiv, Taste frei, Waffenwechsel | Native ADS-Unterbrechung beendet die Mod-Darstellung; kein erzwungenes Wieder-ADS |
| Hold: Taste während Waffenwechsel halten | Native Unterbrechung und Wiederaufnahme; neue Waffe, passende FOV/Reticle, keine zusätzliche Eingabe nötig |
| Toggle: Taste während Waffenwechsel halten, danach loslassen | Native Wiederaufnahme; ADS bleibt nach Release, bis erneuter Press es beendet |
| Während Waffenwechsel loslassen | Keine Wiederaufnahme durch einen Mod-Latch-Schreibzugriff; Kamera folgt dem tatsächlichen nativen Zustand |
| Schnell erneut ADS während Ausblendung | Dieselbe Waffe darf die FOV-Ausblendung umkehren; eine neue Waffe nutzt ihre eigenen Sight-Werte |
| Normal ↔ Sniper bei gehaltenem ADS | TPS/FPS-Routen passen nach dem nativen Ein-/Ausstieg; kein mehrfach skalierter Rest-Zoom |
| Hybrid optional: Scope an/aus bei Hold und Toggle | Scope-Switch funktioniert auch bei aktivem Toggle-ADS mit freier ADS-Taste |
| FFYL, Fahrzeug, Leiter, Respawn, Mod aus/an | ADS-Darstellung und alte Identitäten werden beendet; kein Übernehmen alter Kamera-Kalibrierung |

Zuerst das bisher fehlerhafte Hold-Szenario und Toggle-Release prüfen. Die
veränderte Darstellung während der nativen Waffenwechsel-Unterbrechung ist Teil
von .23: Es wird kein ADS-Zustand künstlich über die Unterbrechung festgehalten.

F10 einmal im Fehlerzustand liefert den vorhandenen QA-Bericht. Benötigt werden
bei erneutem Fehler: Hold/Toggle-Einstellung, Waffe/Routenfolge, genaue
Tastenfolge, Screenshot falls die Darstellung betroffen ist, F10-JSON und
relevante Fehlerzeilen aus dem Mod-Log. Keine alte schwere Trace-Probe starten.

Lokale Tests ersetzen weder den Spieltest noch einen FPS-Vergleich mit .22.
Wenn die native Hold-Policy trotz Release ADS aktiv lässt, folgt .23 diesem
nativen Zustand; dieser Fall muss anhand neuer Daten getrennt untersucht werden.
