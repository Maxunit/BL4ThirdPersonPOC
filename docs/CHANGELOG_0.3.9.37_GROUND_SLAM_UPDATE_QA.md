# 0.3.9.37 – Ground Slam Update QA

Basis .36 (`54ee26b`). Die Distanzfunktion wurde dort in den bestehenden
Animations-Callback integriert. Dieser wird direkt auf BlueprintUpdateAnimation
registriert; die Integration erwartete jedoch das Widget-Argument InDeltaTime
und nahm bei dessen Abwesenheit null an. V4 nutzte den eigenen Widget-PRE und
hatte zusätzlich eine gemessene Delta-Fallback-Berechnung. Die .36-Tests riefen
die Berechnung manuell mit einem synthetischen Widget-Argument auf und prüften
diese unterschiedliche Registrierung nicht.

.37 registriert die Distanzberechnung am selben gefilterten eigenen Widget-
PRE wie V4. Der bestehende Kamera-/Animations-Callback übernimmt nur den Wert
im normalen Offset-Setter. Fehlendes Widget-Delta nutzt die Zeit zwischen den
eigenen Callbacks, ohne Timer oder feste FPS. Ein explizites null-Delta bleibt
null, und beide Quellen werden auf 0–0,1 Sekunden begrenzt.

Eine zusätzliche Widget-Subscription, kein neuer Producer oder nativer Patch.
Shutdown stellt eigene Exit-Daten wieder her und entfernt die Subscription
vor dem vorhandenen Producer. Fehlgeschlagene Entfernung bleibt retrybar und
macht den Callback inert. Distanz 0 / der deaktivierte Ground-Slam-Schalter
geben den Zustand frei, behalten aber die Subscription für späteres Aktivieren.

Da Widget und Animations-Callback getrennte Ereignisse sind, publiziert jeder
Kamera-Setter-Scope seinen frisch gelesenen Kameramodus. Ein zwischenzeitlicher
Wechsel nach GroundSlamExit, FPS oder eine unbekannte Scope kann keinen alten
TPS-Zusatz auf den Null-/Fremd-Offset anwenden.

F10 enthält eine zusätzliche read-only Logzeile: konfigurierter/aktiver Abstand,
Subscription, Zustand, Ground-Channel und Deltaquelle. Die Werte werden nicht
kontinuierlich aufgezeichnet. Standard 150 cm, Menübereich 0–250 cm und die
Oberkörperkorrektur bleiben erhalten. Root-Höhen- und Omni-Produktionsmodule
sind bytegleich zu .36; alle nativen Prefixes sind ebenfalls unverändert.
