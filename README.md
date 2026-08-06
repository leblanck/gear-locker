# Gear Locker

A private inventory of outdoor equipment that runs on your own machine.
Categorise it, search it, see what it weighs, attach photos.

No database and no dependencies — the server is one Python file using nothing
but the standard library.

---

## Running it in Docker

**Create the data folder before the first start.** If you skip this, Docker
creates it for you as `root` and the container won't be able to write to it:

```
mkdir -p data
docker compose up -d --build
```

That's it. If your user isn't UID 1000, pass your IDs so the image builds with
a matching user:

```
mkdir -p data
UID=$(id -u) GID=$(id -g) docker compose up -d --build
```

Then open **http://localhost:8000** — or whichever host port you set in
`docker-compose.yml`.

### Updating after you edit a file

```
docker compose up -d --build
```

One command. No need for `docker compose down` first — `up` replaces the
container when the image changes, and Docker notices the edited files on its
own, so `--no-cache` isn't needed either. Your data is untouched.

### Changing the port

The compose file ships with this:

```yaml
    ports:
      - "${GEAR_PORT:-8000}:8000"
```

Either set the variable — `GEAR_PORT=8090 docker compose up -d` — or replace
the whole line with a fixed value so you don't have to remember it:

```yaml
    ports:
      - "8090:8000"
```

### If you see "Cannot write to /app/data"

This is a file ownership mismatch, and the message means the server caught it
cleanly rather than crashing. A bind mount completely replaces whatever was in
the image at that path, so what matters is who owns `data` **on your host**,
not anything the Dockerfile did. Check with `ls -ld data`. If it says `root`:

```
docker compose down
sudo chown -R $(id -u):$(id -g) data
docker compose up -d
```

To confirm the build args reached the image, `docker compose run --rm
gear-locker id` prints the user inside the container. It should match `id -u`.

---

## Running it without Docker

Put `gear.py` and `index.html` in the same folder:

```
python3 gear.py
```

Open **http://127.0.0.1:8000**, stop with Ctrl-C. Needs Python 3.8 or newer,
which Ubuntu already has.

Options:

```
--port 8000        listen on a different port
--host 127.0.0.1   0.0.0.0 also allows other devices on your network
--data ./data      keep the data folder somewhere else
```

---

## Where your stuff is saved

Everything lives in the `data` folder:

```
data/gear.json      every item, in plain readable JSON
data/photos/*.jpg   one photo per item, named by item id
data/brands/        cached brand logos
```

`gear.json` is yours to open, read, or edit in any text editor. To back
everything up, copy the folder. To move to another machine, copy it across and
start the server there.

The JSON is written atomically, so killing the server mid-save can't corrupt
it. If the file ever does become unreadable, the server moves it aside as
`gear.json.unreadable-<date>` and starts fresh rather than overwriting your
data — and tells you in the log where it went.

---

## In the app

- **Add item** — category, brand, item name, description, plus optional weight
  and photo. Photos are shrunk to about 1000px in the browser before being
  sent, so a phone snapshot lands as ~100 KB instead of 4 MB.
- **Search** matches name, brand, description, and category.
- **Category chips** only appear for categories you actually own something in.
- **Sort** by newest, name, brand, category, heaviest, or lightest.
- **Grid or list** view, toggled top right.
- The bar under the header shows the mix of whatever you're currently looking
  at and its total weight. It follows your search and filter, so you can narrow
  to one category and see what that part of your kit weighs.
- **Switch units** between grams/kg and oz/lb; the choice is remembered
  server-side, so it follows you between devices.
- **Download backup** saves one JSON file with the photos embedded inside it.
  **Restore backup** reads one back in, adding to what's already there.
- **Export spreadsheet** gives you a CSV of whatever is currently on screen.

### Adding your own categories

Pick "+ New category…" in the category dropdown. It gets a three-letter code
automatically and is stored in `gear.json`, so it shows up on every device.

### Brand logos

Type a brand and tab out of the field. The server works out the company's
website, fetches its icon once, and caches it in `data/brands/`. From then on
it's served from your own disk — no repeat calls, and it keeps working offline.

**Fetch brand logos** in the toolbar sweeps every brand already in your locker,
so you don't have to reopen each item.

The catch is that logo services take a *domain*, not a brand name, and outdoor
brands are full of traps — Black Diamond is `blackdiamondequipment.com`, MSR is
`msrgear.com`. There's a built-in table of 73 common brands; anything else
falls back to a plain `brandname.com` guess. When the guess is wrong, edit the
**Brand website** field and press Find. That correction is saved with the item,
so it only ever needs doing once.

Icons come from DuckDuckGo, falling back to Google — both keyless, so there's
no account to create and no API key to leak. They're favicons, so expect a
small mark beside the brand name rather than a full logo. Google returns a
generic globe rather than an error for domains it doesn't know, so if you get
one of those, clear the Brand website field to drop it. When nothing is found
the card just shows the brand as text.

This is the only part of the app that reaches the internet, and only when you
enter a brand or press the sweep button. Ignore those two and nothing ever
leaves your machine.