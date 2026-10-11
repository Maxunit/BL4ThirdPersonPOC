# 0.3.9.37 – lokale Validierung

569 Tests, 564 bestanden und fünf optionale übersprungen:
`python -m unittest discover -s tests -p 'test_*.py' -v`.
Vollständige Ausgabe: `TEST_OUTPUT_0.3.9.37.txt`.

Der .36-Fehler wurde vor der Änderung lokal reproduziert: Dem bisherigen
Loader-Szenario wurden Animations-Argumente (DeltaTimeX statt InDeltaTime)
gegeben. Trotz aktivem langen Slam blieb der tatsächliche rohe Setter-Offset
bei (45,55,10) statt (-105,55,10) für 150 cm Zusatz.

Das Loader-Szenario ruft nun die wirklich registrierten Callbacks auf:
eigener Widget-PRE mit InDeltaTime und separat registrierter Animations-POST
mit DeltaTimeX. Fremde Widget-Adressen werden ausgeschlossen, nur der eigene
Widget-Tick verändert die berechnete Distanz, der Animationspfad führt den
echten Kamera-Updater samt scoped Setter aus. Die übrigen Gameplay-Stages
sind hier isoliert, nicht als vollständige Engine-Simulation nachgebildet.
150 cm werden erreicht, die Bodenannäherung liefert null, Root aus funktioniert,
und tatsächlicher Loader-Shutdown entfernt Route und Zustand.

Neue Regressionen: fehlendes Delta verwendet gemessene Callback-Zeit;
explizites null-Delta bleibt Pause; ein Fremdmodus zwischen den Callbacks
erhält keinen alten Zusatz; fehlgeschlagene Entfernung bleibt retrybar und
der Callback inert. Die .36-Tests für Pose, Native-X-Handoff, sechs Messreplays,
ADS, Fahrzeuge, Root, Menüstandard und Shutdown bestehen weiterhin.

Kein Live-Spieltest der .37 hier möglich. Die nachgewiesene Null-Delta-
Abweichung ist korrigiert; sichtbare Funktion, Terrain und FPS benötigen QA.
Ein zusätzlicher Callback gehört zum bereits bestehenden Widget-Producer;
er führt die eigenen serial-/thread-geprüften SDK-Abfragen aus. Ein FPS-Gewinn
wird nicht behauptet. Keine neue native Codeänderung.

Paket-CRC, Loader-Root, Metadatenversionen und jede Produktionsdatei werden
vor der Ausgabe mit dem Quellstand verglichen. Hashes:
`PACKAGE_SHA256_0.3.9.37.json`.
