import os
import re
import json
from urllib.parse import urlparse, urljoin, parse_qs
from pathlib import Path
import time

import requests
from bs4 import BeautifulSoup, Tag, Comment
import difflib

BASE_URL = "https://tambov.ru.net"
SITE_ROOT = "/detstvo/"
MIRROR_DIR = Path(__file__).parent.resolve()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


def filepath_to_url(filepath):
    name = filepath.stem
    if name == "index":
        return f"{BASE_URL}{SITE_ROOT}"
    query_map = {
        "read-about": ("read", "about"),
        "read-about-about": ("read", "about-about"),
        "read-about-targets": ("read", "about-targets"),
        "read-about-relevance": ("read", "about-relevance"),
        "read-about-geography": ("read", "about-geography"),
        "read-pub-concept": ("read", "pub-concept"),
        "read-socialnet": ("read", "socialnet"),
        "read-memories": ("read", "memories"),
        "read-memories-video": ("read", "memories-video"),
        "read-memories-audio": ("read", "memories-audio"),
        "read-memories-text": ("read", "memories-text"),
        "read-exhibition": ("read", "exhibition"),
        "read-publication": ("read", "publication"),
        "view-photos": ("view", "photos"),
    }
    if name in query_map:
        k, v = query_map[name]
        return f"{BASE_URL}{SITE_ROOT}?{k}={v}"
    if name == "id-anews":
        return f"{BASE_URL}{SITE_ROOT}?id=anews"
    m = re.match(r'^id-anews_page-(\d+)$', name)
    if m:
        return f"{BASE_URL}{SITE_ROOT}?id=anews&page={m.group(1)}"
    m = re.match(r'^id-anews\.main_page-(\d+)$', name)
    if m:
        return f"{BASE_URL}{SITE_ROOT}?id=anews.main&page={m.group(1)}"
    m = re.match(r'^id-anews\.view\.(\d+)$', name)
    if m:
        return f"{BASE_URL}{SITE_ROOT}?id=anews.view.{m.group(1)}"
    return f"{BASE_URL}{SITE_ROOT}?id={name}"


def get_all_local_html_files():
    files = []
    for f in sorted(MIRROR_DIR.glob("*.html")):
        if f.name.startswith("dload-"):
            continue
        files.append(f)
    return files


def is_tracker_or_noise(tag):
    if not isinstance(tag, Tag):
        return False
    if tag.name == "script":
        src = tag.get("src", "")
        text = tag.get_text(strip=True)
        if any(kw in src.lower() for kw in ["yandex", "metrika", "google-analytics", "gtag", "counter", "mc.yandex"]):
            return True
        if any(kw in text.lower() for kw in ["ym(", "gtag(", "ga(", "yandex.metrika"]):
            return True
    if tag.name == "noscript":
        img = tag.find("img")
        if img and "mc.yandex" in img.get("src", "").lower():
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


def strip_noise(soup):
    for tag in soup.find_all(is_tracker_or_noise):
        tag.decompose()
    for tag in soup.find_all("script"):
        if not tag.get("src") and not tag.get_text(strip=True):
            tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()


def normalize_path(path):
    path = path.rstrip("/") or "/"
    path = re.sub(r'//+', '/', path)
    return path


def local_href_to_original_path(href):
    if not href.startswith("./"):
        return None
    name = href[2:]
    if not name.endswith(".html"):
        return None
    stem = name[:-5]

    query_map = {
        "index": None,
        "read-about": "read=about",
        "read-about-about": "read=about-about",
        "read-about-targets": "read=about-targets",
        "read-about-relevance": "read=about-relevance",
        "read-about-geography": "read=about-geography",
        "read-pub-concept": "read=pub-concept",
        "read-socialnet": "read=socialnet",
        "read-memories": "read=memories",
        "read-memories-video": "read=memories-video",
        "read-memories-audio": "read=memories-audio",
        "read-memories-text": "read=memories-text",
        "read-exhibition": "read=exhibition",
        "read-publication": "read=publication",
        "view-photos": "view=photos",
    }
    if stem in query_map:
        q = query_map[stem]
        return f"{SITE_ROOT}" + (f"?{q}" if q else "")
    if stem == "id-anews":
        return f"{SITE_ROOT}?id=anews"
    m = re.match(r'^id-anews_page-(\d+)$', stem)
    if m:
        return f"{SITE_ROOT}?id=anews&page={m.group(1)}"
    m = re.match(r'^id-anews\.main_page-(\d+)$', stem)
    if m:
        return f"{SITE_ROOT}?id=anews.main&page={m.group(1)}"
    m = re.match(r'^id-anews\.view\.(\d+)$', stem)
    if m:
        return f"{SITE_ROOT}?id=anews.view.{m.group(1)}"
    return f"{SITE_ROOT}?id={stem}"


def normalize_link_for_comparison(href):
    if not href:
        return href

    if href.startswith("./"):
        anchor = ""
        href_no_anchor = href
        if "#" in href:
            href_no_anchor, anchor = href.split("#", 1)
            anchor = "#" + anchor
        orig = local_href_to_original_path(href_no_anchor)
        if orig:
            return normalize_path(orig) + anchor
        # Static asset: ./assets/... -> skip or map
        name = href_no_anchor[2:]
        if name.startswith("assets/") or name.startswith("img/"):
            return f"__asset__{name}"
        return href

    if href.startswith("/"):
        return normalize_path(href)

    if href.startswith("http"):
        parsed = urlparse(href)
        if "tambov.ru.net" in parsed.netloc:
            path = normalize_path(parsed.path)
            query = parsed.query
            return path + ("?" + query if query else "")
        return href

    return href


def normalize_image_for_comparison(src):
    if not src:
        return src

    if src.startswith("./"):
        name = src[2:]
        # Image: ./img/fimg-X.Y.jpg
        m = re.match(r'^img/fimg-([\d]+\.)([\d]+)\.jpg$', name)
        if m:
            return f"{SITE_ROOT}?fimg={m.group(1)}{m.group(2)}"
        # Thumbnail: ./img/fqimg-X.Y.Z.jpg -> map to fimg=X.Y
        m = re.match(r'^img/fqimg-([\d]+\.)([\d]+)(?:\.\d+)?\.jpg$', name)
        if m:
            return f"{SITE_ROOT}?fimg={m.group(1)}{m.group(2)}"
        # Static asset
        return f"__asset__{name}"

    if src.startswith("/"):
        return src

    if src.startswith("http"):
        parsed = urlparse(src)
        if "tambov.ru.net" in parsed.netloc:
            path = parsed.path
            query = parsed.query
            return path + ("?" + query if query else "")
        return src

    # Relative paths like sph_templates/glozzom2/img/title1.jpg
    if "sph_templates" in src or src.startswith("js/") or src.startswith("assets/"):
        return f"__asset__{src}"

    return src


def original_image_to_key(src):
    """Convert original image URL to a normalized comparison key.
    fqimg=X.Y.Z -> fimg=X.Y (treat thumbnails and full-size as same)
    sph_templates/... -> __asset__... (flatten path)
    """
    if not src:
        return src

    if src.startswith("/"):
        # Check for fimg/fqimg query params
        parsed = urlparse(src)
        qs = parse_qs(parsed.query)
        if "fqimg" in qs:
            match = re.match(r'^([\d]+\.)([\d]+)', qs["fqimg"][0])
            if match:
                return f"{SITE_ROOT}?fimg={match.group(1)}{match.group(2)}"
        if "fimg" in qs:
            match = re.match(r'^([\d]+\.)([\d]+)', qs["fimg"][0])
            if match:
                return f"{SITE_ROOT}?fimg={match.group(1)}{match.group(2)}"
        # Static asset path
        path = parsed.path
        if "sph_templates" in path or "js/" in path:
            return f"__asset__{path}"
        return src

    if src.startswith("http"):
        parsed = urlparse(src)
        if "tambov.ru.net" in parsed.netloc:
            return original_image_to_key(parsed.path + ("?" + parsed.query if parsed.query else ""))
        return src

    # Relative paths like sph_templates/glozzom2/img/title1.jpg
    if "sph_templates" in src or src.startswith("js/") or src.startswith("assets/"):
        return f"__asset__{src}"

    return src


def extract_normalized_links(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    strip_noise(soup)
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        norm = normalize_link_for_comparison(href)
        links.add(norm)
    return links


def extract_normalized_images(html_text, is_original=False):
    soup = BeautifulSoup(html_text, "html.parser")
    strip_noise(soup)
    images = set()
    for img in soup.find_all("img"):
        for attr in ("src", "data-src"):
            val = img.get(attr, "")
            if val and not val.startswith("data:") and not val.startswith("about:"):
                if is_original:
                    images.add(original_image_to_key(val))
                else:
                    images.add(normalize_image_for_comparison(val))
    for tag in soup.find_all(True):
        style = tag.get("style", "")
        for m in re.finditer(r"url\(['\"]?([^'\"()]+)['\"]?\)", style):
            u = m.group(1)
            if not u.startswith("data:"):
                if is_original:
                    images.add(original_image_to_key(u))
                else:
                    images.add(normalize_image_for_comparison(u))
    # Filter out asset references that can't be compared
    images = {img for img in images if not img.startswith("__asset__")}
    return images


def extract_text(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    strip_noise(soup)
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r'\s+', ' ', text)


def extract_tag_keys(html_text, max_depth=15):
    soup = BeautifulSoup(html_text, "html.parser")
    strip_noise(soup)
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    def walk(el, depth=0):
        if depth > max_depth or not isinstance(el, Tag):
            return []
        result = []
        key = el.name
        classes = el.get("class", [])
        if classes:
            key += "." + ".".join(sorted(classes))
        result.append(key)
        for child in el.children:
            result.extend(walk(child, depth + 1))
        return result

    body = soup.find("body") or soup
    return walk(body)


def extract_headings(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    strip_noise(soup)
    return [(h.name, h.get_text(strip=True)[:200]) for h in soup.find_all(["h1","h2","h3","h4","h5","h6"])]


def extract_title(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""


def compare_pair(orig_html, local_html, page_url=None):
    diffs = []

    t_orig = extract_title(orig_html)
    t_local = extract_title(local_html)
    if t_orig and t_local and t_orig != t_local:
        diffs.append({"type": "title_diff", "message": f"Title differs: orig=\"{t_orig[:100]}\" vs local=\"{t_local[:100]}\""})

    txt_orig = extract_text(orig_html)
    txt_local = extract_text(local_html)
    if txt_orig != txt_local:
        ratio = difflib.SequenceMatcher(None, txt_orig, txt_local).ratio()
        if ratio < 0.995:
            ow = txt_orig.split()
            lw = txt_local.split()
            sm = difflib.SequenceMatcher(None, ow[:500], lw[:500])
            first_change = None
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "equal":
                    o_sample = " ".join(ow[i1:min(i2, i1+5)])[:150]
                    l_sample = " ".join(lw[j1:min(j2, j1+5)])[:150]
                    first_change = f"[{tag}] orig=\"{o_sample}\" vs local=\"{l_sample}\""
                    break
            msg = f"Text differs (similarity: {ratio:.1%})"
            if first_change:
                msg += f"; {first_change}"
            diffs.append({"type": "text_diff", "message": msg})

    hk_orig = extract_tag_keys(orig_html)
    hk_local = extract_tag_keys(local_html)
    if hk_orig != hk_local:
        s_orig = set(hk_orig)
        s_local = set(hk_local)
        missing = s_orig - s_local
        extra = s_local - s_orig
        if missing:
            sample = sorted(missing)[:8]
            diffs.append({"type": "missing_structure", "message": f"Missing elements: {', '.join(sample)}{'...' if len(missing)>8 else ''}"})
        if extra:
            sample = sorted(extra)[:8]
            diffs.append({"type": "extra_structure", "message": f"Extra elements: {', '.join(sample)}{'...' if len(extra)>8 else ''}"})

    hdg_orig = extract_headings(orig_html)
    hdg_local = extract_headings(local_html)
    if len(hdg_orig) != len(hdg_local):
        diffs.append({"type": "heading_count", "message": f"Heading count: orig={len(hdg_orig)}, local={len(hdg_local)}"})
    else:
        for i, (oh, lh) in enumerate(zip(hdg_orig, hdg_local)):
            if oh != lh:
                diffs.append({"type": "heading_diff", "message": f"H{i+1}: orig=<{oh[0]}>\"{oh[1][:80]}\" local=<{lh[0]}>\"{lh[1][:80]}\""})

    lk_orig = extract_normalized_links(orig_html)
    lk_local = extract_normalized_links(local_html)
    # Filter out asset links
    lk_orig = {l for l in lk_orig if not l.startswith("__asset__")}
    lk_local = {l for l in lk_local if not l.startswith("__asset__")}

    missing_lk = lk_orig - lk_local
    if missing_lk:
        sample = sorted(missing_lk)[:10]
        diffs.append({"type": "missing_links", "message": f"Missing links ({len(missing_lk)}): {', '.join(sample)}{'...' if len(missing_lk)>10 else ''}"})
    extra_lk = lk_local - lk_orig
    if extra_lk:
        sample = sorted(extra_lk)[:10]
        diffs.append({"type": "extra_links", "message": f"Extra links ({len(extra_lk)}): {', '.join(sample)}{'...' if len(extra_lk)>10 else ''}"})

    im_orig = extract_normalized_images(orig_html, is_original=True)
    im_local = extract_normalized_images(local_html, is_original=False)
    missing_im = im_orig - im_local
    if missing_im:
        sample = sorted(missing_im)[:10]
        diffs.append({"type": "missing_images", "message": f"Missing images ({len(missing_im)}): {', '.join(sample)}{'...' if len(missing_im)>10 else ''}"})
    extra_im = im_local - im_orig
    if extra_im:
        sample = sorted(extra_im)[:5]
        diffs.append({"type": "extra_images", "message": f"Extra images ({len(extra_im)}): {', '.join(sample)}{'...' if len(extra_im)>5 else ''}"})

    return diffs


def crawl_internal_links(start_url, max_pages=300):
    visited = set()
    to_visit = {start_url}
    all_pages = set()
    errors_404 = set()

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 404:
                errors_404.add(url)
                continue
            if resp.status_code != 200:
                continue
            html = resp.text
        except Exception:
            continue

        all_pages.add(url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
                continue
            full = urljoin(url, href)
            parsed = urlparse(full)
            if "tambov.ru.net" not in parsed.netloc:
                continue
            if SITE_ROOT not in parsed.path and parsed.path.rstrip("/") != SITE_ROOT.rstrip("/"):
                continue
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean += "?" + parsed.query
            if clean not in visited and clean not in errors_404:
                to_visit.add(clean)

    return all_pages, errors_404


def run_audit():
    print("=" * 70)
    print("  SITE AUDIT: tambov.ru.net/detstvo/ vs local mirror")
    print("=" * 70)

    local_files = get_all_local_html_files()
    print(f"\n[1/4] Found {len(local_files)} local HTML files")

    url_map = {}
    for f in local_files:
        url = filepath_to_url(f)
        url_map[f] = url
    print(f"[2/4] Mapped {len(url_map)} files to original URLs")

    print("[3/4] Crawling original site for additional pages...")
    crawled, errors_404 = crawl_internal_links(f"{BASE_URL}{SITE_ROOT}", max_pages=300)
    print(f"  Discovered {len(crawled)} pages ({len(errors_404)} 404s skipped)")

    known_urls = set(url_map.values())
    known_url_normalized = set()
    for u in known_urls:
        parsed = urlparse(u)
        norm = normalize_path(parsed.path) + ("?" + parsed.query if parsed.query else "")
        known_url_normalized.add(norm)

    extra_urls = set()
    for u in crawled:
        parsed = urlparse(u)
        norm = normalize_path(parsed.path) + ("?" + parsed.query if parsed.query else "")
        if norm not in known_url_normalized:
            extra_urls.add(u)

    print(f"  {len(extra_urls)} pages on original not in local mirror")

    print(f"\n[4/4] Comparing {len(url_map)} pages...\n")

    results = []
    perfect = 0
    with_diffs = 0
    missing_local = 0
    errors_count = 0
    total = len(url_map) + len(extra_urls)
    done = 0

    for filepath, url in sorted(url_map.items(), key=lambda x: x[0].name):
        done += 1
        local_html = filepath.read_text(encoding="utf-8", errors="replace")
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200:
                results.append({
                    "url": url, "local_file": filepath.name,
                    "status": f"HTTP_{resp.status_code}", "diffs": []
                })
                errors_count += 1
                print(f"  [{done}/{total}] HTTP {resp.status_code}: {filepath.name}")
                continue
            orig_html = resp.text
        except Exception as e:
            results.append({
                "url": url, "local_file": filepath.name,
                "status": "FETCH_ERROR", "diffs": [{"type": "fetch_error", "message": str(e)}]
            })
            errors_count += 1
            print(f"  [{done}/{total}] FETCH ERROR: {filepath.name}")
            continue

        diffs = compare_pair(orig_html, local_html, url)

        if diffs:
            results.append({
                "url": url, "local_file": filepath.name,
                "status": "HAS_DIFFS", "diffs": diffs
            })
            with_diffs += 1
            diff_types = [d["type"] for d in diffs]
            print(f"  [{done}/{total}] DIFFS({len(diffs)}): {filepath.name} [{', '.join(diff_types[:3])}]")
        else:
            results.append({
                "url": url, "local_file": filepath.name,
                "status": "OK", "diffs": []
            })
            perfect += 1
            print(f"  [{done}/{total}] OK: {filepath.name}")

    for url in sorted(extra_urls):
        done += 1
        parsed = urlparse(url)
        q = "?" + parsed.query if parsed.query else ""
        results.append({
            "url": url, "local_file": "N/A",
            "status": "MISSING_LOCAL", "diffs": []
        })
        missing_local += 1
        print(f"  [{done}/{total}] MISSING: {parsed.path}{q}")

    report = {
        "summary": {
            "total_discovered": len(crawled),
            "local_files": len(local_files),
            "pages_compared": len(url_map),
            "perfect": perfect,
            "has_diffs": with_diffs,
            "missing_local": missing_local,
            "fetch_errors": errors_count
        },
        "pages": results
    }

    json_path = MIRROR_DIR / "audit_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md_path = MIRROR_DIR / "audit_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Site Audit Report: tambov.ru.net/detstvo/\n\n")
        f.write("**Date**: 2026-07-23\n\n")
        f.write("## Summary\n\n")
        f.write("| Metric | Count |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Pages discovered on original | {report['summary']['total_discovered']} |\n")
        f.write(f"| Local HTML files | {report['summary']['local_files']} |\n")
        f.write(f"| Pages compared | {report['summary']['pages_compared']} |\n")
        f.write(f"| Perfect (no diffs) | {report['summary']['perfect']} |\n")
        f.write(f"| Pages with differences | {report['summary']['has_diffs']} |\n")
        f.write(f"| Missing locally | {report['summary']['missing_local']} |\n")
        f.write(f"| Fetch errors | {report['summary']['fetch_errors']} |\n")
        f.write("\n---\n\n")

        missing = [p for p in results if p["status"] == "MISSING_LOCAL"]
        if missing:
            f.write(f"## Missing Local Pages ({len(missing)})\n\n")
            f.write("| # | URL |\n|---|-----|\n")
            for idx, p in enumerate(missing, 1):
                f.write(f"| {idx} | {p['url']} |\n")
            f.write("\n")

        diff_pages = [p for p in results if p["status"] == "HAS_DIFFS"]
        if diff_pages:
            f.write(f"## Pages with Differences ({len(diff_pages)})\n\n")
            for p in diff_pages:
                f.write(f"### {p['url']}\n")
                f.write(f"**Local file**: `{p['local_file']}`\n\n")
                for d in p["diffs"]:
                    f.write(f"- **[{d['type']}]** {d['message']}\n")
                f.write("\n")

        err_pages = [p for p in results if "FETCH_ERROR" in p["status"] or "HTTP_" in p["status"]]
        if err_pages:
            f.write(f"## Fetch Errors ({len(err_pages)})\n\n")
            for p in err_pages:
                f.write(f"- **{p['url']}** -> `{p['local_file']}` ({p['status']})\n")
            f.write("\n")

        ok_pages = [p for p in results if p["status"] == "OK"]
        f.write(f"## Perfect Pages ({len(ok_pages)})\n\n")
        for p in ok_pages:
            f.write(f"- `{p['local_file']}` <=> {p['url']}\n")

    print(f"\n  Reports saved:")
    print(f"    {json_path}")
    print(f"    {md_path}")

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Pages discovered (original): {report['summary']['total_discovered']}")
    print(f"  Local HTML files:            {report['summary']['local_files']}")
    print(f"  Pages compared:              {report['summary']['pages_compared']}")
    print(f"  Perfect (no diffs):          {report['summary']['perfect']}")
    print(f"  Has differences:             {report['summary']['has_diffs']}")
    print(f"  Missing locally:             {report['summary']['missing_local']}")
    print(f"  Fetch errors:                {report['summary']['fetch_errors']}")
    print(f"{'='*70}")

    return report


if __name__ == "__main__":
    run_audit()



