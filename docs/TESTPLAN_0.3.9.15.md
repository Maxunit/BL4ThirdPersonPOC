# Gezielter QA-Lauf 0.3.9.15

Spiel vollständig beenden und Mod/Caches wie gewohnt austauschen.
`dist/BL4ThirdPersonPOC.sdkmod` aus dieser Build installieren. Alternativ
den Mod-Ordner verwenden; nur eine der beiden Varianten installieren.
Save laden und TPS/Omni sowie Hybrid ADS aktivieren. Die folgenden Angaben
meinen die im Spiel belegten Aktionen, im Test ADS = RMB und Sprint = Shift.

1. Dieselbe Waffe wie im letzten Test verwenden. ADS halten, kurz Shift
   drücken und loslassen: FPS-ADS. ADS weiterhin halten, erneut Shift
   drücken und loslassen: TPS-ADS. Drei- bis viermal wiederholen.
   Erwartet: Rückweg direkt zum milden TPS-Zoom und zur ADS-Annäherung,
   ohne sichtbaren Zwischenstopp bei Hüft-Zoom und ohne erneute Zoomfahrt.
2. Noch einmal zum Scope wechseln. Beim Rückweg nach Shift ADS loslassen.
   Erwartet: normaler Rückweg zur Hüftkamera, kein hängen gebliebener Zoom;
   anschließend normales Omni Movement und ein frischer ADS-Einstieg.
3. Im Scope die Waffe wechseln und ADS loslassen. Erwartet: kein alter
   TPS-Zoom auf der anderen Waffe und keine dauerhafte Bewegungssperre.

Konsole während der Eingaben geschlossen halten. Unmittelbar danach:

```
bl4tps_omni status
bl4tps_omni report
```

Die JSON aus der `OMNI_REPORT json=...`-Zeile und auffällige Log-Zeilen an
zur Auswertung bereitstellen. Dazu kurz beschreiben, ob der Zoom-Reset verschwunden ist und
bei welcher Eingabefolge er gegebenenfalls noch auftritt. Die begrenzten
`hybrid_fov_events` werden auch mit `diag off` aufgezeichnet.

Erwartete Belege: Scope-Eintritt (`SCOPE_ON`), angefordertes gehaltenes
TPS-Ziel während der Rückkehr (`RETURN_TARGET`) und übernommenes gehaltenes
TPS-ADS (`TPS_HOLD_RESUMED`, kein neuer `zoom_in`). Beim Loslassen während
der Rückkehr kann `RETURN_CANCELLED` erscheinen. POV-FOV und Offset sind
getrennte Werte; sie sind nicht gleichzusetzen.

Falls Omni stoppt, vor dem erneuten Einschalten einen Report sichern. Dieser
Test betrifft nur den Hybrid-Rückweg; die weiteren Reparaturen folgen einzeln.
