# 0.3.9.17 – QA: eigene FKey-Kopien für den Eingabeadapter

Basis: vollständige 0.3.9.16 QA. Kein GitHub-Push.

## Nachweis aus dem Spiel

QA bestätigt: .16 dreht den Charakter beim Objektwurf noch nicht.
Der Omni-Report 173922 erkennt Carry_Throw und den Carry-Zustandswechsel,
aber keine Wurf-Episode. Die Vergleichsprobe 174439 enthält 475 Samples,
51 Ereignisse, keine Probe- oder Lese-Fehler und wurde sauber beendet.

In Updates 293 und 294 ist die frische, nicht ignorierte Carry_Throw-Zeile
gedrückt. Omnis bereits erfasste Werte melden in beiden Updates dagegen
`carry_throw=False`. Die Zuordnung zur Spielbelegung ist vorhanden. Das
ist kein ausreichender Beleg für die genaue Ursache im Speicher oder die
native Aktionszulassung: Beide Abfragen sind sequenzielle SDK-Snapshots.

## Gezielte Änderung

NativeBindings speichert bisher `row.Key` aus dem veränderlichen Mapping-Array.
Ab .17 übernimmt der Adapter beim Mapping-Scan eigene `FKey`-Kopien mit
`copy.copy()`. Es bleibt exakt der konfigurierte KeyName aus der Spielzeile.
Eine zurückgegebene Referenz auf dieselbe Struktur oder ein abweichender
KeyName wird verweigert. Reports kennzeichnen den Besitz mit `key_storage`.

Dies entfernt die über Callback-Grenzen gehaltenen Mapping-Key-Strukturen.
Es ändert alle Schlüssel-Snapshots dieses gemeinsamen Adapters, also auch
Sprint, Dash, Crouch, Jump, Fire, Zoom und Gadget. Digitale/analoge Abfrage,
einmaliger Frame-Cache, Mapping-Refresh, Owner-Prüfung und Trigger-Filter
bleiben unverändert. Keine neuen physischen Inputs, Ersatzbelegungen, Timer,
nativen Patches oder SDK-Hooks. Die Carry-Wurf-State-Machine bleibt .16.

## SDK-Prüfung

Die Primärquelle des SDK definiert `WrappedStruct.__copy__` als eigene
Python-Speicher-Kopie. Der native Kopierkonstruktor kopiert reflektierte
Properties; er ist kein garantierter Byte-Klon unreflektierter Strukturteile.
Die Eingabeparameter bleiben im bestehenden SDK-Aufrufweg.

- pyunrealsdk Commit `cb5fc362ea228727f334d94b64eb9538d8778bc6`,
  `src/pyunrealsdk/unreal_bindings/wrapped_struct.cpp`
- dessen unrealsdk-Untermodul `ac31716b2b462e78f0a841b6d352aa2fa56c7f92`,
  `src/unrealsdk/unreal/wrappers/wrapped_struct.cpp`

## Lokale Prüfung und Grenze

288 Tests: 284 bestanden, 4 plattformbedingte Skips. Sechs neue Tests prüfen
verfallende Mapping-Views, analoge Eingabe, Frame-Cache, gleich große Remaps,
ignorierte Zeilen und Fehler beim Kopieren. Das Modell verfallender Views
liefert mit .16 frische Eingabe=True / Adapter=False und mit .17 True/True.
Es simuliert eine Speicherlebenszeit; es beweist nicht deren Ablauf in BL4.

Replay der 475 echten Vergleichszeilen mit deren frischen Eingaben startet
eine Carry-Episode in Update 293, hält bis 301 und endet bei Kontextverlust
in 302. Das bestätigt die vorhandene State-Machine für diese Messwerte,
nicht die Wirkung der neuen SDK-Kopien im Spiel. Diese QA muss daher im
Spiel sowohl Carry-Wurf als auch die übrigen Eingaben nachprüfen.


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
