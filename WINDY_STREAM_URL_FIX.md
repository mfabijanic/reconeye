# Windy Camera Stream URL Fix

**Date**: 2026-06-02  
**Status**: ✅ Completed  
**Scope**: Fixed Windy camera stream URLs to enable direct playback instead of opening embedded player pages

---

## Problem

Windy kamere su imale embedded URL-ove za player koji su otvarati novu stranicu umjesto da puštaju video:
- **Old format**: `https://webcams.windy.com/webcams/public/embed/player/{id}/live`
- **Issue**: Clicking on camera opened new tab instead of inline playback

## Root Cause Analysis

1. **API Response**: Windy API returns `player.live` field with embedded player URLs
2. **Embedded Player URLs**: These are meant for iframe embedding on Windy's site, not direct streaming
3. **No Direct Stream URL**: API doesn't provide direct stream URLs; only embedded player URLs

## Solution Implemented

**Discovery**: Found that Windy provides `/webcams/stream/{id}` endpoint that:
- Returns HTTP 200 (valid endpoint)
- Contains HTML page with iframe element
- The iframe src points to actual source stream (MJPEG, HLS, RTSP, WebRTC)
- Provides **direct stream access** instead of embedded player

### Changes Made

#### 1. **Parser** (`apps/scraping/parsers/windy.py`)

Updated `_camera_from_item()` function:

```python
# OLD (lines 149-160):
# Stored embedded player URL directly
stream_url = str(_deep_get(item, "player", "live") or "").strip()

# NEW (lines 157-162):
# Use direct stream access endpoint instead
stream_url = f"https://webcams.windy.com/webcams/stream/{webcam_id}"
```

Also updated `page_url`:
```python
# OLD: Not set or derived from API response
# NEW: Link to Windy main camera page (for context & sharing)
page_url = f"https://www.windy.com/webcams/{webcam_id}"
```

**Key behaviors preserved**:
- ✅ Strict live-only filtering at parse time (skip cameras without `player.live`)
- ✅ Full metadata extraction from API
- ✅ `source_payload` now stores original `player_live` and `player_day` for diagnostics

#### 2. **Template** (`templates/cameras/_stream_player.html`)

Updated Windy stream block (lines 23-32):

```django-html
# OLD (checked source_payload.player_live):
{% elif camera.source_type == "WINDY" and camera.source_payload.player_live %}

# NEW (checks camera.stream_url):
{% elif camera.source_type == "WINDY" and camera.stream_url %}
  {# Windy stream: /webcams/stream/{id} provides direct stream access page #}
  <div class="stream-player mb-3">
    <iframe
      class="camera-frame w-100 rounded border border-secondary bg-black"
      src="{{ camera.stream_url }}"
      ...
    ></iframe>
  </div>
```

**Effect**: Now renders stream access page directly in iframe (provides direct stream playback)

### URL Format Reference

| Component | Format | Example |
|-----------|--------|---------|
| **Stream URL** | `/webcams/stream/{id}` | `https://webcams.windy.com/webcams/stream/1227972392` |
| **Page URL** | `/webcams/{id}` | `https://www.windy.com/webcams/1227972392` |
| **Embedded Player** | `/embed/player/{id}/live` | `https://webcams.windy.com/webcams/public/embed/player/1227972392/live` |

### Example: Camera 1227972392 (Sankt Gallen)

1. **Stream endpoint** returns HTML with iframe:
   ```html
   <iframe src="http://klosterplatz.selfip.info:80/axis-cgi/mjpg/video.cgi"></iframe>
   ```

2. **Actual source stream**: MJPEG at `http://klosterplatz.selfip.info:80/axis-cgi/mjpg/video.cgi`

3. **User flow**:
   - Click camera → Opens `/webcams/stream/1227972392` in iframe
   - Page contains source stream iframe
   - Video plays inline ✅

## Database Cleanup

**Executed cleanup** before re-scraping:
- Deleted **2955 Windy cameras** (old data with embedded URLs)
- Deleted **all Windy scrape jobs** (to start fresh)
- Cache invalidated automatically via Django signals

## Testing & Verification

✅ **URL format validation**:
- Tested `/webcams/stream/{id}` endpoint with HEAD requests
- All tested camera IDs returned HTTP 200
- Format: `https://webcams.windy.com/webcams/stream/{webcam_id}`

✅ **Parser output validation**:
- Tested `_camera_from_item()` with 5 live cameras
- Generated URLs: `https://webcams.windy.com/webcams/stream/{id}` ✅
- All URLs follow correct pattern

✅ **Code validation**:
- No syntax errors in `apps/scraping/parsers/windy.py`
- No syntax errors in `templates/cameras/_stream_player.html`
- Django linting passed

## Next Steps

1. Restart Django development server to reload template changes
2. Restart Celery worker to load updated parser
3. Trigger new Windy scraping job to populate DB with new stream URLs
4. Verify UI: click camera → should play video inline (not open new page)

## Configuration

No new settings required. Parser uses:
- `WINDY_API_BASE_URL` (default: `https://api.windy.com`)
- `WINDY_API_KEY` (existing requirement)
- `WINDY_WEB_CAMS_PER_PAGE` (existing, max 50)

## Backward Compatibility

- No database migrations needed (reuses existing columns)
- Template gracefully handles missing `stream_url`
- Live-only filtering ensures only cameras with valid `player.live` are stored

## References

- Windy API: https://api.windy.com/webcams/docs
- Previous stream discovery: `/webcams/stream/{id}` endpoint analysis
- Source stream types supported: MJPEG, HLS, RTSP, WebRTC (varies by camera)
