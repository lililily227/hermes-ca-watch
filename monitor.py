#!/usr/bin/env python3
"""Hermès Canada public link monitor for exactly three Neo Garden 23 SKUs.

No login, hidden APIs, cart actions or bot-protection circumvention.
Public links are candidates only; a visible page is NOT proof of stock.
"""
import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
BASE = "https://www.hermes.com"
ROBOTS = BASE + "/robots.txt"
BLOCK = (401, 403, 429)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path, fallback):
    return json.loads(path.read_text("utf-8")) if path.exists() else fallback


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def target_url(url, cfg, sitemap=False):
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "www.hermes.com":
        return None
    if not p.path.startswith("/ca/en/"):
        return None
    if sitemap:
        if not p.path.endswith((".xml", ".xml.gz")):
            return None
    elif not p.path.startswith("/ca/en/product/"):
        return None
    return urlunsplit(("https", p.netloc, p.path, "", ""))


def sku_for(url, cfg):
    path = urlsplit(url).path.upper()
    for sku in cfg["target_product_codes"]:
        if re.search(r"(?<![A-Z0-9])" + re.escape(sku) + r"(?![A-Z0-9])", path):
            return sku
    return None


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            value = dict(attrs).get("href")
            if value:
                self.links.append(value)


class RedirectGuard(HTTPRedirectHandler):
    def __init__(self, allowed):
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not self.allowed(newurl):
            raise PermissionError("Redirect not permitted by robots / site scope")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class Site:
    def __init__(self, cfg):
        self.cfg = cfg
        self.robots = RobotFileParser()
        self.loaded = False
        self.opener = build_opener(RedirectGuard(self.allowed))

    def allowed(self, url):
        if url == ROBOTS:
            return True
        p = urlsplit(url)
        return bool(self.loaded and p.scheme == "https" and p.netloc == "www.hermes.com"
                    and p.path.startswith("/ca/en/")
                    and self.robots.can_fetch(self.cfg["user_agent"], url))

    def get(self, url, *, maxbytes=12000000):
        if not self.allowed(url):
            raise PermissionError("Not permitted: " + url)
        request = Request(url, headers={"User-Agent": self.cfg["user_agent"],
                                        "Accept": "application/xml,text/xml,text/html,*/*"})
        try:
            with self.opener.open(request, timeout=self.cfg["http_timeout_seconds"]) as response:
                payload = response.read(maxbytes + 1)
                if len(payload) > maxbytes:
                    raise RuntimeError("Page size limit reached")
                return response.status, payload
        except HTTPError as exc:
            if exc.code in BLOCK:
                raise RuntimeError(f"HTTP {exc.code}: stop, do not bypass website protection") from exc
            return exc.code, b""
        except URLError as exc:
            print("[network] Unavailable:", type(exc).__name__)
            return 0, b""

    def setup(self):
        status, body = self.get(ROBOTS, maxbytes=300000)
        if status != 200:
            raise RuntimeError("Unable to obtain robots.txt; monitoring stopped")
        self.robots.parse(body.decode("utf-8", "replace").splitlines())
        self.loaded = True
        print("[robots] loaded; all requests checked against restrictions")


def sources(site, cfg):
    """Read only permitted public sitemap XML and category HTML."""
    sm = {}
    cat = {}
    queue = [cfg["sitemap_index"]]
    seen = set()
    cap = cfg.get("max_child_sitemaps_per_run", 4) + 1
    successful = 0
    while queue and len(seen) < cap:
        url = target_url(queue.pop(0), cfg, sitemap=True)
        if not url or url in seen:
            continue
        seen.add(url)
        if not site.allowed(url):
            print("[robots] blocked sitemap:", url)
            continue
        status, raw = site.get(url)
        if status != 200:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            print("[sitemap] invalid XML:", url)
            continue
        kind = root.tag.rsplit("}", 1)[-1]
        locs = [(element.text or "").strip() for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "loc"]
        if kind == "sitemapindex":
            choices = [u for u in locs if target_url(u, cfg, sitemap=True)]
            choices.sort(key=lambda x: (not any(t in x.lower()
                         for t in ("product", "catalog", "bag", "leather")), x))
            queue += choices
        elif kind == "urlset":
            successful += 1
            for loc in locs:
                normalized = target_url(html.unescape(loc), cfg)
                if normalized and (sku := sku_for(normalized, cfg)):
                    sm[normalized] = sku
    for url in cfg["category_pages"]:
        if not site.allowed(url):
            print("[robots] blocked category:", url)
            continue
        status, raw = site.get(url)
        if status != 200:
            continue
        successful += 1
        data = raw.decode("utf-8", "replace")
        parser = LinkParser()
        parser.feed(data)
        links = parser.links
        links += re.findall(r"(?:https://www\.hermes\.com)?/ca/en/product/[^\s\"'<>()\\]+", data)
        for link in links:
            normalized = target_url(urljoin(url, html.unescape(link)), cfg)
            if normalized and (sku := sku_for(normalized, cfg)):
                cat[normalized] = sku
    if successful == 0:
        raise RuntimeError("No permitted usable sitemap URL-set or category HTML; stopped")
    print(f"[sources] sitemap={len(sm)} category={len(cat)} sitemap-only={len(set(sm)-set(cat))}")
    return sm, cat


def product_status(site, url, sku):
    """missing / unavailable / accessible / unknown; never assert stock."""
    if not site.allowed(url):
        return "unknown"
    status, raw = site.get(url, maxbytes=400000)
    if status in (404, 410):
        return "missing"
    if status != 200:
        return "unknown"
    body = raw.decode("utf-8", "replace").lower()
    if any(marker in body for marker in ("captcha", "verify you are human", "access denied")):
        raise RuntimeError("Human verification page; monitoring stopped")
    if sku.lower() not in body and "neo garden 23" not in body:
        return "unknown"
    if any(marker in body for marker in ("unfortunately this product is no longer available",
                                         "out of stock", "available soon", "currently unavailable")):
        return "unavailable"
    return "accessible"


def bark(cfg, title, message, url):
    key = os.environ.get("BARK_KEY", "")
    if not key:
        print("[push] BARK_KEY not configured; no notification sent")
        return False
    server = cfg["bark_server"].rstrip("/")
    if not server.startswith("https://"):
        raise ValueError("Bark server must be HTTPS")
    payload = {"device_key": key, "title": title, "body": message,
               "url": url, "group": "Hermes-CA", "level": "timeSensitive"}
    request = Request(server + "/push", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener().open(request, timeout=12) as response:
            answer = json.loads(response.read(2048).decode("utf-8", "replace"))
            ok = response.status == 200 and answer.get("code") in (0, 200)
            print("[push] delivered" if ok else "[push] not confirmed")
            return ok
    except (HTTPError, URLError, ValueError):
        print("[push] request failed")
        return False


def run(cfg, state, audit=False):
    skus = cfg["target_product_codes"]
    if skus != ["H086418CKAC", "H086418CKAA", "H086418CKAF"]:
        raise ValueError("Unexpected SKUs: this monitor is restricted to three colors")
    if state.get("targets") != skus:
        state.clear()
        state["targets"] = skus
    site = Site(cfg)
    site.setup()
    sitemap, category = sources(site, cfg)
    if audit:
        for link in sorted(set(sitemap) - set(category)):
            print("[candidate, not confirmed stock]", link)
        print("[audit] No saved state, no push")
        return state
    first_run = not state.get("initialized", False)
    timestamp = now()
    known = state.setdefault("known", {})
    max_push = cfg.get("max_notifications_per_run", 3)
    sent = 0
    for url, sku in sorted({**sitemap, **category}.items()):
        record = known.get(url)
        if record is None:
            record = {"sku": sku, "first_seen": timestamp, "sitemap_first_seen": None,
                      "category_first_seen": None, "notified": first_run}
            known[url] = record
        if url in sitemap and record["sitemap_first_seen"] is None:
            record["sitemap_first_seen"] = timestamp
        if url in category and record["category_first_seen"] is None:
            record["category_first_seen"] = timestamp
            if record["sitemap_first_seen"]:
                minutes = int((datetime.fromisoformat(timestamp) -
                               datetime.fromisoformat(record["sitemap_first_seen"])).total_seconds() / 60)
                print(f"[timing] {sku}: sitemap {minutes} minutes before category (sampled)")
        if first_run or record["notified"] or sent >= max_push:
            continue
        if url in category:
            title = "Neo Garden 23：分类页发现目标颜色"
            message = f"{cfg['target_names'][sku]}（{sku}）分类页出现；库存请手动核实。"
        else:
            if product_status(site, url, sku) != "accessible":
                continue
            title = "Neo Garden 23：站点地图发现候选链接"
            message = f"{cfg['target_names'][sku]}（{sku}）链接公开可访问，但分类页未见；库存未确认。"
        if bark(cfg, title, message, url):
            record["notified"] = True
            sent += 1

    # Direct known URL checks have a lower rate than sitemap scans.
    page_states = state.setdefault("products", {})
    for sku, url in cfg["target_product_urls"].items():
        if sent >= max_push:
            break
        entry = page_states.setdefault(sku, {})
        previous_check = entry.get("last_checked")
        if previous_check:
            minutes = (datetime.fromisoformat(timestamp) -
                       datetime.fromisoformat(previous_check)).total_seconds() / 60
            if minutes < cfg.get("minimum_product_check_interval_minutes", 60):
                continue
        current = product_status(site, url, sku)
        previous = entry.get("status")
        entry["last_checked"] = timestamp
        if current == "unknown":
            continue
        entry["status"] = current
        print(f"[product] {sku}: {previous} -> {current}")
        if (not first_run and previous in ("missing", "unavailable") and current == "accessible"
                and bark(cfg, "Neo Garden 23：商品页恢复访问",
                         f"{cfg['target_names'][sku]}（{sku}）页面恢复公开访问，库存请手动核实。", url)):
            sent += 1
    state["initialized"] = True
    heartbeat = state.get("heartbeat")
    if not heartbeat or datetime.fromisoformat(timestamp) - datetime.fromisoformat(heartbeat) >= timedelta(days=14):
        state["heartbeat"] = timestamp
    print(f"[done] notified={sent}; watched={len(skus)}; links={len(known)}")
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--test-push", action="store_true")
    args = parser.parse_args()
    cfg = load(ROOT / "config.json", {})
    if args.test_push:
        ok = bark(cfg, "Neo Garden 23 监测测试", "手机推送已配置；这不是上新提醒。",
                  "https://www.hermes.com/ca/en/")
        sys.exit(0 if ok else 2)
    state_path = ROOT / "state.json"
    state = load(state_path, {})
    try:
        state = run(cfg, state, audit=args.audit)
        if not args.audit:
            save(state_path, state)
    except (PermissionError, RuntimeError, URLError, ValueError, OSError) as exc:
        print("[stopped]", str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
