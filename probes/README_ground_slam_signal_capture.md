# Ground-Slam-Signalprobe für 0.3.9.35

Ein eigenständiges PyExec-Skript; .35 bleibt installiert. Die vorige
Phasenprobe muss beendet sein. Keine Höhenaufnahme oder Omni-Profiler parallel.

1. `ground_slam_signal_capture.py` in `sdk_mods` bzw. deinen bisherigen
   PyExec-Ordner legen.
2. In geladenem TPS `pyexec ground_slam_signal_capture.py` ausführen.
3. F1 schließen. Zwei Sekunden stillstehen; einen normalen Sprung ohne Slam
   ausführen und nach der Landung kurz warten. Das ist der Kontrollabschnitt.
4. Den längeren Ground Slam ausführen. Nach Kamerarückkehr drei bis fünf
   Sekunden stillstehen.
5. Erneut `pyexec ground_slam_signal_capture.py` oder F10: Stop und JSON.
   `ground_slam_signals_<UTC-Zeitstempel>.json` liegt in
   `sdk_mods/settings/BL4ThirdPersonPOC_reports`; der vollständige Pfad erscheint
   nach `SAVED` in der Konsole.

Start/Stop, Limits (180 Sekunden einschließlich Startwartezeit oder 16.000
Updates), Owner-Wechsel, Ausgabe-Wiederholung und Mod-Shutdown verwenden die
Diagnose-Infrastruktur von .35. Alle zusätzlich registrierten SDK-Beobachter
werden vor Ausgabe und Producer-Shutdown entfernt. Ein fehlgeschlagener
Detach behält den Diagnoseplatz für einen manuellen Wiederholungsversuch.

Die Probe kopiert die Phasenmessung und ergänzt:

- Eine begrenzte Reflection-Inventur von Slam-UFunctions auf Controller,
  Character, Movement und Animationsinstanz: Namen, Signaturen, Flags.
- Lesezugriffe auf die vorhandenen Bindungen und Signaturen von
  `OnStartGroundSlam` und `OnStopGroundSlam`. Keine Delegate-Aufrufe oder
  Änderungen an deren Bindungen.
- Bis zu zwölf SDK-POST-Beobachter auf passende Start-/Stop-/End-Funktionen
  und bereits gebundene Listener. Marker enthalten Zeitstempel und Herkunft;
  andere Empfänger und Worker-Thread-Aufrufe werden gefiltert.
- Bis zu acht Bool-Getter: nur `IsGroundSlamming`, `IsGroundSlamActive`,
  `IsInGroundSlam` oder `IsPerformingGroundSlam`, wenn sie als BlueprintPure
  markiert sind und genau einen Bool-Rückgabeparameter ohne Eingaben besitzen.
  Verfügbare Rückgabewerte werden je Update unter `slam_getters` aufgezeichnet.
- `signal_events` (maximal 2.048), `functions`, `delegates`, `events`,
  `samples`, Cleanup- und Fehlerangaben zur gemeinsamen Auswertung.

Ein Aufruf kann ein abgelehnter Startversuch sein. Ein vorhandener
Delegate-Listener kann auch von einem anderen Pfad aufgerufen werden.
Eine Delegate-Signatur ist selbst kein Beweis für einen Broadcast.
Darum sind Marker zunächst Kandidaten und werden mit Gettern, Bewegung,
Kameramodus und dem gespeicherten `LastGroundSlamEndedDetails` verglichen.
Wenn keine passenden Getter oder Listener existieren, bleibt die Inventur
nutzbar; die Probe erzeugt keine Ersatzereignisse aus der Fallgeschwindigkeit.

Keine Kamera-, Animations- oder Gameplaywrites; keine native Speicheranalyse,
Patches, Delegate-Mutation, simulierten Eingaben, neuen Producer oder Timer.
Die vorhandenen .35-Kameraeffekte werden durch die Probe nicht verändert.

Prüfung: `python tests/ground_slam_signal_probe_scenario.py`.
15 lokale Tests mit dem echten Loader/Update-Router und simulierten SDK-Objekten
prüfen Grundaufnahme, reinen Getter, Start-/Stop-Marker, vorhandene Listener,
Signatur-/Thread-/Empfängerfilter sowie Cleanup bei Teilregistrierung,
Detach-/Schreibfehler, F10, Shutdown, Limits und Owner-Wechsel.
Das ersetzt die Ingame-Verifikation der tatsächlich vorhandenen Signale nicht.

SDK-Reflection und Delegate-Iteration wurden anhand dieser primären Quellen
geprüft (pyunrealsdk Commit `cb5fc362ea228727f334d94b64eb9538d8778bc6`):

- [UObject-/UStruct-Bindings](https://github.com/bl-sdk/pyunrealsdk/blob/cb5fc362ea228727f334d94b64eb9538d8778bc6/src/pyunrealsdk/unreal_bindings/uobject_children.cpp)
- [BoundFunction](https://github.com/bl-sdk/pyunrealsdk/blob/cb5fc362ea228727f334d94b64eb9538d8778bc6/src/pyunrealsdk/unreal_bindings/bound_function.cpp)
- [WrappedMulticastDelegate](https://github.com/bl-sdk/pyunrealsdk/blob/cb5fc362ea228727f334d94b64eb9538d8778bc6/src/pyunrealsdk/unreal_bindings/wrapped_multicast_delegate.cpp)
