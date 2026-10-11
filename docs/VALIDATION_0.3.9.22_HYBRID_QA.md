# 0.3.9.22 Hybrid QA – lokale Validierung

- 354 Tests ausgeführt: 350 erfolgreich, 4 bestehende übersprungen.
- 10 neue Registrierungstests: SDK-Collection-Append mit `False` trotz
  vorhandenem Hook, tatsächliche Ablehnung, irreführendes `True` ohne Hook,
  Teilfehler, SDK-Ausnahme, erneute Installation, stille Löschfehler,
  unvollständige Bereinigung und vorhandene fremde Identifikatoren.
- Der Collection-Append-Test reproduziert die fehlende Registrierung mit dem
  .21-Installer. Der .22-Installer besteht denselben Test.
- Ein neuer Loader-Test registriert die echten Callbacks bei `False`-Rückgabe,
  dispatcht PRE/POST mit lokalem Controller und passendem Pawn, prüft den
  `client_restart`-Lifecycle samt Zählern und die Entfernung beim Disable.
- Der Vergleich zu .21 zeigt ausschließlich Änderungen an den beiden
  Installations-/Entfernungsfunktionen in `camera_events.py`, dessen Import
  von `has_hook` und der Versionsmetadaten. Alle anderen Paketdateien und
  Kamera-Callback-Funktionen sind unverändert.
- SDKMOD: 102 Dateien, genau ein Root `BL4ThirdPersonPOC`. Python-Syntax,
  Archivintegrität und Paket-Payload werden vor Lieferung geprüft.

Geprüft unter Linux mit SDK-Stubs; kein Windows-Spieltest. Der lokale Nachweis
betrifft Registrierung, Dispatch und Cleanup. Visuelle Ankunftsübergaben
werden separat anhand des Spieltests bewertet.
