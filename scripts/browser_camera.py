"""Unmodified viewport PNGs with physical-size and before/after layout checks."""
import base64
import hashlib
import io
import json

from PIL import Image


def layout(page, cdp):
    return {
        'viewport': page.evaluate('({innerWidth,innerHeight,dpr:devicePixelRatio,scrollX,scrollY,visualViewport:{width:visualViewport.width,height:visualViewport.height,scale:visualViewport.scale},scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth})'),
        'cdp': cdp.send('Page.getLayoutMetrics'),
        'components': page.locator('[data-book-id], [data-ja-source]').evaluate_all('(els)=>els.map(e=>({id:e.dataset.bookId||e.dataset.jaSource,rect:e.getBoundingClientRect().toJSON()}))'),
    }


def screenshot(cdp):
    return base64.b64decode(cdp.send('Page.captureScreenshot', {
        'format': 'png', 'fromSurface': True, 'captureBeyondViewport': False})['data'])


def capture(page, path, native_zoom=False, top=True):
    """Fail on compositor clipping; never resize PNGs or modify page layout."""
    if top:
        page.evaluate('scrollTo(0,0)')
    page.wait_for_timeout(350)
    cdp = page.context.new_cdp_session(page)
    try:
        before = layout(page, cdp)
        raw = screenshot(cdp)
        after = layout(page, cdp)
    finally:
        cdp.detach()
    expected = (page.viewport_size['width'], page.viewport_size['height'])
    dimensions = Image.open(io.BytesIO(raw)).size
    report = {'expected_dimensions': expected, 'png_dimensions': dimensions,
        'png_sha256': hashlib.sha256(raw).hexdigest(), 'native_zoom': native_zoom,
        'before': before, 'after': after, 'layout_unchanged': before == after,
        'ok': before == after and dimensions == expected}
    # Keep failed raw frames and diagnostics, rather than silently accepting or
    # replacing bad evidence. A later run must use its own output directory.
    path.write_bytes(raw)
    path.with_suffix('.metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert before == after, f'Screenshot changed layout: {path}'
    assert dimensions == expected, f'Compositor clipping: PNG {dimensions}, viewport {expected}; {path}'
    assert before['viewport']['scrollWidth'] <= before['viewport']['clientWidth'] + 1, str(path)
    return report


def native_context(playwright, out, viewport):
    extension = out / 'zoom-extension'
    extension.mkdir(exist_ok=False)
    (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3,
        'name': 'Synthetic native zoom camera', 'version': '1.0', 'permissions': ['tabs'],
        'background': {'service_worker': 'worker.js'}}), encoding='utf-8')
    (extension / 'worker.js').write_text('chrome.runtime.onInstalled.addListener(()=>{});', encoding='utf-8')
    return playwright.chromium.launch_persistent_context(str(out / 'native-profile'),
        executable_path=playwright.chromium.executable_path, headless=False,
        ignore_default_args=['--disable-extensions'], args=['--headless=new',
        f'--disable-extensions-except={extension}', f'--load-extension={extension}'], viewport=viewport)


def calibrate_native_window(page, out):
    """Resize the actual outer browser window until its compositor is exact."""
    cdp = page.context.new_cdp_session(page)
    attempts = []
    expected = (page.viewport_size['width'], page.viewport_size['height'])
    try:
        for _ in range(4):
            window = cdp.send('Browser.getWindowForTarget')
            dimensions = Image.open(io.BytesIO(screenshot(cdp))).size
            attempts.append({'window': window, 'png_dimensions': dimensions})
            if dimensions == expected:
                break
            bounds = window['bounds']
            cdp.send('Browser.setWindowBounds', {'windowId': window['windowId'], 'bounds': {
                'width': bounds['width'] + expected[0] - dimensions[0],
                'height': bounds['height'] + expected[1] - dimensions[1]}})
            page.wait_for_timeout(250)
    finally:
        cdp.detach()
        (out / 'native-window-calibration.json').write_text(json.dumps(attempts, indent=2), encoding='utf-8')
    assert dimensions == expected, f'Native browser compositor calibration failed: {attempts}'
    return attempts


def set_native_zoom(context, base, factor):
    worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
    worker.evaluate('async d=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(d.url));await chrome.tabs.setZoom(t.id,d.factor)}', {'url': base, 'factor': factor})
    actual = worker.evaluate('async u=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(u));return chrome.tabs.getZoom(t.id)}', base)
    assert actual == factor, actual
    return actual
