# Stockholm Transit – 35 bestätigte Bildgruppen

Die 35 Entscheidungen sind in `approved_photos.json` festgehalten. Die Dateien in diesem ZIP enthalten **keine heruntergeladenen Originalfotos**: Der Download in der ChatGPT-Arbeitsumgebung ist technisch gescheitert.

1. Diese Dateien (einschließlich `approved_photos.json`) in das bestehende GitHub-Repository übernehmen.
2. GitHub Actions → `Stockholm Transit - ONE TIME import and store vehicle photos` manuell starten. Das lädt **nur die exakt freigegebenen Wikimedia-Dateinamen**, keine Such-Alternativen.
3. Unter Artifacts den Fotobericht prüfen. Die Action committet erfolgreiche Dateien nach `public/assets/photos/`. Wenn welche fehlen, werden sie als fehlend ausgewiesen; keine anderen Bilder werden untergeschoben.
4. Erst dann den regulären V10-Build starten. Er lädt selbst **keine** Fotos aus dem Netz.

Achtung: Für die tatsächliche Lizenzprüfung sind die Commons-Metadaten beim Import maßgeblich. Bildvorschläge können trotz Freigabe nicht abrufbar sein. Ein erfolgreicher Workflow bedeutet nicht automatisch 35 von 35 verfügbaren Gruppen; maßgeblich ist `photo-health.json`.
