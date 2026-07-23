from pathlib import Path
import re

base = Path(r"D:\site_nginx\detstvo")

# Extract links from project index.html
proj = (base / "index.html").read_text(encoding="utf-8")
links = re.findall(r'href="[^"]*?([a-z][a-z0-9_\-]*\.html)"', proj)
print("Project index.html internal .html links:")
for l in sorted(set(links)):
    print("  " + l)

# Check the read-exhibition page for the broken external links
exh = (base / "read-exhibition.html").read_text(encoding="utf-8")
ext_links = re.findall(r'href="(https?://[^"]+)"', exh)
print()
print("read-exhibition.html external links:")
for l in ext_links:
    print("  " + l)

# Check read-about for sub-links
about = (base / "read-about.html").read_text(encoding="utf-8")
about_links = re.findall(r'href="[^"]*?([a-z][a-z0-9_\-]*\.html)"', about)
print()
print("read-about.html internal .html links:")
for l in sorted(set(about_links)):
    print("  " + l)