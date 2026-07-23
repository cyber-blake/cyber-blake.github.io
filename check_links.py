#!/usr/bin/env python3
import os, re, sys, json, hashlib, urllib.parse
from pathlib import Path
from html.parser import HTMLParser
from collections import defaultdict
import urllib.request, ssl, time

BASE_DIR = Path(r"D:\site_nginx\detstvo")
SITE_URL = "https://tambov.ru.net/detstvo"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []
        self.css_links = []
        self.js_links = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and "href" in d:
            self.links.append(d["href"])
        if tag == "img" and "src" in d:
            self.images.append(d["src"])
        if tag == "link" and "href" in d:
            self.css_links.append(d["href"])
        if tag == "script" and "src" in d:
            self.js_links.append(d["src"])

def extract_links_from_file(filepath):
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return None, str(e)
    parser = LinkExtractor()
    try:
        parser.feed(content)
    except Exception as e:
        return None, str(e)
    return {
        "links": parser.links,
        "images": parser.images,
        "css": parser.css_links,
        "js": parser.js_links,
        "content_hash": hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest(),
    }, None

def check_local_link_exists(html_file, href):
    if href.startswith(("http://", "https://", "mailto:", "javascript:", "#", "tel:")):
        return None, "external"
    href_clean = href.split("#")[0]
    if not href_clean:
        return None, "external"
    href_clean = urllib.parse.unquote(href_clean)
    resolved = (html_file.parent / href_clean).resolve()
    if resolved.exists():
        return str(resolved), "ok"
    index_path = resolved / "index.html"
    if index_path.exists():
        return str(index_path), "ok"
    return str(resolved), "BROKEN"

def get_all_html_files():
    html_files = []
    for f in BASE_DIR.rglob("*.html"):
        if "__pycache__" in str(f):
            continue
        html_files.append(f)
    return sorted(html_files)

def fetch_url(url, retries=2):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                content = resp.read()
                return content, resp.status, resp.geturl()
        except Exception as e:
            if attempt == retries:
                return None, str(e), url
            time.sleep(1)

def crawl_site(base_url, max_pages=200):
    visited = set()
    to_visit = [base_url + "/"]
    all_links = {}
    all_images = {}
    page_contents = {}
    errors = []
    seen = set()
    while to_visit and len(visited) < max_pages:
        url = to_visit.pop(0)
        normalized = url.split("#")[0].rstrip("/")
        if normalized in visited:
            continue
        visited.add(normalized)
        print("  Fetching: " + normalized, flush=True)
        content, status, final_url = fetch_url(url)
        if content is None:
            errors.append("FETCH ERROR: " + normalized + " -> " + str(status))
            continue
        if isinstance(status, int) and status != 200:
            errors.append("HTTP " + str(status) + ": " + normalized)
            continue
        try:
            html = content.decode("utf-8", errors="replace")
        except:
            errors.append("DECODE ERROR: " + normalized)
            continue
        content_hash = hashlib.md5(html.encode("utf-8", errors="replace")).hexdigest()
        page_contents[normalized] = content_hash
        parser = LinkExtractor()
        try:
            parser.feed(html)
        except:
            errors.append("PARSE ERROR: " + normalized)
            continue
        all_links[normalized] = parser.links
        all_images[normalized] = parser.images
        base_path = base_url.rstrip("/") + "/"
        for href in parser.links:
            if href.startswith(("mailto:", "javascript:", "tel:", "#")):
                continue
            abs_url = None
            if href.startswith("http://") or href.startswith("https://"):
                abs_url = href
            elif href.startswith("/"):
                abs_url = base_url.split("/detstvo")[0] + href
            elif href.startswith("?"):
                abs_url = base_path.rstrip("/") + "/" + href
            else:
                abs_url = base_path + href
            if abs_url is None:
                continue
            clean = abs_url.split("#")[0].rstrip("/")
            if "/detstvo" in clean and clean.startswith("http") and "tambov.ru.net" in clean:
                if clean not in visited and clean not in seen:
                    to_visit.append(clean)
                    seen.add(clean)
        time.sleep(0.3)
    return {"links": all_links, "images": all_images, "contents": page_contents, "errors": errors, "visited": visited}

def stem_to_site_key(stem):
    """Convert project HTML filename stem to the VALUE of the site's query parameter.
    Site URL examples:
      ?id=anews.view.1   -> site_key = anews.view.1
      ?id=anews          -> site_key = anews
      ?read=about        -> site_key = about
      ?dload=2.134       -> site_key = 2.134
      ?view=photos       -> site_key = photos
      /detstvo/          -> site_key = index
    """
    if stem == "index":
        return "index"
    if stem.startswith("id-anews.main_page-"):
        page = stem.replace("id-anews.main_page-", "")
        return "anews.main&page=" + page
    if stem.startswith("id-anews_page-"):
        page = stem.replace("id-anews_page-", "")
        return "anews&page=" + page
    if stem.startswith("id-anews.view."):
        return "anews." + stem.split("anews.", 1)[1]
    if stem.startswith("dload-"):
        return stem.replace("dload-", "")
    if stem.startswith("read-"):
        return stem[5:]
    if stem.startswith("view-"):
        return stem[5:]
    if stem.startswith("id-anews"):
        return "anews"
    return stem

def site_url_to_key(url):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if not any(qs.values()):
        return "index"
    for k in ["id", "read", "view", "dload"]:
        if k in qs:
            return qs[k][0]
    return "unknown"

def main():
    print("=" * 80)
    print("PHASE 1: Checking all project links for broken references")
    print("=" * 80)
    html_files = get_all_html_files()
    print("Found " + str(len(html_files)) + " HTML files")
    project_links = {}
    broken_links = []
    for hf in html_files:
        rel_path = hf.relative_to(BASE_DIR)
        result, err = extract_links_from_file(hf)
        if result is None:
            print("  ERROR reading " + str(rel_path) + ": " + err)
            continue
        project_links[str(rel_path)] = result
        for href in result["links"] + result["images"] + result["css"] + result["js"]:
            resolved, status = check_local_link_exists(hf, href)
            if status == "BROKEN":
                broken_links.append({"file": str(rel_path), "href": href, "resolved": resolved})
    print()
    print("--- Broken local links in project: " + str(len(broken_links)) + " ---")
    for bl in broken_links:
        print("  FILE: " + bl["file"])
        print("    HREF: " + bl["href"])
        print("    RESOLVED: " + bl["resolved"])
    if not broken_links:
        print("  (none found)")

    print()
    print("=" * 80)
    print("PHASE 2: Crawling live site")
    print("=" * 80)
    site_data = crawl_site(SITE_URL, max_pages=200)
    print("Crawled " + str(len(site_data["visited"])) + " pages on live site")
    print("Site fetch errors: " + str(len(site_data["errors"])))
    for e in site_data["errors"]:
        print("  " + e)

    print()
    print("=" * 80)
    print("PHASE 3: Comparing project vs live site")
    print("=" * 80)

    site_key_to_url = {}
    for url in site_data["visited"]:
        if "tambov.ru.net/detstvo" not in url:
            continue
        key = site_url_to_key(url)
        if key not in site_key_to_url:
            site_key_to_url[key] = url

    print("Site pages on tambov.ru.net/detstvo: " + str(len(site_key_to_url)))
    for k, u in sorted(site_key_to_url.items()):
        print("  " + k + " -> " + u)

    matched = 0
    unmatched_project = []
    content_diffs = []
    link_diffs = []

    for f, data in sorted(project_links.items()):
        stem = Path(f).stem
        site_key = stem_to_site_key(stem)
        site_url = site_key_to_url.get(site_key)
        if site_url is None:
            unmatched_project.append((f, site_key))
            continue
        matched += 1
        proj_hash = data["content_hash"]
        site_hash = site_data["contents"].get(site_url, "")
        if proj_hash != site_hash:
            content_diffs.append({"file": f, "site": site_url, "proj_hash": proj_hash, "site_hash": site_hash})

        proj_internal = set()
        for href in data["links"]:
            h = href.split("#")[0]
            if h and not h.startswith(("http", "mailto:", "javascript:", "tel:")):
                proj_internal.add(urllib.parse.unquote(h).lstrip("./"))
        site_internal = set()
        if site_url in site_data["links"]:
            for href in site_data["links"][site_url]:
                h = href.split("#")[0]
                if h and not h.startswith(("http", "mailto:", "javascript:", "tel:")):
                    site_internal.add(urllib.parse.unquote(h).lstrip("./"))
        only_proj = proj_internal - site_internal
        only_site = site_internal - proj_internal
        if only_proj or only_site:
            link_diffs.append({"file": f, "site": site_url, "only_project": sorted(only_proj), "only_site": sorted(only_site)})

    print()
    print("--- Matched: " + str(matched) + " files ---")
    print("--- Unmatched project files: " + str(len(unmatched_project)) + " ---")
    for f, key in sorted(unmatched_project):
        print("  " + f + " (expected key: " + key + ")")
    print()
    print("--- Content differences: " + str(len(content_diffs)) + " ---")
    for d in content_diffs:
        print("  FILE: " + d["file"] + " vs " + d["site"])
        print("    Project hash: " + d["proj_hash"])
        print("    Site hash:     " + d["site_hash"])
    if not content_diffs:
        print("  (none)")
    print()
    print("--- Link differences: " + str(len(link_diffs)) + " ---")
    for d in link_diffs:
        print("  FILE: " + d["file"] + " vs " + d["site"])
        if d["only_project"]:
            print("    Only in project (" + str(len(d["only_project"])) + "):")
            for l in d["only_project"][:30]:
                print("      + " + l)
        if d["only_site"]:
            print("    Only on site (" + str(len(d["only_site"])) + "):")
            for l in d["only_site"][:30]:
                print("      + " + l)
    if not link_diffs:
        print("  (none)")

    report_path = BASE_DIR / "link_check_report.json"
    report = {
        "broken_local_links": broken_links,
        "site_crawl_errors": site_data["errors"],
        "matched_files": matched,
        "unmatched_project_files": [{"file": f, "expected_key": k} for f, k in unmatched_project],
        "content_differences": content_diffs,
        "link_differences": link_diffs,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("Full report saved to: " + str(report_path))
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("Broken local links in project: " + str(len(broken_links)))
    print("Files matched (project->site): " + str(matched))
    print("Content differences: " + str(len(content_diffs)))
    print("Link differences: " + str(len(link_diffs)))
    print("Unmatched project files: " + str(len(unmatched_project)))

if __name__ == "__main__":
    main()