# Stockholm Transit — V12 rebuild specification

Status: Architecture baseline. **Not deployed.** The existing main branch / GitHub Pages site remains untouched.

## Product truth
Stockholm Transit is a **timetable-based simulation**, not a GPS tracking app. Its position estimates and departures must never be labelled as observed real-time locations. The original UL 801 live-tracker is a separate application.

## User-facing acceptance criteria
1. Stockholm map and responsive sidebar usable on desktop and mobile.
2. Modes: bus, metro, commuter rail, tram, local rail, regional/long-distance rail and ferries, restricted to genuinely available feed coverage.
3. Current Europe/Stockholm wall-clock time controls trips; crossings of midnight and DST are tested.
4. Selecting a vehicle shows line, direction, next stop, timetable arrival, following stops and a correctly scoped photo when available.
5. Selected vehicle route displays its entire verifiable geometry; progress from **trip start** is colored blue, remaining verifiable geometry gray. Stop markers and current next stop remain legible. Do not invent tracks across missing map connections.
6. Consistent smooth movement with the animation clock decoupled from polling and data reloads. Pan/zoom and list updates must not recreate all markers.
7. Performance: cache decoded data; limit visible drawing to the viewport; measure frame time and dropped frames on mobile, not only JavaScript syntax.
8. Photos: only approved, license-attributed files; offline/local catalog first. Missing imagery receives an honest placeholder rather than a false claim that every vehicle has a verified image.
9. All data provenance and age visible; unavailable modes, unknown shapes, and simulated extras clearly labeled.
10. No major feature may deploy without validation; restore the previous release automatically or keep it deployed when checks fail.

## Architecture
- `src/data/`: GTFS ingest, normalization, service calendars, trip indexes and geometry quality flags.
- `src/sim/`: deterministic pure position-at-time calculation, shape progress and next-stop derivation.
- `src/render/`: map and marker renderer; interpolation uses `requestAnimationFrame`, immutable trip state and viewport culling.
- `src/ui/`: route selection, stop board, legend, filter and photo component.
- `src/assets/`: approved photo manifest, license metadata, fallback hierarchy.
- `tests/unit/`: stop times, interpolation, shape projection, midnight/DST, fallback logic.
- `tests/integration/`: built GTFS sample against UI contracts and linked route segments.
- `tests/e2e/`: browser smoke tests, screenshots and interaction checks for desktop/mobile.
- `.github/workflows/`: independent checks for build, tests, data audit, browser checks, and deployment.

## Pipeline contract
1. Compile validated data into versioned artifacts with JSON schemas and content hashes.
2. Produce per-mode metrics: total trips, complete/partial/missing route geometries, percentage of trips with approved photo coverage and reference date.
3. Run deterministic simulation tests + JS/TS type check + UI tests.
4. Run browser checks on a preview build, including selected-trip blue/gray route coloring and photo fallback.
5. Deploy from a passing, tagged build only; no workflow may silently mutate `main`.
6. Preserve the current deployed page until explicit promotion of V12.

## Fundamental choices
- Separate the *transport-data build* from *visual rendering* and from *deployment*.
- Every trip has one stable identity; never choose a random default route shape just to display a blue line.
- Use verified shape/OSM graph sections only; partial geometry is still usable if marked.
- Never interpolate screen pixels between timestamps after a pan or zoom; derive position from world coordinates.
- Maintain a deterministic test fixture for a normal day, midnight crossing and winter/summer timezone shifts.

## First implementation milestones
A. Extract sample data contracts and write deterministic simulator tests.
B. Establish modular frontend and browser interaction test harness.
C. Rebuild route and marker rendering, then validate a selected route before broadening coverage.
D. Integrate photo catalog, filters, mobile sidebar and performance instrumentation.
E. Wire up preview + guarded deployment, then compare against V11.

This document captures an initial implementation plan rather than asserting all criteria already work.
