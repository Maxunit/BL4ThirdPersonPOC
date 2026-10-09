# 0.3.9.14 – QA: Hybrid ADS / Omni-Übergabe

Basis: vollständiger GitHub-Stand 0.3.9.13, Commit
`22c613606548ce62c27a289f02ebc1e17a308b24`.

## Behobener Ablauf

Waffe ausrüsten, ADS halten, Sprint drücken: 0.3.9.13 schaltete die Kamera
innerhalb von `read_combat()` auf `Default`. Die nachfolgende normale
TPS-Sample-Prüfung beendete Omni mit `LEFT_NORMAL_TPS`. Beide gelieferten
Berichte zeigen `scope_on`, `Default`, `normal_tps_sample=false` und die
anschließende Schutzabschaltung mit vollständiger Wiederherstellung.

- Omni stellt jetzt nur eine Anfrage für die bestehende Kamera-Stage
  `hybrid_scope`. Sie gehört zur aktuellen Gameplay-Sitzung und hält nur
  WeakPointer auf Controller, Pawn, Kamera und Waffe.
- Die Stage verbraucht die Anfrage einmalig und prüft Sitzung, Besitzer,
  Waffe, ADS-Route, gehaltenes ADS, Option und UI erneut. Eine verweigerte
  oder gescheiterte Anfrage wird nicht später erneut ausgeführt.
- Vor dem Scope-Wechsel deaktiviert die bestehende Special-Handoff-Routine
  Omnis native Verhaltens-Controls und stellt ersetzte Clips zurück.
- Der Scope verwendet die vorhandene Special-Pause mit Owner-Prüfungen.
  Die Sitzung und ihre Eingabeerkennung bleiben aktiv.
- Auch während der Rückkehr mit bereits gemeldetem `ThirdPerson` bleibt
  die Pause bestehen, solange `bIsTransitioning` wahr ist oder die gehaltene
  ADS-Route noch FPS ist. Danach gilt
  weiterhin die bestehende Freigabe für Sprint/Dash/Crouch/Jump. ADS darf
  für die Rückkehr zum Schulterzielen gehalten bleiben.
- Im Report sind diese Samples als `HYBRID_SCOPE_NATIVE_PAUSE` markiert;
  `hybrid_scope_pause_updates` zählt die entsprechenden Updates.

Keine neuen Hooks oder nativen Codeänderungen. Keine zusätzliche Zeitfrist
für den Zustandswechsel. Die vorhandenen visuellen Kamera-Blends bleiben.
Beam-, Throwable- und Sprint-Fire-Änderungen aus .12/.13 bleiben in diesem
gezielten Reparaturschritt erhalten und gelten dadurch nicht als live bestätigt.

## Prüfung und Grenzen

- 253 Tests unter Python 3.12.14: 249 erfolgreich, 4 plattformbedingte Skips.
- 12 neue Ablauf-Tests verbinden den echten `GameplaySession.frame()`-
  Special-/Combat-/Sampling-Pfad mit der Hybrid-Kamera-Stage. Sie bilden
  SDK-Objekte und native Worker nach; die nicht betroffene native
  Slide-/Dash-Installation und visuelle Diagnose sind ausgenommen.
- Der alte direkte Wechsel reproduziert im Harness `LEFT_NORMAL_TPS`.
- Geprüft: einmalige Ausführung, Scope-Pause, Rückkehr bei gehaltenem ADS,
  ADS-Loslassen, ignorierte Rückkehr, ungültige/stale Anfragen,
  Kamerawechsel-Fehler, FFYL/UI-Pause und weiterhin fatale Native-Prüffehler.
- Vorhandene Loader-Szenarien und Paket-Smoke-Test sind Teil der Testsuite.

BL4, Scope-Zoom, Scope-HUD und native Kamera-Blends können hier nicht live
ausgeführt werden. Der Spieltest steht aus; dies ist eine QA-Build.
