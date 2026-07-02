import os
import re
from pathlib import Path

MIRROR_DIR = Path(__file__).parent.resolve()

def fix_html(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # Fix background-image: sph_templates/glozzom2/img/title1.jpg
    content = re.sub(
        r"url\(['\"]?sph_templates/glozzom2/img/(title1\.jpg)['\"]?\)",
        r"url('./assets/sph_templates_glozzom2_img_\1')",
        content
    )

    # Fix background-image: /detstvo/?fimg=X.Y.Z (thumbnail) -> full res
    content = re.sub(
        r"url\(['\"]?(/detstvo/)?\?fimg=(\d+\.\d+)\.\d+['\"]?\)",
        r"url('./img/fimg-\1\2.jpg')",
        content
    )
    # Remove the extraneous /detstvo/ that might have been captured
    content = content.replace("./img/fimg-/detstvo/", "./img/fimg-")

    # Fix data-src and src with fqimg -> full-res fimg
    content = re.sub(
        r'(src|data-src)\s*=\s*["\']([^"\']*)fqimg=(\d+\.\d+)\.\d+([^"\']*)["\']',
        lambda m: f'{m.group(1)}="./img/fimg-{m.group(3)}.jpg"',
        content
    )

    # Fix any remaining /detstvo/?fimg=X.Y.Z (with size suffix in src)
    content = re.sub(
        r'(src|data-src)\s*=\s*["\']([^"\']*)fimg=(\d+\.\d+)\.\d+([^"\']*)["\']',
        lambda m: f'{m.group(1)}="./img/fimg-{m.group(3)}.jpg"',
        content
    )

    # Fix any remaining /detstvo/?fimg=X.Y (full res) in src
    content = re.sub(
        r'(src|data-src)\s*=\s*["\']([^"\']*)/detstvo/\?fimg=(\d+(?:\.\d+)*)["\']',
        lambda m: f'{m.group(1)}="./img/fimg-{m.group(3)}.jpg"',
        content
    )

    # Fix remaining /detstvo/? (thumbs in regular img src)
    content = re.sub(
        r'(src|data-src)\s*=\s*["\']([^"\']*)/detstvo/\?fqimg=(\d+(?:\.\d+)*)\.\d+["\']',
        lambda m: f'{m.group(1)}="./img/fimg-{m.group(3)}.jpg"',
        content
    )

    # Fix href="/detstvo/?..." -> ./<filename>.html
    def replace_href(m):
        full = m.group(0)
        url_part = m.group(1)  # everything after /detstvo/?
        if not url_part:
            return 'href="./index.html"'
        # Convert query params to filename
        fname = url_part.replace("&", "_").replace("=", "-")
        # Remove any existing .html
        fname = re.sub(r'\.html$', '', fname)
        return f'href="./{fname}.html"'

    content = re.sub(
        r'href\s*=\s*["\']/detstvo/\?([^"\']*)["\']',
        replace_href,
        content
    )

    # Fix href="/detstvo" or "/detstvo/"
    content = re.sub(
        r'href\s*=\s*["\']/detstvo/?["\']',
        'href="./index.html"',
        content
    )

    # Clean up any double ./
    content = content.replace('href="././', 'href="./')

    # Fix intradomain absolute links to social networks etc - keep them as-is

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False

def main():
    html_files = sorted(MIRROR_DIR.glob("*.html"))
    fixed = 0
    for filepath in html_files:
        if fix_html(filepath):
            print(f"  [FIXED] {filepath.name}")
            fixed += 1
        else:
            print(f"  [OK] {filepath.name}")
    print(f"\nDone! {fixed}/{len(html_files)} files modified.")

if __name__ == "__main__":
    main()
