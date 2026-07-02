import os
import re
import time
import random
import hashlib
from urllib.parse import urlparse, urljoin, parse_qs
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://tambov.ru.net"
SITE_ROOT = "/detstvo/"
MIRROR_DIR = Path(__file__).parent.resolve()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

session = requests.Session()
session.headers.update(HEADERS)

downloaded_urls = set()
pages_to_crawl = set()
downloaded_images = set()
IMAGE_MAP = {}

error_500_count = {}
MAX_500_RETRIES = 2
FAILED_URLS_FILE = MIRROR_DIR / "failed_urls.txt"


def log_failed(url, status_code):
    with open(FAILED_URLS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{status_code}\t{url}\n")
    print(f"  [LOGGED] {url} ({status_code}) -> failed_urls.txt")


def polite_delay():
    time.sleep(random.uniform(3.0, 5.0))


def is_tracker_script(tag):
    if not isinstance(tag, Tag):
        return False
    if tag.name == "script":
        src = tag.get("src", "")
        text = tag.get_text(strip=True)
        if "yandex" in src.lower() or "metrika" in src.lower():
            return True
        if "yandex" in text.lower() or "metrika" in text.lower() or "ym(" in text:
            return True
        if "google-analytics" in src.lower() or "gtag" in src.lower():
            return True
    if tag.name == "noscript":
        img = tag.find("img")
        if img and ("yandex" in img.get("src", "").lower() or "mc.yandex" in img.get("src", "").lower()):
            return True
    if tag.name == "a":
        href = tag.get("href", "")
        if "metrika.yandex" in href.lower():
            return True
    if tag.name == "img":
        src = tag.get("src", "")
        if "informer.yandex" in src.lower() or "mc.yandex" in src.lower():
            return True
    return False


def safe_get(url, timeout=30):
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.HTTPError as e:
        code = resp.status_code if resp is not None else 0
        if code == 500:
            error_500_count[url] = error_500_count.get(url, 0) + 1
            if error_500_count[url] > MAX_500_RETRIES:
                log_failed(url, code)
                return "SKIP"
        print(f"  [HTTP {code}] {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  [ERR] {url}: {e}")
        return None


def download_file(url, subdir="", filename=None):
    parsed = urlparse(url)

    if url in downloaded_images:
        return None
    downloaded_images.add(url)

    if filename is None:
        fname = parsed.query if parsed.query else "unknown"
        fname = re.sub(r'[<>:"/\\|?*]', '_', fname)
        if "fimg=" in fname or "fqimg=" in fname:
            fname += ".jpg"
        filename = fname

    save_dir = MIRROR_DIR / subdir
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    if save_path.exists():
        print(f"  [SKIP] already exists: {filename}")
        return str(save_path.relative_to(MIRROR_DIR))

    full_url = urljoin(BASE_URL, url)
    resp = safe_get(full_url)
    if resp == "SKIP" or resp is None:
        return None

    try:
        with open(save_path, "wb") as f:
            f.write(resp.content)
        print(f"  [OK] {filename} ({len(resp.content)} bytes)")
        return str(save_path.relative_to(MIRROR_DIR))
    except Exception as e:
        print(f"  [WRITE ERR] {filename}: {e}")
        return None


def extract_image_urls(soup, base_url):
    results = set()

    # data-src (lightgallery full-res)
    for tag in soup.select("[data-src]"):
        src = tag["data-src"]
        full = urljoin(base_url, src)
        parsed = urlparse(full)
        if "tambov.ru.net" in parsed.netloc or not parsed.netloc:
            results.add(full)

    # srcset: pick the largest source
    for tag in soup.find_all(srcset=True):
        srcset = tag["srcset"]
        best_url = None
        best_w = 0
        for part in srcset.split(","):
            part = part.strip()
            tokens = part.split()
            if len(tokens) < 2:
                continue
            src_val = tokens[0]
            w_str = tokens[1].rstrip("w")
            try:
                w = int(w_str)
            except ValueError:
                w = 0
            if w > best_w:
                best_w = w
                best_url = src_val
        if best_url:
            full = urljoin(base_url, best_url)
            results.add(full)

    # fqimg thumbnails -> derive full-res fimg
    for img in soup.find_all("img", src=re.compile(r"fqimg=")):
        src = img.get("src", "")
        match = re.search(r"fqimg=([\d.]+)", src)
        if match:
            img_id = match.group(1)
            parts = img_id.rsplit(".", 1)
            base_id = parts[0]
            full_url = urljoin(BASE_URL, f"{SITE_ROOT}?fimg={base_id}")
            results.add(full_url)

    # fimg already full-res (with or without size suffix)
    for img in soup.find_all("img", src=re.compile(r"fimg=")):
        src = img.get("src", "")
        if "fqimg=" not in src:
            full_url = urljoin(BASE_URL, src)
            results.add(full_url)

    # fimg with size suffix in inline styles (e.g. background-image: url('/detstvo/?fimg=1.15.320'))
    for tag in soup.find_all(lambda t: t.get("style") and "fimg=" in t.get("style", "")):
        style = tag["style"]
        for m in re.finditer(r"fimg=([\d.]+)", style):
            img_id = m.group(1)
            parts = img_id.rsplit(".", 1)
            if len(parts) == 2 and parts[1].isdigit():
                base_id = parts[0]
                full_url = urljoin(BASE_URL, f"{SITE_ROOT}?fimg={base_id}")
                results.add(full_url)

    # Relative static assets in inline styles (e.g. sph_templates/glozzom2/img/title1.jpg)
    for tag in soup.find_all(lambda t: t.get("style") and "url(" in t.get("style", "")):
        style = tag["style"]
        for m in re.finditer(r"url\(['\"]?([^'\"()]+)['\"]?\)", style):
            asset_path = m.group(1)
            if asset_path.startswith("data:") or asset_path.startswith("http") or asset_path.startswith("./"):
                continue
            if "fimg=" in asset_path or "fqimg=" in asset_path:
                # Already handled above - skip to avoid double-prefixed URLs
                continue
            full_url = urljoin(BASE_URL, f"{SITE_ROOT}{asset_path}")
            results.add(full_url)

    # Regular img src
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:") or src.startswith("//"):
            continue
        full = urljoin(base_url, src)
        parsed = urlparse(full)
        if "tambov.ru.net" in parsed.netloc or not parsed.netloc:
            if SITE_ROOT in parsed.path or "sph_templates" in parsed.path or "js/" in parsed.path:
                results.add(full)

    return results


def url_to_filepath(url):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if parsed.path.rstrip("/") == SITE_ROOT.rstrip("/") and not qs:
        return "index.html"
    if parsed.path.rstrip("/") == SITE_ROOT.rstrip("/"):
        parts = []
        for k, v in qs.items():
            for val in v:
                parts.append(f"{k}-{val}")
        if parts:
            fname = "_".join(parts)
            fname = re.sub(r'[<>:"/\\|?*]', '_', fname)
            return f"{fname}.html"
    rel = parsed.path[len(SITE_ROOT):].lstrip("/") if parsed.path.startswith(SITE_ROOT) else parsed.path.lstrip("/")
    if not rel:
        rel = "index"
    rel = re.sub(r'[<>:"/\\|?*]', '_', rel)
    if qs:
        parts = []
        for k, v in qs.items():
            for val in v:
                parts.append(f"{k}-{val}")
        rel += "_" + "_".join(parts)
    rel = re.sub(r'[<>:"/\\|?*]', '_', rel)
    return f"{rel}.html"


def download_page(url):
    if url in downloaded_urls:
        return None
    downloaded_urls.add(url)

    full_url = urljoin(BASE_URL, url)
    print(f"\n=== Crawling: {full_url} ===")

    resp = safe_get(full_url)
    if resp == "SKIP":
        print(f"  [SKIP] Too many 500s, skipping {url}")
        return None
    if resp is None:
        print(f"  [FAIL] Could not fetch: {url}")
        return None

    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup.find_all(is_tracker_script):
        tag.decompose()

    # --- Download all images ---
    image_urls = extract_image_urls(soup, full_url)
    for img_url in image_urls:
        parsed = urlparse(img_url)

        if "fimg=" in parsed.query:
            match = re.search(r"fimg=([\d.]+)", parsed.query)
            if match:
                fname = f"fimg-{match.group(1)}.jpg"
                local = download_file(img_url, subdir="img", filename=fname)
                if local:
                    full_img_url = urljoin(BASE_URL, img_url)
                    IMAGE_MAP[full_img_url] = local.replace("\\", "/")
                    for q in re.findall(r"fqimg=([\d.]+)", resp.text):
                        if q.startswith(match.group(1)):
                            thumb_url = f"{SITE_ROOT}?fqimg={q}"
                            IMAGE_MAP[urljoin(BASE_URL, thumb_url)] = local.replace("\\", "/")

        elif "fqimg=" in parsed.query:
            match = re.search(r"fqimg=([\d.]+)", parsed.query)
            if match:
                base = match.group(1).rsplit(".", 1)[0]
                fname = f"fimg-{base}.jpg"
                full_img_url = urljoin(BASE_URL, f"{SITE_ROOT}?fimg={base}")
                if full_img_url not in downloaded_images:
                    local = download_file(full_img_url, subdir="img", filename=fname)
                    if local:
                        IMAGE_MAP[full_img_url] = local.replace("\\", "/")
                IMAGE_MAP[urljoin(BASE_URL, img_url)] = f"img/{fname}"
        else:
            img_path = parsed.path
            rel_path = img_path[len(SITE_ROOT):] if img_path.startswith(SITE_ROOT) else img_path.lstrip("/")
            ext = os.path.splitext(rel_path)[1].lower()
            if ext in (".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot"):
                fname = rel_path.replace("/", "_").replace("\\", "_")
                local = download_file(img_url, subdir="assets", filename=fname)
                if local:
                    IMAGE_MAP[urljoin(BASE_URL, img_url)] = local.replace("\\", "/")

    # --- Download CSS ---
    for link in soup.find_all("link", rel=re.compile(r"stylesheet", re.I)):
        href = link.get("href", "")
        if not href:
            continue
        full_href = urljoin(BASE_URL, href)
        parsed_href = urlparse(full_href)
        if "tambov.ru.net" in parsed_href.netloc or not parsed_href.netloc:
            rel_path = href[len(SITE_ROOT):] if href.startswith(SITE_ROOT) else href.lstrip("/")
            fname = rel_path.replace("/", "_").replace("\\", "_")
            if full_href not in downloaded_images:
                local = download_file(href, subdir="assets", filename=fname)
                if local:
                    IMAGE_MAP[full_href] = local.replace("\\", "/")

    # --- Download JS ---
    for script in soup.find_all("script", src=True):
        src = script.get("src", "")
        if not src:
            continue
        full_src = urljoin(BASE_URL, src)
        parsed_src = urlparse(full_src)
        if "tambov.ru.net" in parsed_src.netloc or not parsed_src.netloc:
            rel_path = src[len(SITE_ROOT):] if src.startswith(SITE_ROOT) else src.lstrip("/")
            fname = rel_path.replace("/", "_").replace("\\", "_")
            if full_src not in downloaded_images:
                local = download_file(src, subdir="assets", filename=fname)
                if local:
                    IMAGE_MAP[full_src] = local.replace("\\", "/")

    # --- Rewrite href links ---
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_href = urljoin(full_url, href)
        parsed_href = urlparse(full_href)
        if "tambov.ru.net" in parsed_href.netloc or not parsed_href.netloc:
            if SITE_ROOT in parsed_href.path or SITE_ROOT.rstrip("/") == parsed_href.path:
                page_file = url_to_filepath(full_href)
                a["href"] = f"./{page_file}"
                pages_to_crawl.add(full_href)

    # Rewrite img src/data-src
    for img in soup.find_all("img"):
        for attr in ("src", "data-src"):
            val = img.get(attr)
            if not val:
                continue
            full_val = urljoin(BASE_URL, val)
            if full_val in IMAGE_MAP:
                img[attr] = f"./{IMAGE_MAP[full_val]}"
            else:
                parsed_val = urlparse(full_val)
                if "fimg=" in parsed_val.query or "fqimg=" in parsed_val.query:
                    match = re.search(r"f(img|qimg)=([\d.]+)", parsed_val.query)
                    if match:
                        base_id = match.group(2).rsplit(".", 1)[0] if match.group(1) == "qimg" else match.group(2)
                        img[attr] = f"./img/fimg-{base_id}.jpg"

    # Rewrite link CSS
    for link in soup.find_all("link"):
        href = link.get("href", "")
        if not href:
            continue
        full_href = urljoin(BASE_URL, href)
        if full_href in IMAGE_MAP:
            link["href"] = f"./{IMAGE_MAP[full_href]}"

    # Rewrite script src
    for script in soup.find_all("script", src=True):
        src = script["src"]
        full_src = urljoin(BASE_URL, src)
        if full_src in IMAGE_MAP:
            script["src"] = f"./{IMAGE_MAP[full_src]}"

    # Rewrite inline background-image
    for tag in soup.find_all(lambda t: t.get("style") and "background-image" in t.get("style", "").lower()):
        style = tag["style"]
        urls_in_style = re.findall(r"url\(['\"]?(.*?)['\"]?\)", style)
        for url_in_style in urls_in_style:
            full_style_url = urljoin(BASE_URL, url_in_style)
            # Try direct URL map
            if full_style_url in IMAGE_MAP:
                new_url = f"./{IMAGE_MAP[full_style_url]}"
                style = style.replace(url_in_style, new_url)
            else:
                # Handle /detstvo/?fimg=X.Y.Z -> derive base and map to ./img/fimg-X.Y.jpg
                fimg_match = re.search(r"fimg=([\d]+\.)([\d]+)(?:\.(\d+))?", url_in_style)
                if fimg_match:
                    base_id = fimg_match.group(1) + fimg_match.group(2)
                    new_url = f"./img/fimg-{base_id}.jpg"
                    style = style.replace(url_in_style, new_url)
                else:
                    # Handle /detstvo/?fqimg=X.Y.Z -> derive base
                    fqimg_match = re.search(r"fqimg=([\d]+\.)([\d]+)(?:\.(\d+))?", url_in_style)
                    if fqimg_match:
                        base_id = fqimg_match.group(1) + fqimg_match.group(2)
                        new_url = f"./img/fimg-{base_id}.jpg"
                        style = style.replace(url_in_style, new_url)
                    elif not url_in_style.startswith("data:") and not url_in_style.startswith("./"):
                        # Relative static asset path (e.g. sph_templates/...)
                        rel_path = url_in_style.lstrip("/")
                        asset_url = urljoin(BASE_URL, f"{SITE_ROOT}{rel_path}")
                        if asset_url in IMAGE_MAP:
                            new_url = f"./{IMAGE_MAP[asset_url]}"
                            style = style.replace(url_in_style, new_url)
                        else:
                            # Fallback: map to assets directory
                            fname = rel_path.replace("/", "_").replace("\\", "_")
                            new_url = f"./assets/{fname}"
                            style = style.replace(url_in_style, new_url)
        tag["style"] = style

    # Save HTML
    page_file = url_to_filepath(url)
    save_path = MIRROR_DIR / page_file
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(str(soup))
    print(f"  [SAVED] {page_file}")
    return page_file


def seed_pages():
    pages = [
        f"{SITE_ROOT}",
        f"{SITE_ROOT}?read=about",
        f"{SITE_ROOT}?read=about-about",
        f"{SITE_ROOT}?read=about-targets",
        f"{SITE_ROOT}?read=about-relevance",
        f"{SITE_ROOT}?read=about-geography",
        f"{SITE_ROOT}?read=pub-concept",
        f"{SITE_ROOT}?read=socialnet",
        f"{SITE_ROOT}?id=anews",
        f"{SITE_ROOT}?id=anews&page=2",
        f"{SITE_ROOT}?id=anews&page=3",
        f"{SITE_ROOT}?id=anews&page=4",
        f"{SITE_ROOT}?id=anews&page=5",
        f"{SITE_ROOT}?read=memories",
        f"{SITE_ROOT}?read=memories-video",
        f"{SITE_ROOT}?read=memories-audio",
        f"{SITE_ROOT}?read=memories-text",
        f"{SITE_ROOT}?read=exhibition",
        f"{SITE_ROOT}?read=publication",
        f"{SITE_ROOT}?view=photos",
    ]
    for p in pages:
        pages_to_crawl.add(urljoin(BASE_URL, p))

    news_ids = list(range(33, 45))
    for nid in news_ids:
        pages_to_crawl.add(urljoin(BASE_URL, f"{SITE_ROOT}?id=anews.view.{nid}"))


def copy_static_assets():
    for asset in [f"{SITE_ROOT}favicon.ico", f"{SITE_ROOT}robots.txt"]:
        full_url = urljoin(BASE_URL, asset)
        parsed = urlparse(full_url)
        rel = parsed.path[len(SITE_ROOT):].lstrip("/") if parsed.path.startswith(SITE_ROOT) else parsed.path.lstrip("/")
        if rel:
            download_file(asset, subdir="", filename=rel)


def main():
    if FAILED_URLS_FILE.exists():
        FAILED_URLS_FILE.unlink()

    print("=" * 60)
    print("  Mirror: tambov.ru.net/detstvo/")
    print("  Delay: 3-5s between requests | 500 limit: 2")
    print("=" * 60)

    seed_pages()
    copy_static_assets()

    static_urls = [
        f"{SITE_ROOT}sph_templates/glozzom2/img/title1.jpg",
        f"{SITE_ROOT}sph_templates/glozzom2/sph.css",
        f"{SITE_ROOT}sph_templates/glozzom2/glozzom2.css",
        f"{SITE_ROOT}sph_templates/glozzom2/styles/layout.css",
        f"{SITE_ROOT}sph_templates/glozzom2/read/css/read.css",
        f"{SITE_ROOT}js/jquery/jquery-3.3.1.min.js",
        f"{SITE_ROOT}js/jquery/jquery.backtotop.js",
        f"{SITE_ROOT}js/jquery/jquery.mobilemenu.js",
        f"{SITE_ROOT}js/jquery/lightgallery.css",
        f"{SITE_ROOT}js/jquery/lightgallery-all-1.6.12.min.js",
        f"{SITE_ROOT}js/jquery/jquery.mousewheel.min.js",
        f"{SITE_ROOT}js/sph.js",
    ]
    for static_url in static_urls:
        full = urljoin(BASE_URL, static_url)
        parsed = urlparse(full)
        rel = parsed.path[len(SITE_ROOT):].lstrip("/") if parsed.path.startswith(SITE_ROOT) else parsed.path.lstrip("/")
        if rel:
            fname = rel.replace("/", "_").replace("\\", "_")
            local = download_file(static_url, subdir="assets", filename=fname)
            if local:
                IMAGE_MAP[full] = local.replace("\\", "/")

    # Crawl pages with polite delay
    crawled_this_round = set()
    while pages_to_crawl:
        url = pages_to_crawl.pop()
        if url in crawled_this_round or url in downloaded_urls:
            continue
        crawled_this_round.add(url)

        parsed_url = urlparse(url)
        relative_url = parsed_url.path + ("?" + parsed_url.query if parsed_url.query else "")
        if SITE_ROOT in parsed_url.path:
            rel_part = parsed_url.path[len(SITE_ROOT.rstrip("/")):] if parsed_url.path.startswith(SITE_ROOT) else parsed_url.path
            q = parsed_url.query
            relative_url = SITE_ROOT.rstrip("/") + rel_part + ("?" + q if q else "")

        download_page(relative_url)

        # Polite delay between requests
        if pages_to_crawl:
            polite_delay()

    print("\n" + "=" * 60)
    pages = len(list(MIRROR_DIR.glob("*.html")))
    imgs = len(list((MIRROR_DIR / "img").glob("*"))) if (MIRROR_DIR / "img").exists() else 0
    assets = len(list((MIRROR_DIR / "assets").glob("*"))) if (MIRROR_DIR / "assets").exists() else 0
    print(f"  Done! Pages: {pages} | Images: {imgs} | Assets: {assets}")
    if FAILED_URLS_FILE.exists():
        lines = [l for l in FAILED_URLS_FILE.read_text().strip().split("\n") if l]
        if lines:
            print(f"  Failed URLs logged: {len(lines)}")
            print(f"  See: {FAILED_URLS_FILE.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
