# 0.3.9.19 QA – Omni-Neuaufbau und Fahrzeugübergänge

Basis: 0.3.9.18. Diese Build führt die getrennt getesteten Performance- und
Fahrzeugproben zusammen. Die kombinierte Build benötigt noch Gameplay-QA.

- Beim Omni-Neuaufbau teilen sieben Binder ihre Animationsmetadaten innerhalb
  eines Aufrufs. Geordnete Namens- und Struct-Indizes bewahren Duplikate und
  unbekannte Idle-Nodes für die bisherigen Prüfungen.
- Ein Cache für genau eine Animationsklasse bewahrt primitive Metadaten und
  schwache UStruct-Referenzen. Jeder neue Bind prüft aktuelle Objektidentitäten,
  die vollständige Vererbung und frisch gelesene, geordnete Property-Adressen.
  FField-Wrapper, Pawns und Animationsinstanzen werden nicht über Binds behalten.
- Der vollständige Bone-Katalog wird einmal vom Head-Binder an den Visual-Binder
  derselben Sitzung übergeben. Mesh-, Animations-, Asset- und Bone-Count-Prüfungen
  bleiben live. Änderungen oder ein fehlender Asset-Getter führen zum frischen Scan.
- Bekannte native Omni-Patch-Ziele können innerhalb eines Bind-Aufrufs eine
  geprüfte Image-Region teilen. Die erste Abfrage bleibt frisch; eine zweite
  startet am niedrigsten geprüften Ziel. Nur bekannte, abgedeckte Ziele innerhalb
  einer einzelnen Live-Speicherseite dürfen Ergebnisse wiederverwenden.
- Vor jedem dadurch freigegebenen Code-Schreibvorgang wird der tatsächliche alte
  Seitenschutz nach VirtualProtect und vor dem Kopieren verglichen. Abweichungen
  verhindern das Kopieren; das ursprüngliche finally stellt den alten Schutz
  wieder her. Byte-/Build-/Vtable-/Owner- und Readback-Prüfungen bleiben erhalten.
- Mit Omni und der bestehenden **kamera-relativen Fahrzeugsteuerung** übernimmt
  der gemessene eigene Fahrzeug-Einstieg die zuletzt beobachtete Bewegungsrichtung.
  Der Possession-Pfad bewahrt die Controller-/Kamerarotation. Die Einstiegsausrichtung
  bleibt aktiv, bis die Fahrsteuerung ihren Befehl für denselben Receiver veröffentlicht.
- Der frühe Fahrsteuerungs-Bind ist an dieses eigene Possession-Ticket gebunden.
  Die reguläre Installation prüft auch beim ersten Einstieg nach Spielstart den
  Build, native Bytes, Reflection und Dispatch vor dem Schreiben. Dieser erste
  Einstieg war in den alten Proben nicht abgedeckt und ist ein gezielter QA-Punkt.
- Beim eigenen Fahrzeugausstieg richtet sich der Körper zunächst nach der zuletzt
  beobachteten horizontalen Fahrzeugbewegung aus; ohne beobachtete Bewegung wird
  die Fahrzeugausrichtung verwendet. Der native Abwurfimpuls bleibt erhalten.
- Ein eng begrenzter TurnState-Eingriff erhält diese Körperausrichtung bis zur
  bestätigten Omni-Übernahme. Danach kann Omni den Körper bereits im Fall drehen.
  Voraussetzung sind gepaarte ClientRestart-Aufrufe, derselbe Character, aktuelle
  Weapon-/Animation-/OnFoot-Handler und die bisherigen Kamera-/Input-/Bewegungsprüfungen.
- Fahrzeugprüfungen und volle native Readbacks erfolgen an Übergängen. Normale
  Leerlauf-Updates enthalten keine Fahrzeug-Speicherabfragen oder Kamera-Diagnosegetter.
  Native Templates prüfen weiterhin jeden tatsächlichen Eingriff. Begrenzte
  Scratch-Puffer werden nur auf dem eigenen GameThread bei passenden geschlossenen
  Freigaben zurückgesetzt. Es gibt keine zeitgesteuerte Fahrzeug-Haltephase.
- **Hybrid ADS ist in dieser QA gesperrt**, auch mit einer gespeicherten aktiven
  Einstellung. Die ursprüngliche ADS-Bedienung bleibt verfügbar.

Die umfangreiche Messinstrumentierung, A-B-B-A-Umschaltung und Python-GC-Beobachtung
der Proben sind nicht Bestandteil des Gameplay-Codes. Bounded Zähler und
Übergangsereignisse sind im gewöhnlichen Omni-Report verfügbar.

## Nachweise und Grenzen

Die letzte Fahrzeugprobe zeigte B-Callbacks von 41,02/44,36 ms gegenüber dem
aufgewärmten A-Callback mit 49,82 ms. Fast Travel zeigte 40,49/39,42 ms gegenüber
53,71 ms. Diese Zahlen gehören zu den instrumentierten Proben, nicht zu einer
Messung dieser kombinierten Build oder der gesamten gerenderten Frames.

Gezielte Respawn-Performance-QA wurde wegen der Spielgeldkosten auf einen ohnehin
auftretenden Respawn verschoben. Karten-/Pawn-/Controllerwechsel, erster Einstieg,
weitere Fahrzeugtypen und die kombinierte Performance müssen im Spiel geprüft werden.
Die Cache-Annahme betrifft unveränderte cooked Reflection-Schemata: ein fremder Mod,
der Metadaten an identischen FField-Adressen live umschreibt, ist damit nicht geprüft.
Speicherabfragen und Protection-Checks sind keine Sperre gegen fremde parallele
Image-Ummappings. Die Wiederverwendung bleibt deshalb auf den eigenen kurzen Bind
und bekannte einzelne Seiten begrenzt.
