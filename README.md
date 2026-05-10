# 🃏 Anki AI Manager

A local web app that connects your Anki flashcard library to Claude AI for intelligent deck curation — finding duplicates, improving card quality, retagging, and adding new cards — all without leaving your machine.

---

## What It Does

Anki AI Manager acts as a bridge between your Anki decks and Claude. It reads your cards, generates a structured AI prompt, and then applies Claude's suggested changes directly back into Anki via AnkiConnect.

**Supported operations:**
- **Merge duplicates** — Combines redundant cards into one cleaner card
- **Edit cards** — Improves clarity, atomicity, and recall precision
- **Retag** — Applies hierarchical tags (e.g. `hematology::rbc`, `coagulation::factors`)
- **Delete** — Removes truly redundant cards after merging
- **Add cards** — Creates new Basic or Cloze cards suggested by Claude

---

## Requirements

| Requirement | Details |
|---|---|
| **Python** | 3.8 or higher |
| **Anki** | Desktop app (any recent version) |
| **AnkiConnect** | Anki add-on (see setup below) |
| **Claude.ai account** | Free or paid — used manually via copy-paste |

---

## Project Structure

```
anki-ai-manager/
├── app.py                          # Flask backend — API routes + AnkiConnect bridge
├── Launch Anki AI Manager.bat      # Windows one-click launcher
├── static/
│   └── index.html                  # Full frontend UI (single file)
└── README.md
```

> **Note:** The `static/` folder must exist and contain `index.html`. Create it if it doesn't exist yet.

---

## Setup

### 1. Install the AnkiConnect add-on

1. Open Anki
2. Go to **Tools → Add-ons → Get Add-ons…**
3. Enter code: **`2055492159`**
4. Restart Anki

AnkiConnect runs a local server at `http://127.0.0.1:8765` that this app communicates with. Anki must stay open while using the app.

### 2. Place the files

```
anki-ai-manager/
├── app.py
├── Launch Anki AI Manager.bat
└── static/
    └── index.html
```

Create the `static` folder if it doesn't exist, and move `index.html` into it.

### 3. Install Python dependencies

Flask is the only dependency:

```bash
pip install flask
```

Or if you prefer a virtual environment:

```bash
python -m venv venv

# macOS/Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate

pip install flask
```

### 4. Run the app

**Windows (recommended) — double-click the launcher:**

Just double-click `Launch Anki AI Manager.bat`. It will:
1. Change into the `anki-manager` folder automatically
2. Open `http://localhost:5050` in your browser
3. Start the Flask server in the same window

> **Important:** The `.bat` file expects your project folder to be named `anki-manager` and located in the same directory as the `.bat` file. If you named your folder differently, open the `.bat` file in a text editor and update this line:
> ```bat
> cd /d "%~dp0anki-manager"
> ```
> Change `anki-manager` to match your actual folder name.

The `.bat` file contents for reference:
```bat
@echo off
cd /d "%~dp0anki-manager"
start "" http://localhost:5050
python app.py
```

**macOS / Linux — run manually from terminal:**

```bash
python app.py
```

You should see:

```
🃏 Anki AI Manager running → http://localhost:5050
```

Open your browser and go to **http://localhost:5050**.

---

## How to Use

### Basic workflow

1. **Open Anki** (keep it open the whole time)
2. **Open the app** at http://localhost:5050
3. **Select a deck** from the sidebar — your cards will load
4. *(Optional)* **Add custom instructions** using the panel or presets
5. Click **✦ Generate Prompt** — this builds a structured prompt containing your cards
6. Click **⧉ Copy Prompt** and paste it into [claude.ai](https://claude.ai) in a new chat
7. Wait for Claude to respond, then **copy Claude's full reply**
8. Paste the reply into the **Step 2 text area** and click **✦ Load Changes**
9. Review the proposed changes — expand each card to inspect before/after
10. Uncheck anything you don't want applied
11. Click **✓ Apply selected changes to Anki**

### Batch mode

For large decks (80+ cards), use **⟳ Batch Mode**. The app will split your deck into batches of 80 cards and walk you through each one. A progress indicator shows which batch you're on and how much of the deck has been covered.

### Custom instructions

Click **✦ Custom Instructions** to expand the panel. You can type freeform instructions or click a preset chip:

| Preset | What it does |
|---|---|
| Only duplicates | Skips edits/retags, finds merges only |
| Only retag | Focuses entirely on hierarchical tagging |
| No deletions | Merges and edits only — nothing gets deleted |
| Improve clarity | Makes each card test exactly one fact |
| Coagulation focus | Prioritizes hemostasis/clotting factor cards |
| Hematology focus | Prioritizes blood cell and CBC cards |
| Transfusion focus | Prioritizes blood banking and transfusion cards |

Custom instructions override the default AI rules, so be specific.

---

## API Endpoints (for reference)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status` | Check if Anki + AnkiConnect are reachable |
| GET | `/api/decks` | List all Anki deck names |
| GET | `/api/cards?deck=<name>` | Fetch all notes in a deck |
| POST | `/api/export-prompt` | Generate the Claude prompt from card data |
| POST | `/api/parse-response` | Parse Claude's JSON reply |
| POST | `/api/apply` | Apply a list of changes to Anki |

---

## Troubleshooting

**"Cannot reach AnkiConnect"**
- Make sure Anki is open
- Confirm AnkiConnect is installed (Tools → Add-ons)
- Check that nothing is blocking port 8765 (firewall, VPN, etc.)
- Try visiting http://127.0.0.1:8765 in your browser — you should see a response

**"No Cloze note type found in Anki"**
- Anki needs at least one Cloze note type in your collection
- Go to **Tools → Manage Note Types** and verify a Cloze type exists
- If not, click **Add** and choose **Cloze**

**"Could not parse response"**
- Make sure you copied Claude's *entire* response, not just part of it
- Claude should return raw JSON — if it added markdown fences (```json) the app handles that automatically, but extra text before or after the JSON block can cause failures
- If Claude added an explanation before the JSON, delete everything before the first `{`

**Cards not updating after apply**
- Click on the deck name again in the sidebar to reload cards from Anki
- Some changes (especially tag updates) may take a moment to reflect in Anki's UI — try pressing F5 in Anki

**Port 5050 already in use**
- Change the port in the last line of `app.py`:
  ```python
  app.run(port=5051, debug=False)  # use any free port
  ```

---

## Notes & Limitations

- The app analyzes up to **80 cards per prompt** to stay within Claude's context limits. Use Batch Mode for larger decks.
- Card content is truncated to 400 characters per field in the prompt. Very long cards may be trimmed.
- Changes are applied **immediately and permanently** — there is no built-in undo. Use Anki's own **Edit → Undo** (Ctrl+Z) right after applying if you need to revert.
- The app only reads `Front`/`Back` fields (or the first two fields for custom note types). Complex multi-field note types may not display all fields in the preview.
- This app runs **entirely locally**. No card data is sent anywhere except to Claude.ai via your manual copy-paste.

---

## License

MIT — do whatever you want with it.
