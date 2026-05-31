# Changelog

## v0.1.0 — Initial Public Release

This first release establishes the core ReconEye product and ships a broad set of features for browsing, scraping, geocoding, monitoring, and maintaining camera data.

### Added
- Server-rendered Django application with login-protected access.
- Dashboard with summary cards, active job visibility, and source breakdown.
- Camera list, camera detail, and camera map views.
- Surveillance view for go2rtc cameras.
- HTMX partials for camera lists, dashboard stats, and map panels.
- Celery-based background processing for scraping and geolocation refresh work.
- Insecam scraper pipeline.
- WhatsUpCams scraper pipeline.
- go2rtc camera ingestion and playback support.
- Nominatim-based geolocation lookup with caching.
- Django admin maintenance actions for cache invalidation and geolocation refresh.

### Improved
- ISO-based country label rendering for Insecam and WhatsUpCams country selectors.
- Camera map behavior for overlapping markers on identical coordinates.
- WhatsUpCams title and city resolution for better location naming.
- Stream resilience for go2rtc and HLS playback.
- Handling of partial camera metadata when a direct stream is unavailable.
- Dashboard source counts to include go2rtc alongside the scraper sources.

### Changed
- Camera list filtering now includes a geo fallback filter for country-only geocoding results.
- go2rtc playback favors the WebRTC-based player pages for better reliability.
- Geolocation refresh now supports targeted updates for selected cameras.

### Notes
- This release is the initial public baseline and includes a large functional surface area.
- Future entries should document incremental changes after this first version.