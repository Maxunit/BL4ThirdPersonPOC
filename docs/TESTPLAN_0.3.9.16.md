# Gezielter QA-Lauf 0.3.9.16

Spiel vollständig beenden und Mod/Caches wie gewohnt austauschen.
Die neue `dist/BL4ThirdPersonPOC.sdkmod` installieren, alternativ den
Mod-Ordner; nur eine der beiden Varianten installieren. Eine alte Probe
ist für diesen Lauf nicht erforderlich. Die .15-Leseprobe wurde bereits
mit MANUAL_STOP entfernt.

Save laden und TPS/Omni aktivieren. Konsole während der Eingaben geschlossen
halten. Die Bezeichnungen meinen die tatsächlichen Spielaktionen; in der getesteten Belegung
liegen Carry_Throw auf RMB beziehungsweise LT, Carry_Drop auf E.

1. Dieselbe Art werfbaren Gegenstands wie im letzten Probe-Lauf aufnehmen.
   Ohne ADS mit S rückwärts laufen, bis der Körper von der Kamera wegschaut.
   Währenddessen einmal werfen und kurz weiterlaufen.
   Erwartet: beim Wurf dreht der Körper zur Blickrichtung, danach wieder zur
   Bewegungsrichtung. Kein dauerhafter Lock und keine Omni-Schutzabschaltung.
   Direkt danach `bl4tps_omni report` ausführen und die JSON sichern.
2. Einen Gegenstand aufnehmen und ihn über die normale Ablegen-Aktion
   ablegen. Erwartet: Ablegen allein startet keine Carry-Wurf-Ausrichtung.
3. Falls verfügbar, eine zweite Art werfbaren Objekts sowie die Controller-
   Wurfaktion prüfen. Darauf achten, ob die Kameraausrichtung während der
   sichtbaren Wurfbewegung zu früh endet oder nach ihr zu lange bleibt.
4. Ohne getragenes Objekt normales ADS und den Hybrid-Wechsel prüfen:
   kein Carry-Wurf-Hold allein durch RMB/LT, kein neuer Zoom-Aussetzer.

Die `OMNI_REPORT json=...`-Zeile nennt den Berichtspfad. JSON und auffällige
Log-Zeilen zur Auswertung bereitstellen; dabei die sichtbare Drehung kurz beschreiben.
In den Combat-Samples sollten `carry_throw_intent` und anschließend
`carry_throw_hold` sichtbar sein. Eine vollständige Episode enthält
`object_release_observed=true` und endet mit `CARRY_CONTEXT_ENDED`.
Der Wert belegt den Eingabe-Handback, nicht das Ende sämtlicher
Animationsarbeit. Beim Ablegen darf keine neue Carry-Wurfepisode entstehen.

Bei einem unerwarteten Omni-Stopp zuerst einen Report sichern, bevor die
Funktion wieder eingeschaltet wird. Dieser Test betrifft aufgehobene Objekte;
Gadget-/Ordnance-Verhalten folgt bei Bedarf in einem eigenen Schritt.
