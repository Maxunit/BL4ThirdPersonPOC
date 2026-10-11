# 0.3.9.27 – erster gezielter Omni-Performance-Refactor

## Grundlage: drei Idle-Aufnahmen aus .26

600 Updates je Datei, Diagnose aus, vollständige Aufnahmen, keine gemessenen
Exceptions; temporäre Profiler-Wrapper erfolgreich restauriert.

| Capture | Omni-Callback-Zeit je Gameplay-Update |
|---|---:|
| idle_a / total | 4.073605 ms |
| idle_detail / detail | 4.779812 ms |
| idle_b / total | 4.022381 ms |

Total-Mittel: 4.047993 ms; Detail-Aufschlag: etwa 18.1 %. Angezeigte FPS laut
Spieltest bei Omni an weiterhin 110–114, ohne Omni an derselben Stelle 120.
Diese FPS sind eine Spielbeobachtung; die JSONs messen Callback-Zeiten, keine
Render-/FrameGen-FPS. Die Total-Summe umfasst Gameplay, Lifecycle und Vehicle.
Detail-Eigenzeiten sind bereits um verschachtelte gemessene Calls bereinigt.

Detail zeigte 33 Runtime-Auflösungen, 30 bound-Prüfungen und 12 Input-Snapshots
je Update. Allein die zwei Runtime-Kategorien hatten zusammen etwa 1.42 ms
Eigenzeit. Input-Snapshots etwa 0.53 ms, Visual-Capture etwa 0.42 ms Eigenzeit.
Das ist eine Priorisierung des Audits, kein Nachweis eines bestimmten FPS-Gewinns.

## Änderungen

1. `NativeBindings.begin_frame(coherent=True)` wird ausschließlich für den
   vorhandenen Gameplay-Callback verwendet. Die erste Input-Aufnahme prüft
   Mapping-Anzahl und liest konfigurierte, SDK-eigene FKeys. Spätere Verbraucher
   erhalten eine Kopie der booleschen Aufnahme, ohne die Mapping-Liste erneut
   abzufragen. Controller-/PlayerInput-WeakPointer und aktuelle Owner-Zuordnung
   werden bei jedem Snapshot weiterhin geprüft. `end_frame()` im `finally`
   leert die Aufnahme auch bei Fehlern und Handoffs.
2. Mapping-Anzahländerungen während dieses Callbacks werden beim nächsten
   Callback aufgenommen; ein explizites `refresh()` invalidiert sofort.
   Die bestehende PRE-Refresh-Logik (Anzahl, Rückkehr aus Menüs, bestehender
   30-Update-Takt) bleibt erhalten. Andere Nutzer des gemeinsamen Input-Lesers
   behalten die bisherigen sofortigen Mapping-Anzahlprüfungen.
3. Fire und Zoom in `read_combat()` verwenden dieselbe lokale Input-Aufnahme.
4. Der Special-State-Schritt übergibt seine gerade geprüften Runtime-Objekte
   direkt an `state_context()`. So entfällt die vorher doppelte Auflösung.
   Die Objekte werden weder auf der Session gespeichert noch in anderen
   Pipeline-Schritten wiederverwendet. Spätere `bound()`-Aufrufe prüfen erneut.
5. `omni/visual_guard.py` trennt erforderliche Mesh-/Anim-Owner-, Adress-,
   Eingabewert- und Normal-AimOffset-Guards vom Bericht. Der normale Gameplay-
   Pfad führt die Guards weiterhin aus, baut aber keine Visual-Zeilen und keine
   reinen Pose-/Rotations-/Asset-Beschreibungen mehr. Bei `diag on` bleibt der
   vollständige Visual-Bericht verfügbar. Der Guard baut ein Werte-Dictionary
   nur, wenn der Diagnosepfad es benötigt.
6. `state_context()` baut im normalen Pfad die erforderlichen Zustandsdaten.
   Objektbeschreibungen entstehen bei Zustandskanten oder aktivierter Diagnose.
7. Der Detail-Profiler ergänzt `visual.guard`, damit Guard-Zeit separat sichtbar
   bleibt. Total-Messung und Start per F10 bleiben wie in .26.

## Grenzen und bewusst erhaltene Prüfungen

Kein allgemeiner Callback-Cache für Runtime-UObjects: Ein noch lebender alter
Controller ist kein Beweis für die aktuelle Localplayer-Zuordnung. Die übrigen
WeakPointer-, Localplayer-/Kamera- und Movement-Owner-Prüfungen bleiben daher
pro `bound()` erhalten. Auch Native-Lese-, Byte-/Hash-/Build-Guards und Patch-
Templates bleiben unverändert. Es gibt keine neuen Hooks, Timer, Hotkeys oder
Polling-Schleifen. Gameplay-State, Bewegungs-Samples und erforderliche Native-
Reads werden weiterhin verarbeitet. Folgende Optimierungsschritte hängen vom
.27-Vergleich ab; die verbleibenden Kosten sind noch nicht neu gemessen.
