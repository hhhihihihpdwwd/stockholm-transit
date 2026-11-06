# Stockholm Transit V10 — Static vehicle photo library

**Important:** The national railway / bus route build is unchanged. Photos no longer depend on Commons availability during the big build.

## One-time setup
1. Upload/replace the archive contents at the repository root, preserving directories (`.github/workflows`, `scripts`, `public`, `tests`).
2. In GitHub Actions, choose **Stockholm Transit - ONE TIME import and store vehicle photos**, then **Run workflow**. This fetches photos once and commits successful verified-source images into `public/assets/photos`. It can be rerun to fill missing photos: already committed valid files are retained.
3. Open `public/assets/photos/catalog.json` in GitHub and check that the desired keys exist. Photos failing network/source validation remain missing; the audit artifact lists each failure. Never equate a successful run with all photos having been fetched.
4. Choose **Stockholm Transit V10 - Static photos and national routes**, then Run workflow. This rebuilds national route data but **never downloads photos**. It will deploy even if some photos are missing; those vehicles receive a local SVG illustration with no misleading photo credit.

## Reality and safety
- The ZIP contains **code but not real photographs**: the execution environment could not retrieve remote Commons images. Real files must be committed by the one-time import workflow. **Do not claim the image library is fully populated before seeing that workflow's audit.**
- The approved media keys and exact file-title candidates remain in `scripts/fetch_photos.py`, which only runs in the manual one-time media workflow.
- No placeholders are labelled as photographs. A proper licensing caption always accompanies displayed photos.
- The regular data build uses `scripts/local_photos.py` only, with no HTTP requests and no mandatory-photo deployment gate.
- Existing published V9 does not change until the user runs V10's build/deploy workflow.
- This update does not make the previously missing 42,123 route instances magically complete; it is the requested dependable-media architecture change.
