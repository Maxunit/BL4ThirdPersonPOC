# 0.3.9.23 ADS Refactor QA

Basis ist die unveränderte 0.3.9.22 Hybrid QA. Der Refactor behebt zwei im Trace
nachweisbare Mod-Pfade: ADS-Bestätigung aus dem alten nativen Zustand vor der
Eingabeverarbeitung und redundante SDK-Schreibzugriffe auf Wants/Pending.
Die beobachteten True-Schreibzugriffe erzeugten FF statt der nativen 01-Bytes.
Das belegt einen Fehler im Mod-Pfad; es beweist noch nicht die vollständige
Ursache jedes gemeldeten Hold-ADS-Problems.

## Steuerung

- `ads_control.py`: ADSController verwaltet Beobachtung, Laufzeitbesitzer und
  native Ein-/Ausstiege. Eingabe-Callbacks erfassen nur die gehaltene Taste und
  bereiten Waffeninformationen vor. Sie bestätigen kein ADS vor Native Dispatch.
- Der bestehende Kamera-Update und die bestehenden Collector-Benachrichtigungen
  lesen den lokalen nativen Zustand. State 1/2 aktiviert die Darstellung;
  State 0/3 beendet sie. Wants/Pending/Ticking allein bestätigen kein ADS.
- Physisches Loslassen räumt nur die Eingabevorbereitung ab. Toggle bleibt aktiv,
  wenn der native Zustand aktiv bleibt. Native Wiederaufnahme nach einem
  Waffenwechsel funktioniert auch ohne einen neuen physischen Press-Callback.
- Native Unterbrechung und Wiederaufnahme werden getrennt dargestellt. Gehaltene
  Eingabe bleibt über eine Unterbrechung und das Ende der FOV-Ausblendung erhalten.
- Reentrante Kamera-Benachrichtigungen erzeugen keinen zweiten Ein-/Ausstieg.
- Die native Hold/Toggle-Policy wird weder gelesen noch überschrieben. Der
  Snapshot-Befund Hold=00 / Toggle=01 an LocalPlayer+0x361 bleibt Diagnosewissen;
  der Refactor braucht keinen festen Offset für die Benutzereinstellung.

## Handoff und Darstellung

- `ads_handoff.py`: Waffen-, Kamera- und Collector-Identitäten, echte Equip-Paare,
  Reticle-Readiness und FPS/TPS-Routenwechsel. Keine Latch-Maskierung,
  Latch-Wiederherstellung, True/True-Wiederaufnahme oder State=2-Pose-Publikation.
- `ads_events.py`: FOV-Übergänge und Collector-Darstellung. Beim neuen Waffen-ADS
  innerhalb einer noch laufenden TPS-Ausblendung bleibt die Hip-Kalibrierung
  desselben Kamera-Besitzers erhalten. Ein sichtbarer Rest-Zoom wird nicht erneut
  als Hip-FOV skaliert. Die neue Waffe bekommt ihre eigenen Sight-Werte.
- Nach einem nativen Scope-Rückweg wartet der neue Einstieg auf den bestehenden
  Kamera-Übergangszustand. Keine zusätzliche Zeitgrenze oder erfundene Equip-Zahl.
- Hybrid-Scope-Switch, TPS-Recoil-Rearm, Reticle und Modifier-Readiness hängen an
  aktivem ADS statt an der weiterhin gehaltenen Taste; damit unterstützen sie
  auch natives Toggle-ADS nach Release.
- Der bereits vorhandene, build-geprüfte Sight-Modifier-Recovery-Pfad bleibt
  erhalten. Er ist kein ZoomState-Schreiber und wird nicht durch neue native
  Aufrufe oder Patches ersetzt. Native Reticle-Publikation bleibt ebenfalls erhalten.
- F10-Berichte enthalten `ads_control` mit beobachtetem Native State, Quelle,
  Ein-/Ausstiegen, physischem Hold und letztem Fehler. Entfernte Writer-Diagnosen
  werden nicht als weiterhin aktive Funktionen präsentiert.

Keine neuen Hooks, Detours, RAM-Scans oder ADS-Timing-Fenster. Vorhandene
FOV-/Kamera-Blend-Dauern sind Darstellung, keine Zustandsentscheidung.
Die ClientRestart-Registrierung aus .22 und die übrigen nativen Paketdateien
bleiben erhalten. `native_lifecycle.py` ändert ADS-Readiness-Gates, keine Opcodes.
