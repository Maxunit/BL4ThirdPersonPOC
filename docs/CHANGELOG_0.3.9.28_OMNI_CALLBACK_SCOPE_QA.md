# 0.3.9.28 – Omni Callback-Scope (Performance-Prototyp, Claude)

Basis: 0.3.9.27 unverändert übernommen. Nur Omni-Hotpath und Input-Leser geändert.

## Ursache des Idle-Verlusts

Die .26-Messung zeigt rund 4 ms Python-Arbeit pro Gameplay-Update im Stillstand.
Das läuft auf dem Game-Thread. Mit FrameGen sind 120 angezeigte FPS etwa 60
gerenderte, also rund 16,7 ms pro Frame. 4 ms sind davon fast ein Viertel.
Das erklärt den Rückgang von 120 auf 110–114 angezeigte FPS.

Die Zeit steckt nicht in einer einzelnen teuren Funktion. Sie entsteht, weil jede
der 27 Pipeline-Stufen die Welt selbst neu prüft. Eine Zähl-Umgebung mit dem
echten Omni-Code (`tests/omni_idle_cost_scenario.py`) zeigt pro Idle-Update
(Lifecycle-PRE + Gameplay-POST, ohne Vehicle-POST):

| Pro Update, Stand | 0.3.9.27 | 0.3.9.28 |
|---|---:|---:|
| `bound()` mit voller Identitätsprüfung | 30 | 2 |
| `_get_runtime()` (get_pc-Kette) | 30 | 2 |
| SDK-Property-Lesezugriffe | 392 | 148 |
| UFunction-Aufrufe | 48 | 26 |
| UObject-Vergleiche / WeakPointer-Derefs | 161 / 161 | 45 / 44 |
| ReadProcessMemory | 28 | 4,6 |
| Voller Mapping-Scan | alle 30 Updates | alle 300 Updates |

In der Hocke (PAUSE-Pfad): 23 → 2 Runtime-Auflösungen, 300 → 114 Property-Reads,
49 → 30 UFunctions, 28 → 6,3 ReadProcessMemory.

Die Zahlen sind exakte Zählungen in der Fake-Welt, keine Zeiten. Der Abgleich mit
.26 passt: dort 30 `bound()`, 33 Runtime-Auflösungen (davon 2 im Vehicle-POST)
und 12 Input-Snapshots; die Zähl-Umgebung findet für .27 30, 30 und 11.

## Änderungen

1. **Identität einmal pro Callback.** `bound()` prüft beim ersten Aufruf eines
   Callbacks vollständig: WeakPointer, aktuelle get_pc-Zuordnung, Movement-Owner.
   Weitere Aufrufe im selben Callback bekommen dasselbe Tupel. Das Tupel wird im
   `finally` des Callbacks verworfen, ebenso in `finish()`. Lifecycle-PRE und
   Gameplay-POST haben je einen eigenen Scope.
   Begründung: Innerhalb eines synchronen Game-Thread-Callbacks läuft kein anderer
   Game-Thread-Code. Possession, Kamera-Manager und Movement können sich zwischen
   zwei Stufen nicht ändern. Der Einwand aus .27 („lebender alter Controller ist
   kein Beweis für die aktuelle Zuordnung“) gilt über Callbacks hinweg; dort
   bleibt die volle Prüfung.
2. **`IsCharacterDashing` und `GetActorCameraMode` einmal pro Callback** für
   Stufen-Entscheidungen (Klassifizierung, Dash-Zyklus, Zustandskontext). Jeder
   Game-Write (`set_rotation`, `SetWantsToDash`) verwirft den Wert. Der
   Sampling-Guard in `_sample_frame` liest den Kameramodus weiter frisch. Ein
   Kamerawechsel innerhalb der Pipeline stoppt deshalb weiter mit
   `LEFT_NORMAL_TPS`; der Test aus .14 bleibt unverändert grün.
3. **Native Byte-Audits round-robin.** Die Prüfung eigener Patch-Bytes,
   Node-vtables und des Lean-Links lief in jedem Update (28 ReadProcessMemory).
   Jetzt höchstens zwei von elf Slots pro Update, jeder Slot innerhalb von
   `NATIVE_AUDIT_PERIOD = 6` Updates. Erstes Update, Resume und Rebind prüfen alle
   Slots. Gilt für RUN- und Pause-Pfade. Direkte `validate()`-Aufrufe vor dem
   Einschalten eines Overrides (Jump-Idle, Slam, Slide) sind unverändert.
   Identität (Pawn, Movement, Anim-Adresse, Handler) prüft weiter jedes Update.
4. **Eine SDK-Abfrage pro Taste.** Beim Mapping-Refresh wird jede Taste einmal
   über `KismetInputLibrary.Key_IsAnalog/Key_IsButtonAxis` eingeordnet: Knopf →
   nur `IsInputKeyDown`, reine Achse → nur `GetInputAnalogKeyState`.
   Button-Achsen (Trigger) und alles Unklare behalten beide Abfragen. Schlägt die
   Einordnung fehl, gilt das alte Verhalten.
5. **Voller Mapping-Scan alle 300 statt 30 Updates.** Anzahländerung,
   Rückkehr aus dem Menü und explizites `refresh()` lösen weiter sofort aus.
   Der Scan liest jede Zeile samt Pfadnamen (in der Fake-Welt 468 Reads und 272
   Pfadnamen) in einem einzigen Frame. Das war alle 0,5 s ein Frametime-Spike.
6. **Stillstand ohne Handler-Read.** `_ground_vector_prepare_ground` bricht bei
   Geschwindigkeit ≤ 100 jetzt vor `validate_handler()` und dem Native-Read ab.
   `_manual_dash_frame` hat den Handler im selben Update bereits geprüft.
7. **Produktions-Sample schlanker.** `orientation_flags` und die optionalen
   Mesh-/Anim-Felder entstehen nur mit Pose-Diagnose. Kein Produktionspfad liest sie.

## Geänderter Vertrag

- Fremde Änderung an eigenen Patch-Bytes: erkannt innerhalb von 6 Updates statt
  im nächsten. Der Test `test_native_validation_failure_during_scope_still_stops_session`
  prüft das jetzt über eine Audit-Periode.
- Mapping-Änderung ohne Anzahländerung und ohne Menü: spätestens nach 300 statt
  30 Updates. Exakte Alternative für später: die `EnhancedActionMappings`-Bytes
  (reflektierter Offset 1344) per einem Native-Read vergleichen und nur bei
  Abweichung scannen.

## Unverändert

Native-Templates, Build-/Byte-/Hash-Guards, Patch-Installation und -Restore,
Hook-Struktur, Lifecycle-Gates, Bewegungslogik und alle Native-Klassen
(AST-Hash-Test grün). Keine neuen Hooks, Timer oder RVAs.

## Grenzen

Der Gewinn ist geschätzt, nicht gemessen. Hochrechnung mit Kosten pro Zugriff aus
der .26-Messung (Property-Read etwa 4–5 µs, UFunction etwa 12–15 µs): Omni-Idle
von rund 3,5 ms (.27) auf etwa 1,5–2 ms pro Update. Belegen muss es die
F10-Total-Messung im Spiel.
