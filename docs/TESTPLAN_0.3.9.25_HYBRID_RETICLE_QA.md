# 0.3.9.25 – gezielter Spieltest

Spiel vollständig beenden, alte Mod und deren PyCache entfernen, dann entweder
`dist/BL4ThirdPersonPOC.sdkmod` oder den Quellordner installieren.
Omni und Hybrid-ADS wie bisher aktivieren. Sprint folgt der Spielbelegung
(z. B. Shift); es wird keine zusätzliche Taste benötigt.

1. Hold-ADS mit einer normalen Waffe: TPS-ADS aktiv halten, Shift drücken.
   Das TPS-Crosshair muss in FPS-ADS verschwinden; das native Visier bleibt korrekt.
2. ADS weiter halten und erneut Shift drücken: nach dem Kamerablend muss das
   TPS-Crosshair wieder erscheinen. Mehrmals hin- und herschalten.
3. Während FPS-ADS die ADS-Taste loslassen: normale TPS-/Hip-Rückkehr prüfen.
4. Mit Toggle-ADS wiederholen: ADS aktivieren, physische ADS-Taste loslassen,
   Shift -> FPS, Shift -> TPS, ADS erneut drücken -> beenden.
5. Mit Sniper wiederholen: Scope-Overlay und Rückkehr-Crosshair prüfen.
6. Kurzer .24-Nachtest: Hold-ADS-Waffenwechsel mit normalen Waffen,
   Sniper/Normal-Waffenwechsel und Waffenwechsel im Hybrid-FPS-ADS.

Bei falscher Darstellung direkt im fehlerhaften Zustand F10 drücken und JSON
sowie Logzeilen mit `HYBRID_TPS_RETICLE`, `HYBRID_SCOPE`, `TPS_RETICLE` und
etwaigem `PUBLISH_DISABLED` sichern. F10 soll nicht erst nach ADS-Ende erfolgen.
