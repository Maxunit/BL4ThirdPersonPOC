# 0.3.9.33 – lokale Validierung

517 Tests: 513 erfolgreich, vier übersprungen wegen fehlender optionaler
Keystone-/Capstone-Pakete. Befehl:
`python3 -m unittest discover -s tests -p 'test_*.py'`.
Die GNU-/x64-Tests der neuen Fassung wurden ausgeführt, nicht übersprungen.
Vollständige Ausgabe: `TEST_OUTPUT_0.3.9.33.txt`.

24 neue Tests prüfen unter anderem den stetigen, symmetrischen Winkelübergang,
±180°-Wrapping, Nicht-finite-Werte, aktuelle Post-Setter-Body-Richtung, Verhalten
bei Kampf/Idle/Crouch/Handoff/Dash, geschlossene Gates, den tatsächlichen
Frame-/Handoff-Pfad, geerbte Owner-Prüfung und Restore.

Native Präfixquelle mit GNU assembler neu gebaut und bytegleich zur verwendeten
Vorlage geprüft; kein Keystone/Capstone zur Laufzeit erforderlich. Die wirklichen
Präfixbytes werden über eine Linux-x64-ABI-Testfixture ausgeführt:

- Standing/Crouch-Nodes getrennt, passender und fremder Receiver/Caller;
- Mode 0/1/2, unbekannter Modus und Null-Vektor;
- Yaw-Limit und Pitch-Faktor über 361 Winkelwerte;
- korrupte Pakete und ungültiger ursprünglicher Pitch ohne Schreibzugriff;
- unveränderte XMM0–2, GPRs, Stack, Flags und MXCSR, Roll und Puffergrenzen;
- 2.000 parallele Aufrufe, atomare Zähler und kohärente Paketpaare;
- lebenslang gepinnter Crouch-Control und ausgerichtetes Publikationswort.

`SDK_COUNTS_0.3.9.33.json` vergleicht die .32 und .33 in je 600 Updates für
Stehen, Ducken, Laufen und Drehen. Alle erfassten SDK-/Owner-/Read-Zahlen und
Spiel-Schreibzahlen sind identisch. Die neue Python-Winkelberechnung und native
Arithmetik sind zusätzliche Arbeit; aus den Zähltests folgt keine FPS-Garantie.

110 Produktionsdateien: vier gegenüber .32 geändert (Loader, Metadaten,
`omni/session.py`, `omni/ground.py`), zwei hinzugefügt (`free_look.py`,
`native_free_look.py`). Die übrigen 104 Dateien sind bytegleich, insbesondere die
.32-Fahrzeugkorrektur und die ursprünglichen geprüften Native-Klassen. Der
bisherige V3-Audit-Test bleibt unverändert und besteht.

Paketprüfung: ein Loader-konformer Root, CRC, Versionsangaben sowie exakte
Quell-/Archiv-Übereinstimmung. Manifest: `PACKAGE_SHA256_0.3.9.33.json`.
Linux/SDK-Ersatzobjekte ersetzen keinen Live-Spieltest auf Windows. Sichtbare
Spine-Drehung, BlendSpace-Skalierung und Kamera-/Animationsübergänge müssen im
Spiel bestätigt werden. Diese Fassung ist eine QA-Build.
