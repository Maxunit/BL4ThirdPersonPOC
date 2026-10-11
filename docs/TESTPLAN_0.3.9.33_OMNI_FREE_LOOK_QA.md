# 0.3.9.33 – kurzer Spieltest

Spiel beenden, alte Mod-Version und deren PyCache entfernen. Nur den Ordner
`BL4ThirdPersonPOC/` oder `dist/BL4ThirdPersonPOC.sdkmod` installieren.

1. Omni einschalten, kurz bewegen und anschließend stillstehen. Ohne Zielen
   oder Schießen die Kamera hinter der Figur leicht hoch und runter drehen:
   Die gewohnte Körperneigung soll erhalten bleiben.
2. Kamera hinter der Figur langsam nach links/rechts drehen. Der Oberkörper
   soll begrenzt mitdrehen. Zur Seite hin sollen Drehung und Neigung weich
   verschwinden; von vorne soll Hoch-/Runterdrehen der Kamera keine entsprechende
   Aim-Neigung auslösen. Auch den Übergang hinter der Figur bei ±180° Welt-Yaw testen.
3. Wiederholen, während die Figur langsam läuft und anschließend geduckt steht
   bzw. läuft. Richtung der Oberkörperdrehung und mögliche Zuckungen beachten.
4. Kamera vorn/seitlich: TPS-ADS und Schießen beginnen, dann loslassen. Die
   normale Kampf-Aim-Pose muss sofort frei sein; danach freies Omni-Umschauen.
   Auch Hybrid-ADS (Hold/Toggle plus Sprint-Scope-Taste) und TPS↔FPS prüfen.
5. Kurz Dash, Slide, Sprung/Luftbewegung, Werfen und Fahrzeug-Ein-/Ausstieg testen.
   Danach normales freies Umschauen. Omni ausschalten: normales TPS soll wieder
   seine eigene Oberkörper-/Ganzkörperdrehung verwenden.

Für den ersten Befund reicht: Dreht der Oberkörper in die richtige Richtung?
Ist der Umfang angenehm? Ist die Neigung von vorne weg, und sind die Übergänge
weich? Die 35° sind die Aim-Eingabegrenze, kein gemessener Spine-Winkel.
Keine Diagnoseaufnahme nötig, solange das Verhalten stimmt. FPS bei Gelegenheit
am bisherigen Vergleichsort beobachten; SDK-Abfragezahlen allein beweisen
keine unveränderten Spiel-FPS.
