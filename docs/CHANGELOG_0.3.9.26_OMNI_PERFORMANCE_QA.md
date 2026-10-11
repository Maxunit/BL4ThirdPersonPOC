# 0.3.9.26 – Omni-Performance-Messung

## Audit und Messgrenze

Im Spieltest zeigen sich beim Stillstand im gleichen Bildausschnitt mit Omni aus 120 FPS,
mit Omni an 110-114 FPS. Hardware: Ryzen 5 3600, 32 GB RAM, RTX 4060; Medium,
DLSS, FrameGen und NVIDIA-Control-Panel-Limit 120 angezeigte FPS.
Diese Beobachtung zeigt die Differenz unter diesen Einstellungen, nicht den
Anteil einzelner CPU-/GPU-/Native-Pfade oder die unlimitierte Leistung.

Der bestehende Idle-Pfad durchläuft die Gameplay-Pipeline, baut Samples auf,
prüft Laufzeit-/Animationsobjekte und native Speicherfelder wiederholt. Der
Profiler misst deren Kosten, bevor Optimierungen Guards oder Bewegungslogik ändern.

## Architektur

`omni/profiler.py` ist ein integrierter, standardmäßig inaktiver Profiler.
Drei Callback-Wrapper (Lifecycle, Vehicle, Gameplay) haben im inaktiven Zustand
nur den direkten Weiterleitungsweg; keine Clock-Reads oder Detail-Wrapper.
Sie funktionieren auch für bereits registrierte gebundene Hook-Callbacks.

- `total`: Wall-Time der drei bestehenden Omni-Callbacks, Aufrufzahlen,
  Gameplay-Dauerverteilung und Abstände der Gameplay-Callback-Einstiege.
- `detail`: zusätzlich temporäre Wrapper für 24 Python-Abschnitte sowie die
  bestehenden `_get_runtime`-/`_native_read`-Helfer. Erfasst verschachtelte
  Gesamt-/Eigenzeiten und Anzahl/Bytes der synchronen nativen Reads innerhalb
  der gemessenen Omni-Callbacks.
- Eigenzeit zieht die gemessenen Unteraufrufe ab. Gesamtzeiten verschachtelter
  Abschnitte dürfen nicht summiert werden.
- Zeitmessung über `perf_counter_ns`; automatisches Ende nach 600 Callback-
  Ereignissen. Keine Timer, Wartezeiten oder zusätzliche Update-Hooks.
- Konsolenbefehl armiert; vorhandenes F10 startet. Dadurch muss die Konsole
  während der Messung nicht offen bleiben. Zweites F10 beendet vorzeitig.
- Ende, Omni-Off/Mod-Disable und Session-Retirement stellen die Detail-Wrapper
  wieder her. Abbruch innerhalb eines gemessenen Calls wird bis zu dessen
  Rückkehr aufgeschoben. Fremde Methoden-Replacements werden nicht überschrieben.
- Bindings bleiben unverändert; kein transienter UObject wird im Profiler gespeichert.
  Ausgewertet werden vorhandene Sample-Dictionaries und primitive Sessiondaten.
- JSON-Ausgabe einmal am Ende unter `SETTINGS_DIR/BL4ThirdPersonPOC_reports`.
  Ein Fehler beim Speichern wird nach Wiederherstellung geloggt.

## Aussagekraft

Es sind Wall-Times der Python-Callbacks inklusive synchroner SDK-/Native-
Aufrufe und Profiler-Overhead. Detail hat mehr Messaufwand als Total. Deshalb
Total/Detail/Total im selben Bildausschnitt vergleichen. Abschließendes JSON-
Schreiben und Completion-Logging liegen außerhalb der aufgezeichneten Callback-
Dauern und können am Abschluss einen einzelnen zusätzlichen Frame kosten.

Nicht gemessen: native Detours außerhalb dieser Callbacks, GPU-Arbeit,
FrameGen und gemeinsamer Producer-/Filter-Aufwand. Callback-Abstände sind keine
Render-/FrameGen-FPS. Labels sind manuell; Idle/Moving/Special verwendet vorhandene
Samples, die nach frühen Returns veraltet sein können. Sessionwechsel erzeugen
Teilberichte statt eines vermischten Folgelaufs. Ein FPS-Gewinn wird nicht behauptet.

## Native Zugriff

Keine neuen RVAs, AOBs, Speicherfelder oder Native-Patches. Der bestehende
`_native_read(address, size)` wird nur während Detail im synchronen Omni-
Aufrufkontext zeitlich erfasst; seine Bounds-/Owner-/Byte-Guards bleiben erhalten.
