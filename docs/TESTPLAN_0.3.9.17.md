# 0.3.9.17 – QA der eigenen Mapping-Key-Kopien

Spiel beenden, Mod und Cache wie üblich ersetzen. Installierbare Datei:
`dist/BL4ThirdPersonPOC.sdkmod`. TPS und Omni aktivieren, auf dem Boden bleiben.

1. Objekt aufheben. Rückwärts laufen und mit der im Spiel belegten Wurfaktion
   werfen. Erwartung: Körper dreht zur Kamerarichtung, die normale Omni-
   Ausrichtung übernimmt nach dem Wurf wieder. Ein kurzer Druck muss genügen.
2. Wenn möglich wiederholen, optional auch mit Controller. Ablegen statt
   Werfen darf keine Carry-Wurfepisode starten.
3. Weil NativeBindings seine Schlüssel für alle Rollen kopiert: kurz Fire,
   gehaltenes ADS, Sprint/Dash, Jump und Crouch prüfen. Hybrid ADS + Scope-
   Rückweg ebenfalls prüfen, sofern aktiv. Keine neuen Tasten konfigurieren.
4. Direkt danach `bl4tps_omni report` ausführen und JSON senden. Benennen,
   ob die sichtbare Drehung funktioniert und danach Omni wieder übernimmt.

Der Bericht soll mindestens eine `carry_throw_episode_count` enthalten,
`object_release_observed=True` und ein Ende `CARRY_CONTEXT_ENDED` melden.
Die Mapping-Metadaten enthalten `key_storage` für SDK-eigene FKey-Kopien.
Wenn keine Episode entsteht: keinen Erfolg aus fehlenden Fehlern ableiten.
Dieser Test bestätigt weder andere Throwable-Arten noch alle Audit-Punkte.


## Erster Spieltest – 09.10.2026

Report `player_omnidirectional_snapshot_20261009_175826_202657.json`:
Root RUNNING, keine Root- oder Gameplay-Fehler, keine pensionierte Sitzung.
Eine Carry-Wurfepisode mit beobachteter Objektfreigabe und Ende
`CARRY_CONTEXT_ENDED`. Die Combat-Transitions halten die Ausrichtung auch
nach Tastenfreigabe und beenden sie beim nativen Kontextende.

Die erhaltenen Visual-Samples zeigen etwa 180° Körper-/Kamera-Abstand vor
dem Wurf (Update 326), schrittweise Ausrichtung auf 0° bis Update 335,
Halten bis 339 und ab Update 340 Rückkehr von der Kamerarichtung zur
Bewegungsausrichtung. QA bestätigt die sichtbare, natürliche Drehung.
Für diesen Objektwurf ist .17 live bestätigt. Der Bericht bestätigt damit
nicht alle übrigen Aktionen, andere Throwable-Arten oder Controller-QA.
