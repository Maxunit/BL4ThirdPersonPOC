# 0.3.9.16 – QA: Ausrichtung beim Werfen aufgehobener Objekte

Basis: 0.3.9.15 QA mit dem im ersten Spieltest bestätigten Hybrid-Rückweg.
Der zugrunde liegende GitHub-Stand ist weiterhin .13, Commit
`22c613606548ce62c27a289f02ebc1e17a308b24`.

## Gemessener Fehler

Der .15-Bericht `player_omnidirectional_snapshot_20261009_170416_279481.json`
erkannte den Tragekontext, aber keine Wurfepisode. Die anschließende Leseprobe
`omni_throwable_observer_20261009_171520_222652.json` enthält 322 Samples und
35 Ereignisse ohne Lese- oder Probe-Fehler; der temporäre SDK-Hook wurde entfernt.

Sie belegt `Action_Carry_Throw` im bekannten Enhanced-Input-Ordner, in der getesteten
Belegung auf RMB beziehungsweise Gamepad_LeftTrigger. Der alte Wurfpfad verwendete Gadget
oder Fire bei fehlendem Zoom-Mapping und erfasste diese Aktion nicht.

Im Probe-Update 228 ist Carry_Throw gedrückt und `bIsCarrying` bereits falsch;
im vorherigen Sample war das Feld noch wahr. Die Taste wird ab Update 231
nicht mehr gehalten. Die Carry_Throw-Mappings bleiben bis Update 236 bestehen
und verschwinden bei Update 237. In allen 322 Samples liefert
`GetCurrentActiveMontage()` keine aktive Montage. Während des gemessenen
Wurfs bleibt der Körper etwa 180° von der Blickrichtung entfernt.

## Gezielte Änderung

- Der bestehende Eingabeadapter kennt die optionale Rolle `carry_throw` für
  das gemessene `Action_Carry_Throw`. Tastatur und Controller folgen den
  tatsächlichen Spielbelegungen. Unbrauchbare komplexe oder fremde optionale
  Zeilen erzeugen keine Ersatzbelegung und keine neue Schutzabschaltung.
- Eine steigende Wurf-Eingabe beginnt die Ausrichtung. Bei beobachtetem
  `bIsCarrying: true → false` bleibt Combat-Ausrichtung aktiv, solange der
  Carry_Throw-Eingabekontext noch gemeldet ist. Beim Kontextende übernimmt
  die normale Omni-Bewegungsausrichtung wieder.
- Ein Tastendruck ohne beobachtete Objektfreigabe hält die Ausrichtung nur
  während der Eingabe. Fehlt das Carry-Feld, gilt ebenfalls nur die gehaltene
  Eingabe; ein Kontext allein darf dann keine fortdauernde Ausrichtung halten.
  Menü, Fahrzeug, Shop, Leiter, Slide oder ein neu getragenes Objekt beenden
  beziehungsweise verhindern die Carry-Übergabe.
- Die bestehende Combat-/Body-Follow-Pipeline verwendet weiter ihre
  visuelle Drehrate von 1080°/s. Die Korrektur verändert weder die native
  Wurfzulassung noch Flugrichtung, Ressourcen oder Eingabetrigger.
- Fire allein bei fehlendem Zoom-Mapping wird nicht mehr als Carry-Wurf
  eingestuft. Der vorhandene Gadget-/Ordnance-Montagepfad bleibt separat.
  Seine Montage-Frische- und Quiet-Sample-Regeln sind durch diesen Schritt
  nicht bestätigt oder repariert.
- Reports enthalten `carry_throw_episodes`, `carry_throw_episode_count`
  sowie im Combat-Sample Eingabe, Kontext, Carry-Feld, Hold und Phase.
  `throw_episode_count` zählt Gadget- und Carry-Episoden zusammen;
  `throw_episodes` enthält weiterhin nur die Gadget-Episoden.

Die neue Carry-Übergabe verwendet keine Montage-Frist, keinen zusätzlichen
Timer und keine Anzahl ruhiger Samples als Freigabebedingung. Neue native
Patches oder SDK-Hooks sind dafür nicht erforderlich.

## Prüfung und Grenzen

282 Tests unter Python 3.12.14: 278 erfolgreich, 4 plattformbedingte Skips.
14 neue Tests prüfen den State-Tracker, reale Eingabeadapter- und Combat-
Verdrahtung sowie `GameplaySession.frame()` bis zur Körperdrehung mit
simulierten SDK-Objekten und nativen Workern. Der Körper-Test prüft freie
Rückwärtsausrichtung, Drehung zur Kamera, gehaltene Ausrichtung nach
Tastenfreigabe und die Rückgabe an Movement-Follow.

Eine zusätzliche Wiedergabe aller 322 echten Probe-Zeilen im neuen Tracker
ergibt genau eine Episode: Hold in Updates 228–236, Ende bei Mapping-Entfernung
in Update 237. Der Tracker behauptet damit keinen Montage- oder Animationsabschluss:
der gemessene Eingabekontext ist seine Handback-Bedingung. Ob diese Bedingung
die sichtbare Wurfbewegung vollständig abdeckt, ist noch im Spiel zu prüfen.
.16 ist eine gezielte QA-Build; andere Throwable-Arten und weitere Audit-
Punkte sind dadurch nicht pauschal bestätigt.
