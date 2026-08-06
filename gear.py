#!/usr/bin/env python3
"""
Gear Locker — a tiny inventory server that runs on your own machine.

Start it:
    python3 gear.py

Then open http://127.0.0.1:8000 in your browser.

Everything is saved as plain files in the folder beside this script:

    data/gear.json      your whole inventory, human-readable
    data/photos/*.jpg   one photo per item

Back it up by copying the `data` folder. Read or edit gear.json in any
text editor. Standard library only — nothing to install.

Options:
    --port 8000         port to listen on
    --host 127.0.0.1    use 0.0.0.0 to reach it from your phone on the same wifi
    --data ./data       where to keep gear.json and photos
"""

import argparse
import base64
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
MAX_BODY = 32 * 1024 * 1024          # generous ceiling for a photo upload
DATA_URL = re.compile(r"^data:image/[a-z0-9.+-]+;base64,(.+)$", re.I | re.S)
BLANK = {"version": 1, "metric": True, "customCats": [], "items": []}

DATA_DIR = os.path.join(HERE, "data")
JSON_PATH = os.path.join(DATA_DIR, "gear.json")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
BRAND_DIR = os.path.join(DATA_DIR, "brands")


# ----------------------------------------------------------------------
# Brand logos
#
# Every logo service takes a DOMAIN, not a brand name, and outdoor brands
# are full of traps (Black Diamond is blackdiamondequipment.com). So: look
# the brand up here first, fall back to a naive guess, and let the person
# correct it by hand in the app — that edit is saved with the item.
# ----------------------------------------------------------------------
BRAND_DOMAINS = {
    # packs
    "osprey": "osprey.com", "gregory": "gregorypacks.com", "deuter": "deuter.com",
    "granite gear": "granitegear.com", "mystery ranch": "mysteryranch.com",
    "hyperlite mountain gear": "hyperlitemountaingear.com", "zpacks": "zpacks.com",
    "gossamer gear": "gossamergear.com", "ula": "ula-equipment.com",
    "eagle creek": "eaglecreek.com", "cotopaxi": "cotopaxi.com",
    "topo designs": "topodesigns.com", "thule": "thule.com",
    # shelter
    "big agnes": "bigagnes.com", "nemo": "nemoequipment.com",
    "msr": "msrgear.com", "mountain safety research": "msrgear.com",
    "tarptent": "tarptent.com", "durston": "durstongear.com",
    "six moon designs": "sixmoondesigns.com",
    "mountain laurel designs": "mountainlaureldesigns.com",
    "kelty": "kelty.com", "marmot": "marmot.com", "exped": "exped.com",
    # sleep
    "therm a rest": "thermarest.com", "thermarest": "thermarest.com",
    "klymit": "klymit.com", "enlightened equipment": "enlightenedequipment.com",
    "western mountaineering": "westernmountaineering.com",
    "feathered friends": "featheredfriends.com", "sea to summit": "seatosummit.com",
    # cooking + water
    "jetboil": "jetboil.com", "snow peak": "snowpeak.com", "primus": "primus.eu",
    "trangia": "trangia.se", "gsi outdoors": "gsioutdoors.com",
    "nalgene": "nalgene.com", "hydro flask": "hydroflask.com",
    "camelbak": "camelbak.com", "katadyn": "katadyn.com", "sawyer": "sawyer.com",
    "platypus": "platy.com", "yeti": "yeti.com", "stanley": "stanley1913.com",
    # clothing + footwear
    "patagonia": "patagonia.com", "the north face": "thenorthface.com",
    "arcteryx": "arcteryx.com", "rab": "rab.equipment",
    "outdoor research": "outdoorresearch.com",
    "mountain hardwear": "mountainhardwear.com", "fjallraven": "fjallraven.com",
    "darn tough": "darntough.com", "smartwool": "smartwool.com",
    "icebreaker": "icebreaker.com", "salomon": "salomon.com",
    "merrell": "merrell.com", "la sportiva": "lasportiva.com",
    "altra": "altrarunning.com", "hoka": "hoka.com", "vasque": "vasque.com",
    "keen": "keenfootwear.com",
    # hardware, light, electronics
    "black diamond": "blackdiamondequipment.com", "petzl": "petzl.com",
    "nitecore": "nitecore.com", "ledlenser": "ledlenser.com",
    "garmin": "garmin.com", "suunto": "suunto.com", "goal zero": "goalzero.com",
    "anker": "anker.com", "leatherman": "leatherman.com",
    "victorinox": "victorinox.com", "coleman": "coleman.com", "rei": "rei.com",
}

# Keyless, so there's no account to make and no API key to leak.
ICON_SOURCES = [
    "https://icons.duckduckgo.com/ip3/%s.ico",
    "https://www.google.com/s2/favicons?domain=%s&sz=128",
]


def brand_key(name):
    """'Therm-a-Rest' and 'Fjällräven' both need to match the table."""
    flat = unicodedata.normalize("NFKD", str(name or ""))
    flat = flat.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", flat.lower()).strip()


def guess_domain(name):
    key = brand_key(name)
    if not key:
        return ""
    if key in BRAND_DOMAINS:
        return BRAND_DOMAINS[key]
    return key.replace(" ", "") + ".com"


def tidy_domain(value):
    """Accept 'https://osprey.com/packs' and keep just 'osprey.com'."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://", "", text).split("/")[0].split("?")[0]
    return text if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", text) else ""


def domain_slug(domain):
    """osprey.com -> osprey-com   (a safe file name)"""
    return re.sub(r"[^a-z0-9.-]", "", str(domain or "").lower())[:60].replace(".", "-")


def sniff_type(blob):
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if blob.startswith(b"GIF8"):
        return "image/gif"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return ""


def icon_file(slug):
    return os.path.join(BRAND_DIR, slug + ".img")


def miss_file(slug):
    return os.path.join(BRAND_DIR, slug + ".miss")


def fetch_icon(domain, timeout=6):
    """Try each source; accept only something that really is an image."""
    quoted = urllib.parse.quote(domain, safe="")
    for template in ICON_SOURCES:
        try:
            req = urllib.request.Request(
                template % quoted, headers={"User-Agent": "GearLocker/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as res:
                if res.status != 200:
                    continue
                blob = res.read(400_000)
        except Exception:                             # noqa: BLE001 — any failure, try the next
            continue
        if len(blob) >= 100 and sniff_type(blob):
            return blob
    return None


def attach_domain(name, domain):
    """Give every item of this brand the domain, unless it already has one."""
    key = brand_key(name)
    with LOCK:
        cat = load()
        if key:
            touched = False
            for it in cat["items"]:
                if not it.get("domain") and brand_key(it.get("brand")) == key:
                    it["domain"] = domain
                    touched = True
            if touched:
                persist(cat)
        return cat


def op_brand(body):
    """Resolve a brand to a domain, then cache its icon on disk."""
    name = str(body.get("brand") or "").strip()
    domain = tidy_domain(body.get("domain")) or tidy_domain(guess_domain(name))
    if not domain:
        return {"domain": "", "slug": "", "icon": False, "reason": "no domain"}

    slug = domain_slug(domain)
    result = {"domain": domain, "slug": slug}

    def finish(res):
        if body.get("applyToItems"):
            res["state"] = attach_domain(name, domain)
        return res

    if os.path.exists(icon_file(slug)):
        return finish(dict(result, icon=True, cached=True))
    # A bulk sweep skips known misses; an explicit lookup always retries.
    if body.get("skipMisses") and os.path.exists(miss_file(slug)):
        return dict(result, icon=False, reason="no icon found before")

    os.makedirs(BRAND_DIR, exist_ok=True)
    blob = fetch_icon(domain)
    if not blob:
        try:
            open(miss_file(slug), "w").close()
        except OSError:
            pass
        return dict(result, icon=False, reason="nothing found for " + domain)

    tmp = icon_file(slug) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, icon_file(slug))
    try:
        os.remove(miss_file(slug))
    except OSError:
        pass
    return finish(dict(result, icon=True))


# ----------------------------------------------------------------------
# Reading and writing the JSON file
# ----------------------------------------------------------------------
def blank():
    return {"version": 1, "metric": True, "customCats": [], "items": []}


def load():
    """Read gear.json. Never destroy a file we can't parse."""
    if not os.path.exists(JSON_PATH):
        return blank()
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("top level is not an object")
    except (OSError, ValueError) as e:
        keep = JSON_PATH + ".unreadable-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            os.replace(JSON_PATH, keep)     # move it aside so this happens once
            note = "the old file was moved to " + os.path.basename(keep)
        except OSError:
            note = "it could not be moved aside"
        print("\n  !! Could not read %s (%s)." % (JSON_PATH, e))
        print("  !! Starting with an empty locker; %s\n" % note)
        return blank()

    out = blank()
    out["metric"] = bool(raw.get("metric", True))
    if isinstance(raw.get("customCats"), list):
        out["customCats"] = [c for c in raw["customCats"]
                             if isinstance(c, list) and len(c) == 2]
    if isinstance(raw.get("items"), list):
        out["items"] = [clean(i) for i in raw["items"]
                        if isinstance(i, dict) and str(i.get("name", "")).strip()]
    return out


def persist(cat):
    """Write the file atomically, so a crash mid-save can't corrupt it."""
    os.makedirs(PHOTO_DIR, exist_ok=True)
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cat, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JSON_PATH)


# ----------------------------------------------------------------------
# Items and photos
# ----------------------------------------------------------------------
def new_id():
    return "%s%s" % (int(time.time() * 1000), os.urandom(2).hex())


def safe_id(value):
    """Strip anything that could escape the photos folder."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:48]


def photo_path(item_id):
    return os.path.join(PHOTO_DIR, safe_id(item_id) + ".jpg")


def clean(raw, prev=None):
    """Coerce whatever the browser sent into a well-formed record."""
    now = int(time.time() * 1000)

    def text(value, limit):
        return str("" if value is None else value).strip()[:limit]

    try:
        grams = max(0.0, float(raw.get("g") or 0))
    except (TypeError, ValueError):
        grams = 0.0

    item_id = safe_id(raw.get("id")) or new_id()
    if prev:
        added = int(prev.get("added") or now)
    else:
        try:
            added = int(raw.get("added") or now)
        except (TypeError, ValueError):
            added = now

    return {
        "id": item_id,
        "added": added,
        "updated": int(raw.get("updated") or now) if prev is None else now,
        "cat": text(raw.get("cat"), 12) or "MSC",
        "name": text(raw.get("name"), 90),
        "brand": text(raw.get("brand"), 60),
        "desc": text(raw.get("desc"), 1200),
        "g": grams,
        "photo": bool(raw.get("photo")),
        "domain": tidy_domain(raw.get("domain")),
    }


def write_photo(item_id, data_url):
    """Decode a browser data URL and drop it on disk as a .jpg."""
    match = DATA_URL.match(data_url or "")
    if not match:
        return False
    try:
        blob = base64.b64decode(match.group(1))
    except (ValueError, TypeError):
        return False
    if not blob:
        return False
    os.makedirs(PHOTO_DIR, exist_ok=True)
    target = photo_path(item_id)
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, target)
    return True


def drop_photo(item_id):
    try:
        os.remove(photo_path(item_id))
    except OSError:
        pass


def read_photo_data_url(item_id):
    try:
        with open(photo_path(item_id), "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return ""


# ----------------------------------------------------------------------
# Operations — each returns the full catalog so the browser stays in sync
# ----------------------------------------------------------------------
def op_save(body):
    incoming = body.get("item")
    if not isinstance(incoming, dict):
        raise ValueError("no item")

    with LOCK:
        cat = load()
        at = next((n for n, it in enumerate(cat["items"])
                   if it["id"] == safe_id(incoming.get("id"))), -1)
        prev = cat["items"][at] if at > -1 else None
        item = clean(incoming, prev)
        if not item["name"]:
            raise ValueError("an item needs a name")

        photo_data = body.get("photoData")
        if photo_data:
            item["photo"] = write_photo(item["id"], photo_data)
        elif not item["photo"]:
            drop_photo(item["id"])
        else:
            item["photo"] = os.path.exists(photo_path(item["id"]))

        if at > -1:
            cat["items"][at] = item
        else:
            cat["items"].append(item)
        persist(cat)
        return cat


def op_delete(body):
    target = safe_id(body.get("id"))
    with LOCK:
        cat = load()
        cat["items"] = [i for i in cat["items"] if i["id"] != target]
        drop_photo(target)
        persist(cat)
        return cat


def op_meta(body):
    with LOCK:
        cat = load()
        if "metric" in body:
            cat["metric"] = bool(body["metric"])
        if isinstance(body.get("customCats"), list):
            cat["customCats"] = [c for c in body["customCats"]
                                 if isinstance(c, list) and len(c) == 2]
        persist(cat)
        return cat


def op_import(body):
    incoming = body.get("items")
    if not isinstance(incoming, list):
        raise ValueError("that file has no items in it")

    with LOCK:
        cat = load()
        if isinstance(body.get("customCats"), list):
            have = {c[0] for c in cat["customCats"]}
            for c in body["customCats"]:
                if isinstance(c, list) and len(c) == 2 and c[0] not in have:
                    cat["customCats"].append(c)
                    have.add(c[0])

        used = {i["id"] for i in cat["items"]}
        added = 0
        for raw in incoming:
            if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
                continue
            item = clean(raw)
            if item["id"] in used:
                item["id"] = new_id()
            used.add(item["id"])
            photo = raw.get("photo")
            item["photo"] = write_photo(item["id"], photo) if isinstance(photo, str) else False
            cat["items"].append(item)
            added += 1
        persist(cat)
        cat = dict(cat, imported=added)
        return cat


def build_export():
    with LOCK:
        cat = load()
    items = []
    for it in cat["items"]:
        row = dict(it)
        row["photo"] = read_photo_data_url(it["id"]) if it["photo"] else ""
        items.append(row)
    return {
        "app": "gear-locker",
        "version": 1,
        "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metric": cat["metric"],
        "customCats": cat["customCats"],
        "items": items,
    }


OPS = {"save": op_save, "delete": op_delete, "meta": op_meta,
       "import": op_import, "brand": op_brand}


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------
class Locker(BaseHTTPRequestHandler):
    server_version = "GearLocker/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------
    def reply(self, status, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                      # browser navigated away mid-response

    def reply_json(self, data, status=200):
        self.reply(status, json.dumps(data), "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def reply_file(self, path, ctype, headers=None):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.reply(404, "Not found")
        return self.reply(200, body, ctype, headers)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if length <= 0:
            raise ValueError("empty request")
        if length > MAX_BODY:
            raise ValueError("that upload is too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt, *args):
        pass                          # keep the terminal quiet

    def log_error(self, fmt, *args):
        sys.stderr.write("  http: %s\n" % (fmt % args))

    # -- routes --------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            page = os.path.join(HERE, "index.html")
            if not os.path.exists(page):
                return self.reply(500, "index.html is missing from " + HERE)
            return self.reply_file(page, "text/html; charset=utf-8",
                                   {"Cache-Control": "no-cache"})

        if path == "/api/state":
            with LOCK:
                cat = load()
            cat["dataFile"] = os.path.relpath(JSON_PATH, HERE)
            return self.reply_json(cat)

        if path == "/api/export":
            name = "gear-locker-%s.json" % time.strftime("%Y-%m-%d")
            return self.reply(
                200, json.dumps(build_export(), indent=2, ensure_ascii=False),
                "application/json; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="%s"' % name})

        if path.startswith("/photos/"):
            name = path[len("/photos/"):]
            if not name.endswith(".jpg"):
                return self.reply(404, "Not found")
            return self.reply_file(
                os.path.join(PHOTO_DIR, safe_id(name[:-4]) + ".jpg"), "image/jpeg",
                {"Cache-Control": "public, max-age=31536000, immutable"})

        if path.startswith("/brands/"):
            slug = re.sub(r"[^a-z0-9-]", "", path[len("/brands/"):].lower())[:60]
            try:
                with open(icon_file(slug), "rb") as f:
                    blob = f.read()
            except OSError:
                return self.reply(404, "No icon")
            return self.reply(200, blob, sniff_type(blob) or "image/png",
                              {"Cache-Control": "public, max-age=604800"})

        if path == "/favicon.ico":
            return self.reply(204)

        return self.reply(404, "Not found")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self.reply(404, "Not found")
        op = OPS.get(path[len("/api/"):])
        if not op:
            return self.reply_json({"error": "unknown request"}, 404)
        try:
            result = op(self.read_body())
        except ValueError as e:
            return self.reply_json({"error": str(e)}, 400)
        except Exception as e:                        # noqa: BLE001
            sys.stderr.write("  error: %r\n" % (e,))
            return self.reply_json({"error": "the server could not save that"}, 500)
        return self.reply_json(result)


# ----------------------------------------------------------------------
def main():
    global DATA_DIR, JSON_PATH, PHOTO_DIR, BRAND_DIR

    ap = argparse.ArgumentParser(description="Run your Gear Locker.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 to allow other devices on your network")
    ap.add_argument("--data", default=DATA_DIR, help="folder for gear.json and photos")
    args = ap.parse_args()

    DATA_DIR = os.path.abspath(args.data)
    JSON_PATH = os.path.join(DATA_DIR, "gear.json")
    PHOTO_DIR = os.path.join(DATA_DIR, "photos")
    BRAND_DIR = os.path.join(DATA_DIR, "brands")

    try:
        os.makedirs(PHOTO_DIR, exist_ok=True)
        os.makedirs(BRAND_DIR, exist_ok=True)
        probe = os.path.join(DATA_DIR, ".writable")
        with open(probe, "w"):
            pass
        os.remove(probe)
    except OSError as e:
        print("\n  Cannot write to %s" % DATA_DIR)
        print("  %s\n" % e)
        print("  In Docker this usually means the mounted folder belongs to a")
        print("  different user than the one inside the container. Rebuild with:")
        print("      UID=$(id -u) GID=$(id -g) docker compose build\n")
        sys.exit(1)

    cat = load()
    if not os.path.exists(JSON_PATH):
        persist(cat)

    try:
        server = ThreadingHTTPServer((args.host, args.port), Locker)
    except OSError as e:
        print("\n  Could not start on %s:%s — %s" % (args.host, args.port, e))
        print("  Something else may be using that port. Try: python3 gear.py --port 8001\n")
        sys.exit(1)

    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print("\n  Gear Locker is running.")
    print("  Open       http://%s:%s" % (shown, args.port))
    print("  Saving to  %s" % JSON_PATH)
    print("  In locker  %d item%s" % (len(cat["items"]), "" if len(cat["items"]) == 1 else "s"))
    if args.host == "0.0.0.0":
        print("  Reachable from other devices on this network.")
    print("  Stop with  Ctrl-C\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("  Stopped. Your locker is saved in %s\n" % JSON_PATH)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()