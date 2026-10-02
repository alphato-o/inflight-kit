# Show reels

The clips were recorded by driving a Chromium-based browser over the DevTools Protocol, from live flight data.

**Capture:** call `Page.captureScreenshot` in a tight loop, at about 25 fps for a 1920x1080 page, and stamp each frame with its time.

**Smooth motion:** before each clip, a script injected on page load (`Page.addScriptToEvaluateOnNewDocument`) slows the page's `performance.now()` to half speed, and `Animation.setPlaybackRate(0.5)` slows CSS animations to match. Frames are stamped in page time, so playback runs at real speed with about 50 fps of source material.

**Input:** keyboard shortcuts as raw `Input.dispatchKeyEvent`. Mouse clicks dispatched during capture were sometimes dropped, so clicks happen just before capture starts.

**Encode:** `encode.py` turns each `frames/<clip>/` folder (`NNNNN.jpg` plus `times.json`) into a 1080p30 H.264 High-profile MP4 with `+faststart`, which uploads cleanly to X/Twitter:

```sh
python3 encode.py              # every folder under frames/
python3 encode.py cine_orbit   # one clip
```

Needs `ffmpeg`. The rendered MP4s aren't committed, because they show a real flight.

Two caveats:
- **d3 transitions stall under the slowed clock.** d3's timer compares `performance.now()` against `Date.now()`, and only the first is slowed. Record d3 transitions at normal speed.
- **A hidden browser window stops producing frames while a page reloads**, so loading screens can't be captured this way.
