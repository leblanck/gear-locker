# Gear Locker

A private inventory of your outdoor equipment that runs on your own machine.
Nothing to install — Python's standard library is all it needs.

## Run it

Put `gear.py` and `index.html` in the same folder, then:

```
python3 gear.py
```

Open **http://127.0.0.1:8000**. Stop it with Ctrl-C.

## Where your stuff is saved

The server creates a `data` folder beside the script:

```
data/gear.json      every item, in plain readable JSON
data/photos/*.jpg   one photo per item
```

`gear.json` is yours to open, read, or edit in any text editor. To back
everything up, copy the `data` folder. To move to another computer, copy the
folder across and start the server there.

The file is written atomically, so killing the server mid-save can't corrupt
it. If the file ever does become unreadable, the server moves it aside as
`gear.json.unreadable-<date>` rather than overwriting it, and tells you where
it went.

## Using it from your phone

Handy when you're cataloguing gear in the garage. Start it with:

```
python3 gear.py --host 0.0.0.0
```

Then browse to `http://<your-computer's-ip>:8000` from any device on the same
wifi. Leave off `--host` to keep it to your own machine.

Note there's no password on it. On your home network that's usually fine —
just don't forward the port to the internet.

## Running it in Docker

```
UID=$(id -u) GID=$(id -g) docker compose build
docker compose up -d
```

Same address: **http://127.0.0.1:8000**. Logs with `docker compose logs -f`,
stop with `docker compose down`.

Your data lands in `./data` next to the compose file, exactly as it does
without Docker — it's a plain bind mount, not a named volume, so `gear.json`
stays somewhere you can open and back up.

Two things worth knowing:

- **The UID/GID build args matter.** The container writes to a folder owned by
  you on the host. If the IDs don't line up you'll get a clear "Cannot write
  to /app/data" message on startup rather than a crash. Rebuild with the
  command above and it resolves.
- **Serving on a different port:** `GEAR_PORT=9000 docker compose up -d`.
  That changes the host side only; the container stays on 8000.

To reach it from your phone, no extra flags are needed — the container already
listens on all interfaces, so `http://<your-server-ip>:8000` works as soon as
the port is published.

## Options

```
--port 8000        listen on a different port
--host 127.0.0.1   0.0.0.0 opens it to your local network
--data ./data      keep gear.json and photos somewhere else
```

## In the app

- **Add item** — category, brand, name, description, optional weight, optional photo.
  Photos are shrunk to about 1000px in the browser before they're sent, so a
  phone snapshot lands as ~100 KB rather than 4 MB.
- **Search** matches name, brand, description, and category.
- **Category chips** only show categories you actually own something in.
- **Sort** by newest, name, brand, category, or weight.
- The bar under the header shows the mix of what you're currently looking at,
  and the total weight of it — it responds to your search and filter, so you
  can filter to a category and see what that part of your kit weighs.
- **Download backup** saves a single JSON file with the photos embedded.
  **Restore backup** reads one back in, adding to what's already there.
- **Export spreadsheet** gives you a CSV of whatever is currently on screen.

## Adding your own categories

Pick "+ New category…" in the category dropdown when adding an item. It gets a
three-letter code automatically and is shared across all your devices, since it
lives in `gear.json` too.