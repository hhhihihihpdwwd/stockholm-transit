# STOCKHOLM / TRANSIT — Version 1

Eine fahrplanbasierte Verkehrssimulation für Stockholm. **Keine Live-GPS-Daten.** Die Anzeige verwendet ausschließlich die aktuelle schwedische Ortszeit, mit sanfter Positionierung entlang verfügbarer GTFS-Streckenformen. Auf der Karte werden Verkehrsmittel aus den geladenen GTFS-Datensätzen dargestellt: Metro, Bus, Pendeltåg, Trams, Lokalbahnen, Fern-/Regionalzüge und Fähren. Die Abdeckung hängt von den Datenfeeds ab.

## Installation ohne Render-Server

Wir verwenden eine **neue GitHub-Repository** namens `stockholm-transit` und **GitHub Pages**. Die alte UL-801-App wird nicht verändert.

### A. Neues Repository

1. Öffne https://github.com/new und melde dich an.
2. Repository-Name: `stockholm-transit`. **Public** auswählen. Mit README erstellen? **Nein** (im ZIP liegt bereits eine).
3. Lade den Inhalt dieses ZIPs in dein neues GitHub-Repo. Die Dateistruktur muss so aussehen:

```
stockholm-transit/
  README.md
  public/
    index.html
  scripts/
    build.py
  .github/
    workflows/
      build.yml
```

Achtung: `public/index.html` darf NICHT im Hauptverzeichnis liegen. `.github/workflows/build.yml` muss genau diesen Pfad erhalten. Falls GitHub beim Drag-and-drop Ordner nicht erhält, öffne den jeweiligen Ordner im GitHub-Dateibaum und lade die Datei dort hoch; den Workflow kannst du über Add file → Create new file mit dem Namen `.github/workflows/build.yml` anlegen und den Inhalt der beiliegenden Datei einfügen.

### B. Trafiklab-Schlüssel als GitHub-Secret

**Schlüssel nie in eine Datei schreiben oder in den Chat senden.**

1. https://developer.trafiklab.se/ öffnen und einen persönlichen Schlüssel für **GTFS Regional – Static data** verwenden/erstellen (nicht den Realtime-Schlüssel!).
2. GitHub: `stockholm-transit` → Settings → Secrets and variables → Actions → New repository secret.
3. Name `GTFS_SL_KEY`, Value: GTFS Regional Static API-Schlüssel. Bestätigen.
4. **Optional für Fernzüge und andere Unternehmen:** einen zweiten Schlüssel für **GTFS Sweden 3 Static data** anlegen, denselben Weg gehen und `GTFS_SWEDEN_KEY` nennen. Ohne ihn enthält die App nur Verkehrsangebote aus dem SL-Feed, nicht automatisch alle Fernzüge.

### C. Webseite veröffentlichen

1. GitHub → Settings → Pages → Build and deployment → Source: **GitHub Actions** (kein fertiges Template auswählen).
2. GitHub → Actions → **Build Stockholm timetable** → **Run workflow** → Branch `main` → Run workflow.
3. Wenn **build** und **deploy** grün sind: GitHub → Settings → Pages. Dort steht die URL, typischerweise `https://<dein-name>.github.io/stockholm-transit/`.
4. Öffne sie auf Desktop oder iPhone. GitHub führt den Build täglich aus. Die Webseite braucht zum Anzeigen danach **keinen Render-Server und keine API-Schlüssel**.

### D. Test / Fehlersuche

- Meldung „Data saknas“: In GitHub Actions → Build Stockholm timetable → letzter Lauf → `build` → `Build timetable data` die Fehlermeldung überprüfen.
- `No datasets downloaded`: `GTFS_SL_KEY` fehlt, hat falschen Typ oder wird vom Anbieter abgelehnt.
- `HTTP 404` auf der GitHub Pages Website: **Settings → Pages** muss auf **GitHub Actions** stehen und der Deployment-Lauf erfolgreich sein.
- Falls nur SL-Fahrzeuge, aber keine Fernzüge angezeigt werden, ist vermutlich der **optionale Sweden-3-Schlüssel** noch nicht konfiguriert.
- Standorte ohne präzise GTFS-Geometrie sind **schematische Positionsschätzungen** zwischen Haltestellen, keine gemessenen Fahrzeugpositionen.
- Nach Tagen ohne Actions-Ausführung veralten die Fahrplantage. Die App zeigt eine Warnung an, statt alte Abfahrten als „live“ auszugeben.

## Wie die Simulation arbeitet

- Lädt bis zu drei Verkehrstage (gestern, heute, morgen) aus dem bei GitHub vorab erzeugten Datensatz. Damit sind auch Fahrten über Mitternacht möglich.
- Berücksichtigt `calendar.txt`, `calendar_dates.txt`, die Abfahrts-/Ankunftszeiten aus `stop_times.txt`, Fahrt-/Linienzuordnung und `shapes.txt` aus GTFS.
- Positionen werden vom Browser anhand der **aktuellen schwedischen Uhrzeit** berechnet. Kein Zeitregler; man kann die Simulation nicht vor- oder zurückstellen.
- Die Animation läuft unabhängig von Netzabfragen mit ca. 30 Bildern/Sekunde; Beschleunigung/Bremsung werden angenähert.
- Busse und Züge werden nur **innerhalb des Stockholmer Kartenausschnitts** berücksichtigt.
- Die Kategorisierung der Züge anhand von GTFS `route_type` und Linienbezeichnung ist heuristisch. Einzelne Regionalzüge können unter „Regional/Fjärr“ statt „Pendeltåg“ erscheinen.
- Bei fehlenden Streckenverläufen werden keine blauen/grauen Falschrouten gezeichnet; eine schematische Fahrzeugposition kann dennoch aus Haltestellenkoordinaten errechnet werden.
- Die Bildsuche nutzt Wikimedia Commons; die Bilder sind **unverifizierte Typbeispiele**, nicht Fotos des gerade fahrenden Fahrzeugs. Lizenz/Urheber vor späterem Fest-Einbau prüfen.
- **Kein Sound, keine Abstellgleise, kein Zeitraffer**.

## Datenquellen

- GTFS Regional: https://trafiklab.se/api/gtfs-datasets/gtfs-regional
- GTFS Sweden 3: https://trafiklab.se/api/gtfs-datasets/gtfs-sweden/
- Kartengrundlage: © OpenStreetMap contributors. Bei hohem Besuchsaufkommen Kartenkacheln auf einen geeigneten Provider umstellen.
