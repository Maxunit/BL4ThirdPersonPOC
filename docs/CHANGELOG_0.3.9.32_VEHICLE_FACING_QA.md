# 0.3.9.32 – Fahrzeugausrichtung beim Rufen und Aussteigen

Basis: Repo-.31, Commit `001a62a45d7f9307f1b91088e7b25bfba63d0941` in
`Maxunit/BL4ThirdPersonPOC`. Die Repo-.28/.29 sind eigene Callback-Scope-/Bind-
Builds; sie entsprechen nicht den früher in diesem Chat getesteten Batch- bzw.
Sampling-Builds mit denselben Versionsnummern.

## Gemeldete Fehler und gewünschtes Verhalten

- Fahrzeug rufen, W/S/A/D kurz antippen, direkt aussteigen: Figur steht oft
  in einer anderen Richtung als das Fahrzeug.
- Gerufenes Fahrzeug steht gelegentlich anders als die Figur zuvor.
- Für den Ausstieg wurde Fahrzeugausrichtung bestätigt, auch bei Rückwärtsfahrt
  oder einer seitlichen Bewegung des Fahrzeugs.

## Zwei widersprüchliche Richtungsquellen in .31

`ExitFacing.publish_vehicle` wählte ab 150 cm/s weiterhin die waagerechte
Geschwindigkeitsrichtung. Bei Rückwärtsfahrt, seitlicher Fahrt, Drift oder
einem kurzen Steuerimpuls kann sie erheblich von der Fahrzeugrotation abweichen.
Die Geschwindigkeitsgrenze aus .30 korrigierte nur stehende/kriechende Fahrzeuge.

`SummonFacing.frame` übernahm die letzte native Movement-Eingaberichtung. Das
ist das Ziel der Bewegung und nicht die momentan erreichte Actor-Rotation.
Zudem blieb die gespeicherte Summon-Richtung ohne aktive Eingabe erhalten,
auch wenn ein Fahrzeugausstieg inzwischen die Actor-Rotation geändert hatte.

Diese Abweichungen sind im Code nachweisbar. Ob zusätzlich eine spätere
Fahrzeug-/Kamera-Übergabe beteiligt ist, muss der Spieltest zeigen.

## Änderungen

1. Der Ausstiegs-Publisher verwendet bei jedem Tempo die aktuelle
   `K2_GetActorRotation().Yaw` des eigenen Fahrzeugs. Velocity wird weiterhin
   für den Report gelesen und geprüft; sie bestimmt die Ausstiegsrichtung nicht.
   Quelle im Report: `vehicle_body_orientation`.
2. Der Summon-Publisher liest in jedem zugelassenen On-foot-Update die aktuelle
   Figurenrotation über den vorhandenen `rot_yaw`-Leser. Das gilt auch ohne
   Bewegungseingabe und nach einem Fahrzeugausstieg. Quelle:
   `current_character_body`. Das ersetzt einen Input-Getter durch einen
   Actor-Getter; keine zusätzliche On-foot-UFunction-Abfrage.
3. `[OmniVehicle] exit` und `vehicle_handoff.exit_facings` lesen den angewandten
   Winkel aus dem bestehenden Native-Scratch-Datensatz. In .31 wurde unter
   `applied_yaw` nur der zuletzt vom Python-Publisher gehaltene Winkel angezeigt.

| Feld | Bedeutung |
| --- | --- |
| `applied_yaw` | Vom nativen Ausstieg tatsächlich eingesetzter Winkel |
| `published_yaw` | Zuletzt vom Publisher beobachteter Zielwinkel |
| `native_original_yaw` | Ursprünglicher Winkel der nativen Ausstiegsberechnung vor dem Override |
| `native_camera_yaw` | Controller-Kamerawinkel beim nativen Ausstieg |
| `publication_update`, `publication_sequence` | Zugehörige Veröffentlichung und Sitzfolge |
| `publication_age_updates` | Vehicle-Updates zwischen Veröffentlichung und Lesen des Exit-Datensatzes |
| `character_yaw` | Figurenwinkel beim späteren Lesen des Exit-Datensatzes |
| `native_record_error` | Diagnosefehler; kein Einfluss auf Gameplay oder Handoff |

Der vorhandene 128-Byte-Datensatz wird unverändert gelesen; keine neue native
Adresse, kein veränderter Stub und kein weiterer Hook. Trace/Reports bleiben
begrenzt und verwenden weiterhin die bestehende .31-Infrastruktur.

## Grenzen und Kosten

- Die Veröffentlichung erfolgt im vorhandenen Vehicle-POST. Sie ist eine
  Beobachtung aus einem Update, kein atomarer SDK-Getter im nativen Summon- oder
  Ausstiegsmoment. Die zusätzlichen Reportwerte helfen, alte Veröffentlichungen
  oder eine spätere Änderung der Figurenrichtung zu erkennen.
- Die eigentliche Figurenanimation kann von ihrer Actor-Rotation abweichen;
  dieser Build orientiert sich an der Actor-Rotation.
- Die Lichtschützen-Kamera-Korrektur aus .31 bleibt enthalten. Eine zusätzliche
  kamerabhängige Fahrzeugdrehung wird durch diese Quellenkorrektur nicht
  automatisch ausgeschlossen.
- Bei schneller Fahrt kommt im Exit-Publisher nun auch der Actor-Getter hinzu,
  den .31 nur unter 150 cm/s aufrief. Das ist der Preis der gewünschten
  Fahrzeugausrichtung. Es wird kein FPS-Gewinn behauptet.

Unverändert: Callback-Scope, Bind-Staffelung, Combat-/Input-Optimierungen,
Summon-/Possession-/Boot-Stubs, Native-Adressen/Templates/Hashes sowie
Installation, Guards und Cleanup. `pyproject.toml` wird vom veralteten .24-Eintrag
auf .32 synchronisiert; Loader-Version ebenfalls .32.
