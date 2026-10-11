# 0.3.9.24 – gezielter Spieltest

Frisch installieren wie üblich, genau eine Mod-Version. Zuerst dasselbe Setup
und denselben Hold-ADS-Waffenwechsel nutzen, bei dem .23 das Fadenkreuz verliert.
Keine alte Trace-Probe starten.

1. Normale TPS-Waffe: Hold-ADS drücken und halten; ohne Waffenwechsel prüfen.
2. ADS weiter halten, A → B → A wechseln. Nach jedem abgeschlossenen Wechsel
   muss das passende Fadenkreuz wieder sichtbar sein. Eine Unterbrechung während
   des nativen Equip ist von dauerhaftem Verschwinden nach Equip zu unterscheiden.
3. ADS loslassen; Hip-Fadenkreuz prüfen. Erneut halten und den Wechsel wiederholen.
4. Toggle: kurzer Press/Release, Waffenwechsel mit freier Taste; danach Toggle
   mit während des Wechsels gehaltener Taste und anschließendem Release prüfen.
5. Erst wenn der ursprüngliche Fall besteht: Sniper ↔ normale Waffe und optional
   Hybrid-Scope-Ein-/Ausstieg nach einem ADS-Waffenwechsel prüfen.

Wenn das Fadenkreuz erneut dauerhaft fehlt: direkt F10 drücken und diese JSON
zusammen mit den Log-Zeilen `TPS_RETICLE_EVENT_RESULT`,
`TPS_RETICLE_READINESS_RESULT` und eventuellen `ADS_HANDOFF_ERROR`-Zeilen senden.

F10 liest den bereits vorhandenen Publisher-Snapshot; keine neue Probe nötig.
Relevant sind Native State, Route, Waffen-/Collector-Identitäten, Equip-Ordinal,
Rebind/Pending, letzter Reticle-Event/Status und `reticle_model.byte_88`.
Bei sichtbar fehlendem Fadenkreuz trotz publiziertem Modell muss die weitere
HUD-/Collector-Bindung untersucht werden; der Publisher markiert diese Bindung
weiterhin als `local_pc_candidate` und behauptet keinen Nachweis der HUD-Zeichnung.
