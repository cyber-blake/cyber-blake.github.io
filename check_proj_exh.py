from pathlib import Path
import re

proj = Path(r"D:\site_nginx\detstvo\read-exhibition.html").read_text(encoding="utf-8")

# Find all href with tambov
tambov_links = re.findall(r'href=\x22([^\x22]*tambov[^\x22]*)\x22', proj)
print("Project read-exhibition.html tambov links:")
for l in tambov_links:
    print("  " + l)

# Find protocol-relative links
proto_links = re.findall(r'href=\x22(//[^\x22]+)\x22', proj)
print()
print("Protocol-relative links:")
for l in proto_links:
    print("  " + l)

# Find the photos link
photos = re.findall(r'href=\x22([^\x22]*photo[^\x22]*)\x22', proj, re.I)
print()
print("Photo-related links:")
for l in photos:
    print("  " + l)