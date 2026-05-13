# 🃏 Anki AI Manager

A local web app that connects your Anki deck to Claude AI for intelligent flashcard curation — merging duplicates, improving card quality, retagging, and adding new cards.

![Anki AI Manager UI](https://img.shields.io/badge/version-1.0-gold) ![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![Flask](https://img.shields.io/badge/flask-2.x-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

Anki AI Manager acts as a bridge between your Anki collection and Claude.ai. It exports your cards as a structured prompt, you paste that prompt into Claude, then paste Claude's JSON response back into the app — which parses it and applies the suggested changes directly to Anki via AnkiConnect.

**Supported change types:**

| Type | Description |
|---|---|
| **Merge duplicate** | Identifies near-duplicate cards, merges them into one, deletes the redundant copy |
| **Edit card** | Rewrites front/back for better clarity, atomicity, or accuracy |
| **Retag** | Applies hierarchical tags (e.g. `hematology::rbc`) |
| **Delete** | Removes genuinely redundant cards (typically post-merge) |
| **Add card** | Creates new cards (Basic or Cloze) to fill gaps in the deck |

**Additional features:**
- **Batch mode** — splits large decks (100+ cards) into sequential batches for multi-turn Claude conversations
- **Custom instructions** — override default AI behavior per session (e.g. "focus only on duplicates", "no deletions", "use Filipino medical terminology")
- **Preset chips** — one-click common instruction templates
- **MathJax safety check** — detects when AI rewrites may strip `\(...\)` or `\[...\]` math notation and flags those changes with a warning banner before you apply them
- **Selective apply** — review every proposed change, check/uncheck individual items, then apply only what you approve
- **Cloze ↔ Basic conversion** — automatically handles model-type mismatches when AI converts a card type

---

## Requirements

- **Python 3.8+**
- **Anki** (desktop) with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed
- A **Claude.ai** account (free tier works; Pro recommended for large decks)
- The following Python packages:
  ```
  flask
  ```

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/anki-ai-manager.git
cd anki-ai-manager
```

### 2. Install dependencies

```bash
pip install flask
```

### 3. Install AnkiConnect in Anki

1. Open Anki
2. Go to **Tools → Add-ons → Get Add-ons**
3. Enter code: `2055492159`
4. Restart Anki

### 4. Set up the folder structure

The app expects this layout:

```
anki-ai-manager/
├── app.py
└── static/
    └── index.html
```

Move `index.html` into a `static/` subfolder inside the project directory.

---

## Running the app

### Option A — Windows (double-click launcher)

Place `Launch Anki AI Manager.bat` one level above the `anki-ai-manager/` folder, then double-click it. It will open your browser and start the server.

```
your-folder/
├── Launch Anki AI Manager.bat   ← double-click this
└── anki-ai-manager/
    ├── app.py
    └── static/
        └── index.html
```

### Option B — Manual (any OS)

```bash
# Make sure Anki is open first
cd anki-ai-manager
python app.py
```

Then open [http://localhost:5050](http://localhost:5050) in your browser.

---

## Usage

### Basic flow (small deck, ≤ 100 cards)

1. Open Anki (must be running in the background)
2. Launch the app and navigate to [http://localhost:5050](http://localhost:5050)
3. The green dot in the header confirms AnkiConnect is reachable
4. Select a deck from the sidebar
5. *(Optional)* Expand **Custom Instructions** and add specific guidance or select a preset
6. Click **✦ Generate Prompt**
7. Click **⧉ Copy Prompt** and paste it into a new [Claude.ai](https://claude.ai) conversation
8. Wait for Claude's JSON response
9. Copy Claude's full response and paste it into the **Step 2** textarea
10. Click **✦ Load Changes**
11. Review the proposed changes — uncheck anything you don't want
12. Click **✓ Apply selected changes to Anki**

### Batch mode (large deck, 100+ cards)

For decks with more than 100 cards, use **⟳ Batch Mode** instead of Generate Prompt:

1. Click **⟳ Batch Mode** — the app splits your deck into batches of 100
2. For each **hold batch**: copy the prompt → paste into Claude → wait for the acknowledgement reply → click **Next Batch**
3. For the **final batch**: copy the prompt → paste into Claude → Claude now analyzes the full deck and returns JSON
4. Paste the final JSON response → Load Changes → Apply

> ⚠️ All batches must be sent in **the same Claude conversation** so Claude has full context when producing the analysis.

---

## Custom instructions

The custom instructions field lets you override the default AI behavior. Examples:

- `Focus only on finding and merging duplicate cards. Do not suggest edits or retags.`
- `Do not delete any cards. Only merge, edit, or retag.`
- `Use Filipino medical terminology where applicable.`
- `This deck has already been partially curated. Focus on remaining issues only.`

Custom instructions take **strict priority** over the default rules in the prompt.

---

## MathJax warning system

If your deck contains cards with LaTeX/MathJax notation (`\(...\)` inline, `\[...\]` block), the app automatically:

1. Detects math in original cards
2. Checks whether Claude's rewritten version preserved it
3. Flags any change that appears to have stripped math with an **⚠️ warning banner** and an orange card border

Changes with math warnings are still selectable, but you should expand and inspect them carefully before applying. When in doubt, uncheck the edit and use a **retag only** instead.

---

## Project structure

```
anki-ai-manager/
├── app.py              # Flask backend — AnkiConnect bridge, prompt builder, parser
└── static/
    └── index.html      # Single-page frontend (vanilla JS, no build step)

Launch Anki AI Manager.bat   # Windows one-click launcher (optional)
```

### Key API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Check AnkiConnect connection |
| `/api/decks` | GET | List all Anki decks |
| `/api/cards` | GET | Fetch cards for a deck |
| `/api/export-prompt` | POST | Generate the Claude prompt |
| `/api/parse-response` | POST | Parse Claude's JSON response |
| `/api/apply` | POST | Apply approved changes via AnkiConnect |

---

## How the AI analysis works

The app builds a structured prompt containing:
- Up to 100 cards (front, back, tags, ID) per batch
- Your custom instructions (if any)
- A strict JSON schema Claude must follow
- Rules for MathJax preservation, cloze syntax, tag hierarchy, and card atomicity

Claude returns a JSON object with a summary, stats, and a `changes` array. The backend parses this, runs the MathJax safety check, and renders the results in the UI for review before anything touches your deck.

---

## Troubleshooting

**Red dot / "Anki not found"**
- Make sure Anki is open before launching the app
- Confirm AnkiConnect is installed (Tools → Add-ons)
- AnkiConnect runs on port 8765 by default — check nothing else is using it

**"Could not parse response" error**
- Make sure you copied Claude's *entire* response, including the opening `{`
- The app accepts raw JSON or JSON wrapped in ` ```json ``` ` fences

**Changes applied but cards look wrong**
- Check the Anki undo history (Edit → Undo) immediately after applying
- For cloze/basic conversion issues, make sure you have both a "Basic" and a "Cloze" note type in Anki (Tools → Manage Note Types)

**Batches getting confused**
- Each batch session must stay in the **same Claude conversation**
- If you accidentally close the tab, start over from Batch 1 in a new conversation

---

## Contributing

Pull requests welcome. A few areas that could use improvement:

- Diff view showing before/after for edit changes
- Undo/rollback support for applied changes
- Support for more than 2 card fields
- Dark/light theme toggle

---

## License

MIT — do whatever you want with it.

---

## Acknowledgements

- [AnkiConnect](https://github.com/FooSoft/anki-connect) by FooSoft Productions — the add-on that makes programmatic Anki access possible
- [Claude](https://claude.ai) by Anthropic — the AI doing the actual deck analysis
- [Fraunces](https://github.com/undercasetype/Fraunces) & [DM Mono](https://fonts.google.com/specimen/DM+Mono) — fonts used in the UI
