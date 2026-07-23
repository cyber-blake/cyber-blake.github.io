import urllib.request, ssl, re
from html.parser import HTMLParser

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class LE(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and "href" in d:
            self.links.append(d["href"])

# Fetch the exhibition page from site
url = "https://tambov.ru.net/detstvo/?read=exhibition"
headers = {"User-Agent": "Mozilla/5.0"}
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
    html = resp.read().decode("utf-8", errors="replace")

p = LE()
p.feed(html)

print("Site exhibition page external links:")
for l in p.links:
    if l.startswith("http"):
        print("  " + l)

# Check for detstvo-bibl and detstvo-photos
print()
print("Looking for problematic links:")
for l in p.links:
    if "bibl" in l or "photos" in l:
        print("  FOUND: " + l)