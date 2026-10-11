# 0.3.9.35 – Root Height QA

Auslöser: Auf Geländern, Kisten und schmalen Hindernissen sitzt die sichtbare
Figur teilweise tiefer, während die TPS-Kamera am Kapsel-/Actor-Bezug bleibt.
Drei .34-Messreihen mit je 600 Updates zeigen eine anhaltende Skelett-Root-
Absenkung um ungefähr 43–44 Einheiten. Mesh-Komponentenoffset und Kamera-Anker
bleiben gleich. Der Wechsel zeigt zusätzlich eine getrennte Oberkörperkompression
beim Landen und die Rückkehr der Root-Höhe nach dem Abstieg. IK ist als Ursache
weiterhin nicht bewiesen; Ground Slam wurde in diesen Reihen nicht erfasst.

## Kamera-Verhalten

SDK-Referenz: `Root.Z - MeshWorld.Z + CurrentFloor.FloorDist`. In den gemessenen
normalen Standposen entspricht Root ungefähr dem Mesh-Ursprung minus Bodenabstand.
Die Geländerpose weicht davon deutlich nach unten ab. Diese laufende geometrische
Referenz funktioniert auch beim Start auf dem Geländer, ohne zuerst dort eine
falsche Normalhöhe einzulernen. Kein fest hinterlegter Geländer-Versatz und keine
fortlaufende Pose-Baseline, die den Höhenfehler wieder wegadaptiert.

Normales Grounded TPS folgt negativen Abweichungen über zwei Einheiten. Die
zusätzliche Kamera-Höhe nähert sich dem Ziel pro bestehendem Update mit 20 % an
und wird unter 0,02 Einheiten auf null gesetzt. QA-Schranke: maximale zugelassene
Absenkung 80; positive Root-Auslenkung höchstens 8; gültiger, blockierender und
begehbarer Bodenabstand 0–8. Nichtfinite/fehlende/abweichende Daten verweigern
die neue Korrektur mit einer Meldung bei Änderung des Fehlers.

Die Verschiebung ist in Welt-Z. Sie wird mit Kamera-Pitch und -Roll auf den
lokalen Kameraoffset zurückgerechnet, einschließlich ±90° Pitch ohne Division.
Schulter-, Respawn-, FFYL- und Hybrid-Fades bleiben in ihrer bestehenden
Kompositionsreihenfolge. Kameraoffsets außerhalb des laufenden TPS-Aufrufs
bekommen keine Root-Korrektur. Figur, Kapsel, Skelett und Steuerrotation werden
nicht geschrieben. Die vorhandene Kollisionskamera bleibt zuständig.

Motion Camera entfernt die rohe Root-Translation aus ihrer Z-Messung. Die
Oberkörperkompression beim Landen bleibt enthalten. Wechsel zwischen relativer
und bisheriger Messweise richten die Motion-Baseline um, ohne eine künstliche
Posebewegung auszulösen. Vorhandene Stärke-, Filter- und Limit-Einstellungen
bleiben bestehen. Die neue Grundhöhenkorrektur funktioniert mit Motion aus.

Beim Fallen und Ducken wird kein neues Absenkungsziel gesetzt; ein vorhandener
Zusatz läuft aus. ADS, Fahrzeuge, Shops, Slide, Leiter/Mantle, FFYL,
Kamera- und Lifecycle-Übergänge sowie fremde/custom Movement-Modi sperren die
Korrektur. Ground-Slam-Kameramodi sind durch das bestehende TPS-Gate gesperrt.

## Eigentum, Diagnose und Kosten

Die existierende eigene Kamera-Updatefunktion besitzt einen kurzen Frame-Scope.
Actor-, Mesh- und Spine3-Werte werden aus der vorhandenen Mantle-Abfrage geteilt.
Ein zusätzlicher Root-Socket-Getter ist nötig, während Motion zwei bisherige
Doppelabfragen einspart. Floor-/Mode-/Weak-/Runtime-Prüfungen haben eigene Kosten;
aus UFunction-Zahlen folgt keine FPS-Aussage. Auf abgesenkten Flächen wird der
bestehende Offset-Setter zusätzlich benutzt. Keine neuen Update-Produzenten,
Hooks, Timer, nativen Leser oder Patchsites.

Serial-geprüfte WeakPointer binden Controller, Pawn, Manager und Mesh. Änderungen
oder abgelaufene Referenzen starten mit neutraler Höhe neu. SDK-Reentry beim
Root-Lesen verwirft den alten Frame; der finale Setter prüft seine aktuelle
Runtime nochmals gegen den Scope. Enable/Disable löschen die Höhe, Scope und
Frame-Samples. Root-Höhe ist unabhängig von den nativen Wiederherstellungen.

Neuer persistenter Schalter im Kamera-Menü: **Grounded Body Height (QA)**,
Standard an, sowie `bl4tps_root_height on|off|status`. Höhe/Status erscheinen
lesend in der .34-Diagnose. Alle Omni- und nativen Produktionsmodule sind
bytegleich zu .34. Basis: lokaler .34-Checkpoint `1ba29a7`, keine Veröffentlichung.
