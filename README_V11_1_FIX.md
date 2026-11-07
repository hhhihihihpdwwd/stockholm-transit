# Stockholm Transit V11.1 – Routen-Fix nach fehlgeschlagenem Build

Dieses Update enthält die V11-Dateien sowie zwei gezielte Korrekturen:

1. Der Workflow zählt FULL und PARTIAL OSM-Routen gemeinsam für die Qualitätsprüfung. Der letzte reale Build hatte beispielsweise bei der Tunnelbana 4 FULL + 22659 PARTIAL von 22663 Fahrten; die alte Prüfung hat ihn fälschlich als fast vollständig fehlend gewertet. Die Qualitätsschranken bleiben aktiv (90–95 % FULL oder PARTIAL je nach Modus).
2. Bei Auswahl eines Fahrzeugs wird zusätzlich eine durchgehende, **gestrichelte und nur angenäherte** Haltestellenlinie gezeigt: bereits zurückgelegter Abschnitt blau, restlicher Abschnitt grau. Wo genaue OSM-Teilstücke vorhanden sind, werden diese weiterhin darüber angezeigt. Die gestrichelte Linie ist **keine echte Straße/Schiene**. Die originalen Fernzuggeometrien bleiben unverändert.

## Installation

ZIP entpacken; Inhalt mit erhaltenen Unterordnern in das vorhandene Repository kopieren und committen. Keine bestehenden `public/assets/photos/*.jpg` löschen. Dann den V11-Workflow erneut starten.

## Ehrliche Grenzen

Die ZIP enthält keine Originalfotos. Fünf zuvor fehlgeschlagene Wikimedia-Downloads werden durch diese Korrektur nicht plötzlich verfügbar. Für 100 % echte Fotos müssen die fünf Dateien tatsächlich beschafft und mit Lizenzdaten ins Repo übernommen werden. Der Workflow lässt aktuell 20/25 lokale Fotos zu; daher ist **100 % Fotoabdeckung nicht bestätigt**. Ebenso kann eine angenäherte Haltestellenlinie nicht die Genauigkeit einer vollständig gerouteten Strecke ersetzen.

35 bestehende Tests sowie JavaScript-Syntaxprüfung lokal bestanden. Der vollständige GitHub-Datensatz wurde nicht hier ausgeführt.
