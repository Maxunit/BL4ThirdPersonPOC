# 0.3.9.31 – Summon-Ausrichtung beim Lichtschützen (Claude)

Basis: 0.3.9.30. Spielbefund zu .30:

- Ausstieg aus Fahrzeugen mit sichtbarem Fahrer: Richtung passt.
- Korrektur zu .30: Der Ausstiegsfehler war kein Rückschritt aus .29. Er bestand
  schon in früheren Versionen (gegengetestet).
- Sonderfall **Lichtschütze** (Light Gunner): Die Figur ist in diesem Fahrzeug
  nicht sichtbar. Kamera nach Norden, Figur nach Süden, Fahrzeug rufen: Das
  Fahrzeug steht nach Norden. Mit der Figur nach Osten oder Westen stimmt es.

## Befund

So arbeitet die Summon-Ausrichtung (seit 0.3.9.19):

1. Beim Rufen liefert der Getter-Stub dem Summon-Aufrufer die Richtung der Figur
   statt der Kamerarichtung. Das Fahrzeug erscheint also in Figurrichtung.
2. Beim Einsteigen behält der Possession-Stub die Kamera.
3. Bei Radfahrwerken hält der Boot-Stub die Lenk-Sollrichtung (`DesiredYaw`) auf
   der Summon-Richtung, bis die kamerarelative Steuerung übernimmt.

Seitlich klappt es auch beim Lichtschützen. Schritt 1 greift also, das Fahrzeug
erscheint richtig. Nur wenn die Kamera hinter dem Fahrzeug steht, dreht es sich
zur Kamera. Das passt zu einem Fahrzeug, dessen Rumpf der Blick- bzw.
Waffenrichtung folgt, sobald sie einen Schwenkbereich verlässt (zwischen 90° und
180°). Diese Logik liest die Kamerarichtung an einer Stelle, die Omni nicht hält.

Klasse, Fahrwerk und Lesestelle des Lichtschützen sind offline unbekannt. Die
Ursache ist aus dem Spielbefund abgeleitet, nicht gemessen.

## Änderungen

1. **Kamera hinter den Lichtschützen** (`omni/summon_seat.py`). Alle Bedingungen
   müssen erfüllt sein:
   - Frischer Summon-Datensatz des Getter-Stubs (höchstens 300 Updates alt).
   - Die Figur sitzt in 3 aufeinanderfolgenden Updates nicht sichtbar am Steuer:
     kein oder ein anderer Fahrer (`DriverPawn`), Actor versteckt (`bHidden`) oder
     Mesh unsichtbar.
   - Die Kamera steht mehr als 90° von der Summon-Richtung weg.

   Dann setzt Omni einmal pro Einstieg die Kamera auf die Summon-Richtung
   (`SetControlRotation`, Neigung bleibt). Unverändert bleiben: sichtbarer Fahrer
   (alle normalen Fahrzeuge), seitliche Lücken bis 90° und Einstiege ohne Summon.
2. **Summon-Trace** `[OmniVehicle] summon …`, eine Zeile pro Einstieg nach 90
   Updates oder beim Aussteigen:
   - `cls`, `vehicle`, `mesh`, `movement`: Fahrzeugklasse, Objekt, Mesh-Asset, Fahrwerk
   - `possession`, `boot_hold`: Ergebnis des Possession-Stubs und ob der Boot-Hold
     für dieses Fahrzeug aktiv war
   - `seat`: Zustand im ersten Update, `visible_driver` oder der Grund für „nicht
     sichtbar“ (`no_driver`, `other_driver`, `actor_hidden`, `mesh_hidden`);
     `hidden_from`: erstes Update mit einem solchen Grund
   - `target`, `summon_camera`, `ticket_age`: Summon-Richtung, Kamera beim Rufen,
     Alter des Datensatzes
   - `align`: `f2:0>180` (Kamera in Update 2 von 0° auf 180°), `kept_gap_…`,
     `visible_driver` oder `no_summon_ticket`
   - `turn_frame`: erstes Update, in dem das Fahrzeug mehr als 15° von der
     Summon-Richtung abweicht
   - `timeline`: Fahrzeug/Kamera/`DesiredYaw` in den Updates 0, 1, 2, 3, 5, 10, 20, 40, 89

   Das Fenster öffnet sich für jeden Pawn außer der Figur, der das eigene Fahrzeug
   ist oder auf einen frischen Summon folgt, unabhängig vom Klassennamen. Report:
   `vehicle_handoff.summon_seats` (letzte 8).
3. `hitch.text()`: fehlertolerante Textwerte für Trace-Zeilen.

## Grenzen

- Erkennt Omni die Figur im Lichtschützen auf keinem der drei Wege als
  unsichtbar, greift die Ausrichtung nicht. Die Trace-Zeile zeigt dann
  `seat=visible_driver` und kein `hidden_from`. Die nächste Version kann den
  Lichtschützen über `cls` oder `mesh` aus dieser Zeile erkennen.
- Dreht sich das Fahrzeug schon vor Update 2 (`turn_frame` 0 oder 1), dreht die
  Kamera es danach zurück. Das wäre als kurzes Hin und Her sichtbar.
- Beim Lichtschützen dreht sich die Kamera in diesem Fall mit, statt stehen zu
  bleiben. Anders lässt sich der Rumpf ohne die unbekannte Lesestelle nicht halten.

## Kosten

Zu Fuß ohne offenes Fenster keine zusätzlichen Zugriffe. Im Fenster pro Update ein
UFunction-Aufruf und rund 8 Property-Reads, höchstens 90 Updates pro Einstieg.

## Unverändert

Native-Stubs (Templates und Hashes), Ausstiegslogik aus .30, alle Fahrzeuge mit
sichtbarem Fahrer.
