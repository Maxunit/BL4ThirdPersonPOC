# 0.3.9.30 – Ausstiegsrichtung und Richtungs-Trace

Basis: 0.3.9.29. Spielbefund: Nach dem Holen eines Fahrzeugs und dem Aussteigen
schaut die Figur entgegengesetzt (vorn → hinten, rechts → links), teils jedes
Mal anders.

## Befund

Die Ausstiegsrichtung setzt der Native-Stub aus `ExitFacing.publish_vehicle`.
Bisher galt: Sobald die Fahrzeuggeschwindigkeit numerisch nicht null war,
bestimmte ihre Richtung die Ausstiegsrichtung, ohne Mindesttempo. Ein frisch
gerufenes oder stehendes Fahrzeug hat aber fast immer etwas Restbewegung
(Absetzen, Federung, leichtes Zurückrollen). Die Richtung dieses Rauschens ist
beliebig, beim Zurückrollen genau entgegengesetzt. Das passt zu „jedes Mal
anders“ und zu „immer umgekehrt“.

Die .29-Änderungen im Fahrzeugpfad (Messpunkte, gleichwertige Identitätsprüfung)
greifen nicht in die Richtung ein. Der Testplan von .29 (mehrmals direkt
hintereinander ein- und aussteigen) macht den Fall aber besonders häufig.

## Änderungen

1. **Mindesttempo für die Fahrtrichtung:**
   - Ab 150 cm/s waagerecht (~5,4 km/h) bestimmt weiter die Fahrtrichtung den
     Ausstieg, auch rückwärts und beim Driften.
   - Darunter gilt die aktuelle Fahrzeug-Ausrichtung, also auch nach dem Anhalten.
   - Quelle im Report: `vehicle_travel_direction` oder `vehicle_body_below_travel_speed`.
2. **Richtungs-Trace** (Konsole, höchstens 48 Zeilen pro Spielsitzung, zusätzlich
   im Report unter `hitches.notes`):
   - `[OmniVehicle] seated`: Fahrzeug-Yaw, Kamera-Yaw und Summon-Ziel beim Einsteigen
   - `[OmniVehicle] exit`: angewandter Yaw, Quelle, Tempo, Figuren- und Kamera-Yaw
   - `[OmniVehicle] air_rebind`: Figuren-Yaw, wenn Omni im Ausstiegssprung übernimmt
   - `[OmniBind] ready`: Figuren- und Kamera-Yaw, wenn das gestaffelte Binden fertig ist

   Alle Werte werden fehlertolerant gelesen. Ein Trace kann das Gameplay nicht stoppen.
3. Report `vehicle_handoff.exit_facings`: die letzten 16 Ausstiege mit denselben Werten.

## Grenzen

Die Ursache ist aus dem Code abgeleitet, nicht im Spiel gemessen. Zeigt die
Figur trotzdem falsch, belegen die Trace-Zeilen, an welcher Stelle der Yaw kippt
(Summon, Ausstieg, Übernahme durch Omni).
