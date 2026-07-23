#!/usr/bin/env python3
"""Fix local mirror HTML files based on audit_report.json findings."""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

MIRROR_DIR = Path(__file__).parent.resolve()
REPORT_PATH = MIRROR_DIR / "audit_report.json"


def load_report():
    with open(REPORT_PATH, encoding="utf-8") as f:
        return json.load(f)


def parse_list_from_diffs(diffs, diff_type):
    for d in diffs:
        if d["type"] == diff_type:
            m = re.search(r'\(\d+\):\s*(.*)', d["message"])
            if m:
                return [l.strip() for l in m.group(1).rstrip('.').split(', ')]
    return []


def parse_fimg_from_diffs(diffs, diff_type):
    result = []
    for d in diffs:
        if d["type"] == diff_type:
            for part in d["message"].split(', '):
                fm = re.search(r'fimg=(\d+\.\d+)', part.strip())
                if fm:
                    result.append(fm.group(1))
    return result


def main():
    print("=" * 70)
    print("  FIX MIRROR: Applying fixes based on audit_report.json")
    print("=" * 70)

    report = load_report()
    changed_files = set()

    for page in report["pages"]:
        if page["status"] != "HAS_DIFFS":
            continue
        local_file = page["local_file"]
        if local_file == "N/A":
            continue

        filepath = MIRROR_DIR / local_file
        if not filepath.exists():
            print(f"  SKIP: {local_file} not found")
            continue

        diffs = page["diffs"]
        html = filepath.read_text(encoding="utf-8")
        original_html = html
        fixes_applied = []

        missing_links = parse_list_from_diffs(diffs, "missing_links")
        extra_links = parse_list_from_diffs(diffs, "extra_links")
        extra_fimgs = parse_fimg_from_diffs(diffs, "extra_images")
        missing_fimgs = parse_fimg_from_diffs(diffs, "missing_images")

        has_pagination = any('_page=' in l for l in extra_links)

        gallery_anchors_missing = sorted(set(
            int(m.group(1))
            for l in missing_links
            for m in [re.search(r'#photo_(\d+)', l)]
            if m
        ))
        gallery_anchors_extra = sorted(set(
            int(m.group(1))
            for l in extra_links
            for m in [re.search(r'#photo_(\d+)', l)]
            if m
        ))

        dload_links_map = {}
        for link in missing_links:
            m = re.search(r'dload=(\d+\.\d+)', link)
            if m:
                dload_links_map[m.group(1)] = link

        has_broken = any(d["type"] in ("text_diff", "missing_structure", "extra_structure", "heading_count")
                         for d in diffs)
        has_fixable = has_pagination or extra_fimgs or missing_fimgs or gallery_anchors_missing or dload_links_map
        if has_broken and not has_fixable:
            print(f"  SKIP (broken URL page): {local_file}")
            continue

        # FIX: Image fimg values - only replace EXTRA with MISSING
        if extra_fimgs and missing_fimgs:
            extra_set = set(extra_fimgs)
            missing_set = set(missing_fimgs)
            fimg_map = {}
            sorted_extra = sorted(extra_set)
            sorted_missing = sorted(missing_set)
            for i in range(min(len(sorted_extra), len(sorted_missing))):
                old_val = sorted_extra[i]
                new_val = sorted_missing[i]
                if old_val != new_val:
                    fimg_map[old_val] = new_val

            for old_val, new_val in fimg_map.items():
                html = re.sub(rf'fimg-{re.escape(old_val)}\.', f'fimg-{new_val}.', html)
                html = re.sub(rf'fimg={re.escape(old_val)}\b', f'fimg={new_val}', html)
                fixes_applied.append(f"fimg {old_val}->{new_val}")

        # FIX: Gallery anchor links
        if gallery_anchors_missing and gallery_anchors_extra:
            anchor_map = {}
            for i in range(min(len(gallery_anchors_extra), len(gallery_anchors_missing))):
                old_a = gallery_anchors_extra[i]
                new_a = gallery_anchors_missing[i]
                if old_a != new_a:
                    anchor_map[old_a] = new_a

            if anchor_map:
                soup = BeautifulSoup(html, 'html.parser')
                changed_anchors = False
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    for old_a, new_a in anchor_map.items():
                        old_pattern = f'#photo_{old_a}'
                        new_pattern = f'#photo_{new_a}'
                        if old_pattern in href:
                            a['href'] = href.replace(old_pattern, new_pattern)
                            changed_anchors = True
                if changed_anchors:
                    html = str(soup)
                    fixes_applied.append(f"gallery anchors: {anchor_map}")

        # FIX: Download links
        if dload_links_map:
            soup = BeautifulSoup(html, 'html.parser')
            changed_dload = False
            for a in soup.find_all('a', href=True):
                m = re.match(r'\./dload-(\d+\.\d+)\.html', a['href'])
                if m:
                    dload_id = m.group(1)
                    if dload_id in dload_links_map:
                        a['href'] = dload_links_map[dload_id]
                        changed_dload = True
            if changed_dload:
                html = str(soup)
                fixes_applied.append(f"dload: {list(dload_links_map.keys())}")

        if html != original_html:
            filepath.write_text(html, encoding="utf-8")
            changed_files.add(local_file)
            print(f"  FIXED: {local_file}")
            for fix in fixes_applied:
                print(f"    - {fix}")
        else:
            print(f"  OK (no changes): {local_file}")

    print(f"\n{'='*70}")
    print(f"  Files changed: {len(changed_files)}")
    for f in sorted(changed_files):
        print(f"    - {f}")
    print(f"{'='*70}")
    return len(changed_files)


if __name__ == "__main__":
    changed = main()
    sys.exit(0)
