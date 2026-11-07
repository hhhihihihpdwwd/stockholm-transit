# Stockholm Transit V11 – stabile Fotos, bessere Strecken, flüssigere Animation

## Das ist das **eine** V11-Paket für das bestehende GitHub-Projekt

Projekt: https://github.com/hhhihihihpdwwd/stockholm-transit

**Nicht die ZIP selbst als Datei in GitHub ablegen.** Die ZIP auf deinem Computer entpacken und den **Inhalt** ins Stammverzeichnis des bestehenden Projekts hochladen. Die Ordnerstruktur muss gleich bleiben: `.github/workflows/build.yml`, `public/index.html`, `scripts/*.py`, `tests/*.py`, `approved_photos.json`.

**Bisherige lokale Bilder nicht löschen!** Mit Absicht enthält diese ZIP **keine** `public/assets/photos/catalog.json` und **keine** `photo-health.json`, falls diese Dateien bereits in GitHub existieren. Ebenso werden keine vorhandenen Bilder gelöscht oder ersetzt, wenn sie weiterhin zum exakt freigegebenen Dateinamen gehören.

### Installation ohne Terminal

1. Im GitHub-Repository auf **Code → Add file → Upload files** gehen. Die **entpackten** Dateien und Ordner (einschließlich des versteckten `.github`-Ordners) ins Uploadfeld ziehen, Dateipfade prüfen, **Commit changes** klicken. Auf dem Mac kann man versteckte Dateien mit **Cmd + Shift + .** anzeigen. Wenn das Hochladen der Ordnerstruktur im Browser nicht funktioniert, GitHub Desktop verwenden und die entpackten Dateien in eine lokale Kopie des Repositorys kopieren, committen und pushen.
2. Auf **Actions** gehen. Links **Stockholm Transit V11 - Stable photos, mapped routes, smooth movement** wählen. **Run workflow** → Branch **main** → **Run workflow**.
3. Der Workflow führt vor dem großen Kartendownload erst die **35 Tests**, dann den **Fotoimport** aus. Nur die 25 zuvor freigegebenen unterschiedlichen Originaldateien werden geladen, in max. 1100 Pixel breite JPEGs umgewandelt, mit Lizenz und Quelle im Fotokatalog gespeichert. Er übernimmt gültige vorhandene Dateien erneut, statt sie sinnlos zu löschen. Er prüft, ob wenigstens **20 von 25** Originalen lokal vorhanden sind; andernfalls wird die Veröffentlichung **vor dem teuren OSM-Build** gestoppt.
4. Erst danach kommt der große GTFS- und OSM-Verkehrsdaten-Build (der erste Download ist groß; später werden die OSM-Extrakte im Actions-Cache wiederverwendet). Die bestehende Seite bleibt online, falls ein Test oder eine Qualitätskontrolle fehlschlägt.
5. Unter **Actions → Lauf → Artifacts → stockholm-v11-validation-reports** den vollständigen Bericht nachsehen. Wichtig sind **`photo-health.json`** für die 25 Fotos und **`display-coverage.json`** für echte im Browser darstellbare Strecken. Ein grüner Action-Lauf ist ein Test- und Deployment-Erfolg, aber **keine Zusage für 100% Foto-/Routenabdeckung**.
6. Bei Erfolg: https://hhhihihihpdwwd.github.io/stockholm-transit/ – neu laden (Cmd + Shift + R).

### Was in V11 tatsächlich geändert wurde

- **Fotoquelle:** 35 bestätigte Fahrzeuggruppen, 25 exakte Commons-Dateien; keine ungefragten Ersatzmotive. **Lokale Bilder zuerst**, danach nur als Notfall derselbe **freigegebene** Commons-Dateiname in 960px-Vorschau oder Originalgröße. Nur erfolgreiche Originalbilder werden in GitHub gespeichert, inklusive Quelle/Autor/Lizenz. Die Bildbibliothek wird nicht durch den leeren V10-Katalog überschrieben. Richtige Erkennung des Verkehrsunternehmens „SL“ bei den Busbildern.
- **Straße und Schiene:** Vergrößerter Straßenkartenausschnitt, mehr mögliche Haltestellen-Anbindungen auf demselben zusammenhängenden OSM-Netz. In V10 konnte eine nicht aufgelöste Verbindung die ganze Route unsichtbar machen. Jetzt bleiben **verifizierbare Teilstücke** sichtbar, getrennt von echten Lücken – keine erfundenen Verbindungen durch Wasser oder Häuser.
- **Strecken am Browser:** Für neu aus OSM erzeugte vollständige Routen werden Haltestellen-Positionen auf der Strecke **vorausberechnet und mitgespeichert**. Für vorhandene GTFS-Routen bleibt die bisherige Darstellung als Fallback. Züge zu nationalen Zielen werden nicht gefiltert oder durch Schätzlinien ersetzt.
- **Animation:** Zeitinterpolation mit hochauflösender Uhr, kein Sekundenspringen; Kartenlinien werden aktualisiert statt ständig gelöscht und neu erstellt, Bewegungen über echte Teilstrecken werden animiert; Canvas-Zeichnung und wiederverwendete Geometrien mit begrenzten Caches.
- **Build und Sicherheit:** Tests vor Datendownload, Fotos vor großem 900-MB-Download, gespeicherte OSM-Extrakte für Wiederholungen, sichtbare Fortschrittsanzeige und automatische Prüfung gegen deutlich schlechtere Routenabdeckung. GitHub Pages wird **erst nach allen Tests** aktualisiert.

### Grenzen, die ich nicht beschönige

- Die **25 echten Bilddateien sind in diesem ZIP nicht enthalten**: Ein direkter Download von Wikimedia war aus der Arbeitsumgebung nicht möglich. GitHub Actions versucht, sie zu laden und dauerhaft zu speichern. Verbleibende Quellenfehler werden im Bericht aufgelistet. **Auch ein Foto-Fallback zu Commons kann fehlschlagen**; unbekannte Fahrzeugtypen bekommen lieber ein korrekt beschriftetes Symbol als ein falsches Foto.
- **100% aller Bus- und Bahnlinien können nicht aus einem GTFS-Archiv plus OSM-Straßennetz garantiert werden.** Einige Haltestellen/Schienen sind nicht durchgehend verknüpft; der regionale Straßen-Extrakt ist nicht ganz Schweden. Verifizierbare Teilstrecken werden sichtbar, echte Lücken bleiben sichtbar und werden ausgewiesen.
- Diese Lieferung wurde mit synthetischen OSM-Netzen, Python-Tests und JavaScript-Syntaxchecks getestet. Der komplette GitHub-Lauf einschließlich der 900-MB-Kartendatei und der externen Fotoquellen konnte **hier nicht ausgeführt** werden. Das sagt der Actions-Prüfbericht nach dem echten Lauf.
- Es bleibt eine **historische Simulation**, kein Live-GPS. Eine streng realistische 1:1-Fahrtbewegung benötigt Live-Positionsdaten beziehungsweise vollständig geprüfte, aktuelle GTFS-Shapes.

### Orientierung bei Fehlern

- **Fotos unter 20/25:** Actions-Log `Import ONLY the 25 photos ...`, Artifact `photo-health.json`. Mit V11 wird der große Build dann gar nicht erst gestartet.
- **Kartendownload hängt:** Actions-Log `Generate historical services and FULL plus PARTIAL OSM tracks`. Geofabrik-PBF wird alle 50 MiB protokolliert und kann nach Verbindungsabbrüchen fortgesetzt werden, solange die Runner-Sitzung noch läuft. Ein neuer Runner kann ohne Cache neu herunterladen müssen.
- **Routen unvollständig:** Report `display-coverage.json` → `lines[]`, sortiert nach `percent` und `examples`. Der Workflow bricht bei deutlicher Gesamtregression ab, statt still eine schlechtere Seite zu veröffentlichen.

**Wichtig:** Nicht die alten V10-Dateien nachträglich hochladen. Diese V11-ZIP ist die neue Codebasis. Freigegebene Fotos und bereits gespeicherte `.jpg`-Dateien im Repository erhalten.
