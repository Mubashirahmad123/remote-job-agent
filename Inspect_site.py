"""
inspect_site.py — Run this on YOUR machine to dump real HTML for inspection.

Usage:
    python inspect_site.py "https://justremote.co/remote-developer-jobs?exp=junior,mid" justremote_dump.html
    python inspect_site.py "https://goremote.io/remote-jobs/software-development/" goremote_dump.html
    python inspect_site.py "https://remotetech.io/remote-jobs/developer/" remotetech_dump.html

This saves the raw HTML to a file AND prints the first few candidate
job-container selectors it can find automatically, so we can see
what classes/structure the site is currently using.
"""

import sys
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

def inspect(url, output_file):
    print(f"Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Length: {len(resp.text)} chars")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(resp.text)
    print(f"Saved full HTML to: {output_file}")

    if resp.status_code != 200:
        print(f"\n⚠️ Non-200 response — site may be blocking this request.")
        print(f"First 300 chars of body:\n{resp.text[:300]}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try to find repeating elements that look like job cards
    candidates = {}
    for tag in soup.find_all(True):
        cls = tag.get("class")
        if cls:
            key = f"{tag.name}.{'.'.join(cls)}"
            candidates[key] = candidates.get(key, 0) + 1

    # Show classes that repeat 5-50 times (likely job listing containers)
    likely_job_containers = {k: v for k, v in candidates.items() if 5 <= v <= 50}
    sorted_candidates = sorted(likely_job_containers.items(), key=lambda x: -x[1])

    print(f"\n=== Likely job-card selectors (repeated 5-50 times) ===")
    for selector, count in sorted_candidates[:20]:
        print(f"  {count:3d}x  {selector}")

    # Also check for data-testid or article tags
    articles = soup.find_all("article")
    print(f"\n<article> tags found: {len(articles)}")

    data_testids = set()
    for tag in soup.find_all(attrs={"data-testid": True}):
        data_testids.add(tag.get("data-testid"))
    if data_testids:
        print(f"\ndata-testid values found: {list(data_testids)[:15]}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python inspect_site.py <url> <output_file>")
        sys.exit(1)
    inspect(sys.argv[1], sys.argv[2])