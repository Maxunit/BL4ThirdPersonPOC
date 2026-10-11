# 0.3.9.25 – Hybrid Reticle QA

## Problem und Audit

Der Hybrid-Einstieg schaltet dieselbe bereits zoomende Waffe von TPS auf die
native FPS-Kamera. Er löst keinen erneuten Zoom-State-Wechsel aus, auf dessen
UI-Notification man die Reticle-Übergabe stützen könnte. .24 veröffentlichte das
TPS-Modell, löschte beim Scope-Einstieg aber nur Pending-/ADS-Buchhaltung.
Die fehlende Übergabe lässt sich im simulierten Modell bei Hold und Toggle
reproduzieren. Das belegt den Python-Pfad, nicht die exakte native HUD-Ereignisfolge.

## Änderung

- Nach erfolgreichem `SetActorCameraMode(..., 'Default', ...)` und Commit der
  FPS-Route wird einmal `hide_for_scope` auf dem vorhandenen Publisher ausgeführt.
- Show und Hide teilen denselben Snapshot-/Write-/Readback-Pfad; die bisherigen
  TPS-Publikationsgates und .24-Equip-POST-Anforderungen bleiben bestehen.
- Hide prüft aktives Hybrid-Scope, FPS-Route, lokale Controller-/Pawn-/Kamera-/
  Waffenidentität gegen die Identität vor dem Kamerawechsel, native Waffen-
  Besitzzuordnung und Zoom-State 1/2. Sonderzustände und Route-Pending sperren.
- Der native Kamerablend darf am Umschaltereignis noch den ausgehenden
  `ThirdPerson`-Modus melden. Ohne laufenden Blend muss `Default` vorliegen.
- Nur ein vorhandenes `crosshair_`-Modell mit `byte_90 == 0` und booleschem
  Sichtbarkeitswert wird geschrieben. Unveränderte Native-Hashes und
  Assignment-Bytes sichern den bereits bestehenden Zugriff ab.
- Ein verweigerter/fehlgeschlagener Kamerawechsel versteckt kein Modell.
- Der vorhandene Rückweg publiziert nach dem beobachteten TPS-Kamerablend erneut.
- Logging: `HYBRID_TPS_RETICLE_HIDDEN` bei Write; andernfalls
  `HYBRID_TPS_RETICLE_HANDOVER` mit Status/Gate. F10 enthält Modell und Zähler.

## Native Daten

Keine neuen RVAs, AOBs oder Offsets. Weiterverwendet werden die bestehenden
validierten Modelltabellen-/Owner-/Waffen-Anker in `_reticle_publish.py`.
Geschrieben werden ausschließlich Modell `+0x88` (Sichtbarkeit) und `+0x8C`
(Änderungszähler). `+0x90`, Text und native Scope-Daten werden nicht geändert.
Keine ZoomState-/Wants-/Pending-Schreibzugriffe, zusätzlichen Hooks, Timer oder
per-frame Reticle-Wiederholungen. Kein transienter Modellpointer wird gespeichert.

## Grenze

Bei einem Pointer-/Byte-/Modell-Guardfehler wird der Write verweigert. Der
Publisher meldet Fehler über den vorhandenen Fail-Closed-Pfad. Live-HUD und
native Scope-Overlays müssen mit dieser QA-Build im Spiel geprüft werden.
