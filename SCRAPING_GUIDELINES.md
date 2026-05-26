# Respectful Web Scraping Guidelines

This document outlines the scraping policies and rate-limiting strategies used in reconeye to ensure we don't harm or "attack" target websites like Insecam.org.

## Philosophy

Once we pull cameras into the local database, we only need periodic updates. Heavy scraping should be:
- **Respectful**: Not hammering the server
- **Efficient**: Minimal HTTP requests (lazy enrichment)
- **Observable**: Clear timing between requests (not bot-like)

## Current Implementation

### Rate Limiting

**Location**: `apps/scraping/http.py`

```python
LIMITER = AsyncLimiter(max_rate=1, time_period=1)  # 1 request/second max
```

**Default**: 1 request per second (respectful)

### Insecam Scraper Specifics

**File**: `apps/scraping/parsers/insecam.py`

#### 1. **Listing Phase - Random Delay Between Pages**

```python
# Random 1-3 second delay between listing pages
delay = random.uniform(1.0, 3.0)
await asyncio.sleep(delay)
```

- Avoids pattern detection ("hammering at regular intervals")
- Mimics natural browser behavior
- 14 RU cameras now takes ~31 seconds instead of ~5 seconds

#### 2. **Enrichment Phase - Lazy Loading**

Only fetch detail pages for cameras that **need** enrichment (missing stream_url).

- ~95% of cameras have stream_url from listing → **no detail request needed**
- Only ~5% need enrichment (fallback cases)
- If detail is required, small random delay (0.3-0.7s) added

#### 3. **User-Agent Rotation**

**File**: `apps/scraping/http.py`

```python
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36...",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
    # ... rotates between 4 different UA strings
]
```

- Random selection on each client instantiation
- Prevents IP-level fingerprinting

## Performance vs Respectfulness Trade-off

### Example: Russia (RU - 73 cameras)

**Before Optimization**:
- Old: 3 requests/second, no delays
- Time: ~5 seconds
- Requests: 14 (listing) + 0 (enrichment) = **14 total**

**After Respectful Implementation**:
- New: 1 request/second, 1-3s random delays between pages
- Time: ~31 seconds
- Requests: 14 (listing) + 0 (enrichment) = **14 total**

**Trade-off**: +26 seconds for respectful behavior ✅

### Request Savings via Lazy Enrichment

**Hypothetical without lazy enrichment**:
- RU: 14 listing + 73 detail = **87 requests** (would take ~87 seconds)
- JP: 50 listing + 345 detail = **395 requests** (would take ~395 seconds)

**With lazy enrichment** (current):
- RU: 14 listing + 0 detail = **14 requests** (~31 seconds)
- JP: 50 listing + 0 detail = **50 requests** (~100 seconds)

**Savings**: 80-90% fewer requests! 🚀

## Configuration

### Adjusting Rate Limits

Edit `apps/scraping/http.py`:

```python
def get_limiter(max_rate: float = 1, time_period: float = 1) -> AsyncLimiter:
    # max_rate=2, time_period=1 → 2 requests/second
    # max_rate=1, time_period=2 → 1 request per 2 seconds (more respectful)
    return AsyncLimiter(max_rate=max_rate, time_period=time_period)
```

### Adjusting Delays

Edit `apps/scraping/parsers/insecam.py`:

```python
# Between listing pages:
delay = random.uniform(1.0, 3.0)  # Current: 1-3 seconds

# After detail fetch:
await asyncio.sleep(random.uniform(0.3, 0.7))  # Current: 0.3-0.7 seconds
```

## Scraping Session Example

A typical scrape of Russia (73 cameras):

1. **Collect Listing** (6 pages with duplicates):
   - GET /en/bycountry/RU/?page=1 (finds 14 cameras)
   - [wait ~2s random]
   - GET /en/bycountry/RU/?page=2 (finds 0 new, stop)
   - Total: 14 cameras discovered

2. **Process Cameras** (batch of 50):
   - All 14 have stream_url from listing → no detail requests
   - Flush to DB with `total_new=0, total_updated=73`

3. **Total Time**: ~31 seconds, **14 HTTP requests**

## Recommendations for Future Sources

When adding new scrapers (WhatsUpCams, etc.):

1. **Always implement lazy enrichment** where possible
2. **Use rate limiting** (default: 1 req/sec)
3. **Add random delays** between requests (avoid pattern detection)
4. **Rotate User-Agents** (use `USER_AGENTS` list from `http.py`)
5. **Respect robots.txt and Terms of Service** of the target site
6. **Log HTTP requests** for audit trail (already done via httpx)

## Monitoring

Check Celery logs for scraping activity:

```bash
tail -f /tmp/reconeye-logs/celery.log | grep "HTTP Request"
```

Example output (respectful spacing visible):
```
17:24:07 GET http://www.insecam.org/en/bycountry/RU/?page=1 200 OK
17:24:09 GET http://www.insecam.org/en/bycountry/RU/?page=2 200 OK  ← +2s gap
17:24:11 GET http://www.insecam.org/en/bycountry/RU/?page=3 200 OK  ← +2s gap
```

## Summary

✅ **Respectful**: 1 req/sec rate limit + random delays  
✅ **Efficient**: Lazy enrichment skips 95% of detail requests  
✅ **Observable**: Clear timing (not bot-like)  
✅ **Maintainable**: Periodic updates instead of continuous crawling  

Once cameras are in the local DB, scraping becomes a lightweight update process, not an ongoing bombardment of the target server.
