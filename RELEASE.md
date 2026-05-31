## ReconEye — First Public Release

This is the first public release of ReconEye.

It brings together camera scraping, geolocation, mapping, dashboard stats, and surveillance playback in one server-rendered Django app.

### What’s Included
- Login-protected web app with dashboard, camera list, camera detail, map, and surveillance views.
- Insecam and WhatsUpCams scraping pipelines with background processing through Celery.
- go2rtc camera support with surveillance playback and stream recovery improvements.
- Geolocation caching and targeted refresh for selected cameras.
- Marker clustering and overlapping-marker separation on the map.
- Dashboard source breakdown, including Insecam, WhatsUpCams, and go2rtc.
- Admin tools for filtering, cache invalidation, and geolocation maintenance.

### Highlights
- Better WhatsUpCams country labels using ISO country names.
- Improved reliability for stuck or stalled streams.
- Better handling of partial metadata and country-only geolocation fallbacks.

### Notes
- This release is intended as the first stable public baseline.
- Detailed change history is kept in `CHANGELOG.md`.

