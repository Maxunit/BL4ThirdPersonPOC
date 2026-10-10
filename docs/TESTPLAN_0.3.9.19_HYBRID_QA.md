# 0.3.9.19 Hybrid QA – gezielte Bug-Inventur

## Installation und Aktivierung

Spiel beenden, die bisherige Mod wie gewohnt ersetzen und Bytecode-Caches entfernen.
`dist/BL4ThirdPersonPOC.sdkmod` nach `sdk_mods` kopieren; keine zweite entpackte
BL4ThirdPersonPOC-Version daneben. Der SDKMOD-Dateiname muss unverändert bleiben.
Die Variantennummer im Loader bleibt 0.3.9.19.

Omni einschalten, auf dem Boden kurz laufen und das Binden der Gameplay-Sitzung
abwarten. Hybrid dann im Menü einschalten oder `bl4tps_omni hybrid on` verwenden.
`bl4tps_omni hybrid status` zeigt Option/aktive Sitzung, Scope-Zustand und die
bestehenden Hybrid-Zähler. Hybrid kann über Menü oder `bl4tps_omni hybrid off`
wieder ausgeschaltet werden. Der Standard ist aus; eine gespeicherte On-Einstellung
kann nach Neustart wieder aktiv sein.

Die aktuelle Sprint-Belegung schaltet bei gehaltenem ADS die Scope-Route um.
Shift/L3 sind Beispiele deiner Belegung, keine neue fest vorgegebene Eingabe.

## Vergleich mit derselben Waffe

Bei jedem Vergleich dieselbe Waffe, dieselbe Schulter, Kameradistanz und dasselbe
ruhende Ziel benutzen. Einstellungen und Kategorie dazuschreiben; jeweils nur eine
Einstellung ändern. Erst Hybrid aus, dann mit derselben Einstellung Hybrid an.

| Fall | Zu dokumentieren |
|---|---|
| Native ADS-Unterschiede | Zwei Waffen mit sichtbar unterschiedlichem nativem ADS-Zoom vergleichen; Kategorie und Waffe festhalten. TPS-Halten und FPS-Scope getrennt beurteilen. |
| Globaler Mod-ADS-Zoom | Zwei deutlich unterschiedliche erlaubte globale Zoom-Werte wählen; Kategorie-Override dabei aus. Reagiert Hybrid TPS-ADS/FPS-ADS jeweils darauf? |
| Zoom pro Kategorie | Kategorie-Override aktivieren, zwei deutlich unterschiedliche erlaubte Werte vergleichen; globalen Zoom dabei gleich lassen. |
| Sniper-ADS-Option | Mit derselben Sniper beide vorhandenen ADS-Routen/Einstellungen testen; Hybrid aus/an vergleichen. Zustand beim ADS-Drücken sowie nach Sprint-Toggle festhalten. |
| Scope-Wechsel | ADS halten, einmal Sprint-Taste drücken und loslassen, dann erneut drücken/loslassen. TPS→FPS und FPS→TPS getrennt prüfen; Zoom, Scope/HUD, Kamera und Omni nach ADS-Loslassen beschreiben. |

Wenn ein Fehler auftritt, zuerst eine einfache reproduzierbare Folge aufschreiben.
Weitere Kombinationen (Waffenwechsel während ADS, Sprint bereits gehalten,
Hybrid aus während FPS-Scope) erst danach, damit die Ursache zuordenbar bleibt.
Kein erzwungener Respawn nötig.

## Bericht pro Fehler

- Waffe/Kategorie, Plattform/Input und vorhandene Sprint-/ADS-Belegung.
- Globaler ADS-Zoom, aktiver Kategorie-Override mit Wert und Sniper-ADS-Option.
- Optional veränderte Hybrid-Einstellungen (`bl4tps_omni hybrid status`).
- Genaue Folge von Drücken/Halten/Loslassen, erwartetes und tatsächliches Verhalten.
- Ob das Verhalten bei Hybrid aus ebenfalls auftritt; ob es sich wiederholen lässt.

Direkt nach einem kurzen Reproduktionslauf `bl4tps_omni hybrid status` und danach
`bl4tps_omni report` ausführen.
Die dort ausgegebene JSON sowie den passenden SDK-Log-Ausschnitt senden.
Optional ein Screenshotpaar vom selben Ziel für Zoom-Vergleiche.
Die Konsole für den Gameplay-Test vollständig schließen, da sie Eingaben blockiert.

Die umfangreichen alten Performance-A/B-Proben werden für diese Inventur nicht
benötigt. Zoom-/Sniper-/Scope-Bugs sind in dieser Variante bewusst noch unverändert.
