# Gezielter QA-Lauf 0.3.9.14

Spiel vollständig beenden und alte Mod-Dateien/Caches wie gewohnt entfernen.
Entweder `dist/BL4ThirdPersonPOC.sdkmod` oder den Mod-Ordner installieren,
nicht beide. Save laden und TPS/Omni aktivieren.

Für diesen Test in der Oak2-Konsole:

```
bl4tps_omni diag on
bl4tps_omni on
bl4tps_omni hybrid on
```

Konsole schließen und kurz normale Bewegung prüfen. Während der eigentlichen
Eingabefolgen geschlossen halten: die Konsole blockiert Spieleingaben.
Die folgenden Angaben meinen die im Spiel belegten Aktionen; in der getesteten Tastaturbelegung
sind dies RMB für ADS und Shift für Sprint.

1. Eine normale Schusswaffe ausrüsten. ADS halten, Shift kurz drücken und
   loslassen. Erwartet: Wechsel zur FPS-Sicht ohne Omni-Schutzabschaltung.
   Scope-Zoom und HUD gesondert beobachten und berichten.
2. ADS weiterhin halten. Shift erneut drücken, bei der Rückkehr kurz halten,
   dann loslassen. Erwartet: Schulterzielen kehrt zurück; der Charakter bleibt
   beim Zielen zur Kamera ausgerichtet. Kein `LEFT_NORMAL_TPS`, kein
   `UNSUPPORTED_CAMERA_MODE`.
3. Wieder den Scope öffnen. ADS loslassen. Danach mit A/S/D bewegen.
   Erwartet: TPS kehrt zurück und normale Omni-Ausrichtung funktioniert.
4. Im Scope die Waffe wechseln, dann ADS loslassen. Erwartet: kein
   dauerhafter Bewegungs-Lock und keine Schutzabschaltung. Falls Scope/HUD
   nach dem Wechsel anders aussehen, separat beschreiben.
5. Hybrid abschalten (`bl4tps_omni hybrid off`), ADS und Sprint sowie
   normale Bewegung prüfen. Danach bei Bedarf wieder einschalten.

Danach in der Konsole:

```
bl4tps_omni status
bl4tps_omni report
```

Die `OMNI_REPORT json=...`-Zeile nennt den Snapshot-Pfad. JSON und relevante
Log-Zeilen zur Auswertung bereitstellen. Im Snapshot sollte `current_gameplay` weiterhin
aktiv sein, Scope-Ein-/Austritte enthalten und die Pause unter
`HYBRID_SCOPE_NATIVE_PAUSE` zeigen. Öffnen der Konsole erzeugt zusätzlich
eine erwartete UI-Pause.

Falls Omni unerwartet stoppt: zuerst den Report sichern und den genauen
Ablauf nennen. Für den Nachweis nicht sofort neu einschalten.

Dieser Lauf beurteilt die Hybrid-/Omni-Übergabe. Throwable-Rotation und
Beam-Tiefe werden danach gezielt getrennt untersucht.
