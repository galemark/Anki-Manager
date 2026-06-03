import json
import os
import re
import urllib.request
import urllib.error
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')

ANKI_CONNECT_URL = "http://127.0.0.1:8765"

# ── AnkiConnect helpers ──────────────────────────────────────────────────────

def anki(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode()
    req = urllib.request.Request(ANKI_CONNECT_URL, payload, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            if resp.get("error"):
                raise RuntimeError(resp["error"])
            return resp["result"]
    except urllib.error.URLError:
        raise RuntimeError("Cannot reach AnkiConnect. Make sure Anki is open and AnkiConnect add-on is installed.")

# ── Routes: status & data ────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    try:
        anki("version")
        return jsonify({"connected": True})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})

@app.route("/api/decks")
def get_decks():
    try:
        decks = anki("deckNames")
        return jsonify({"decks": decks})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/deck-stats")
def get_deck_stats():
    deck = request.args.get("deck", "")
    if not deck:
        return jsonify({"error": "No deck specified"}), 400
    try:
        stats = anki("getDeckStats", decks=[deck])
        # getDeckStats returns a dict keyed by deck id; grab the first (and only) value
        deck_stat = next(iter(stats.values())) if stats else {}
        return jsonify({
            "new":     deck_stat.get("new_count", 0),
            "learn":   deck_stat.get("learn_count", 0),
            "due":     deck_stat.get("review_count", 0),
            "total":   deck_stat.get("total_in_deck", 0),
            "reviews": deck_stat.get("reviews_today", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/anki-browse", methods=["POST"])
def anki_browse():
    data = request.json
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "No query provided"}), 400
    try:
        anki("guiBrowse", query=query)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cards")
def get_cards():
    deck = request.args.get("deck", "")
    try:
        query = f'deck:"{deck}"' if deck else "deck:*"
        ids = anki("findNotes", query=query)
        if not ids:
            return jsonify({"cards": []})
        notes = anki("notesInfo", notes=ids)
        cards = []
        for n in notes:
            # Exclude 00 Topic Map notes — these are reference cards, not study cards
            if n.get("modelName") == "00 Topic Map":
                continue
            fields = n.get("fields", {})
            front = next(iter(fields.values()), {}).get("value", "") if fields else ""
            back = list(fields.values())[1]["value"] if len(fields) > 1 else ""
            cards.append({
                "id": n["noteId"],
                "front": front,
                "back": back,
                "tags": n.get("tags", []),
                "deck": deck or "unknown",
                "modelName": n.get("modelName", "")
            })
        return jsonify({"cards": cards})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── MathJax helpers ──────────────────────────────────────────────────────────

def has_mathjax(text):
    """Return True if text contains MathJax delimiters \\(...\\) or \\[...\\]"""
    return r'\(' in text or r'\[' in text

def to_anki_html(text):
    """Convert plain-text field content to Anki-compatible HTML.
    Replaces newlines with <br> so bullet lists and multi-line backs
    render correctly inside Anki's HTML card renderer.
    Skips conversion if the text already contains HTML tags.
    """
    if not text:
        return text
    if '<' in text and '>' in text:
        # Already contains HTML — don't double-convert
        return text
    return text.replace('\n', '<br>')

def check_math_warning(change, card_map):
    """
    Return True if a change rewrites content and strips MathJax that was
    present in the original card(s). Only applies to edit_card and merge_duplicate.
    """
    ctype = change.get("type")
    if ctype not in ("edit_card", "merge_duplicate"):
        return False

    # Check if any original card involved had MathJax
    original_has_math = False
    for cid in change.get("card_ids", []):
        card = card_map.get(str(cid)) or card_map.get(cid)
        if card:
            if has_mathjax(card.get("front", "")) or has_mathjax(card.get("back", "")):
                original_has_math = True
                break

    if not original_has_math:
        return False

    # Check if the rewritten content still has MathJax
    new_front = change.get("new_front", "")
    new_back = change.get("new_back", "")
    rewritten_has_math = has_mathjax(new_front) or has_mathjax(new_back)

    return not rewritten_has_math


# ── Routes: AI analysis ──────────────────────────────────────────────────────

@app.route("/api/export-prompt", methods=["POST"])
def export_prompt():
    """Generate the prompt text for the user to paste into Claude.ai"""
    data = request.json
    cards = data.get("cards", [])
    deck = data.get("deck", "selected deck")

    if not cards:
        return jsonify({"error": "No cards provided"}), 400

    batch_index = data.get('batchIndex', 0)
    total_batches = data.get('totalBatches', 1)
    sample = cards[:100]
    card_count = len(sample)
    is_hold_batch = total_batches > 1 and batch_index < total_batches - 1
    cards_json = json.dumps([{
        "id": c["id"], "front": c["front"][:400], "back": c["back"][:400], "tags": c["tags"]
    } for c in sample], indent=2)

    custom = data.get("customInstructions", "").strip()
    obsidian_ref = data.get("obsidianRef", "").strip()

    # Build obsidian block — injected before custom instructions
    if obsidian_ref:
        notes_list = ', '.join([f'"{n.strip()}"' for n in obsidian_ref.split(',') if n.strip()])
        obsidian_block = f"\n\nOBSIDIAN REFERENCE (read these notes from the connected Obsidian vault via MCP before improving cards, use them as your factual reference):\n{notes_list}\n"
    else:
        obsidian_block = ""

    custom_block = f"\n\nSPECIAL INSTRUCTIONS (follow these strictly, they override the default rules below):\n{custom}\n" if custom else ""

    if is_hold_batch:
        prompt = f"""You are an expert Anki deck curator receiving card data in multiple batches before analysis.
{obsidian_block}
This is Batch {batch_index+1} of {total_batches} from the deck "{deck}". There are more batches to come.

DO NOT analyze. DO NOT suggest changes. DO NOT produce any JSON.
Simply acknowledge receipt and wait for the next batch.

Reply ONLY with exactly this text (filling in the batch numbers):
Batch {batch_index+1} of {total_batches} received. Waiting for next batch.

CARDS IN THIS BATCH:
{cards_json}"""
    else:
        batch_note = f' — Final batch ({batch_index+1} of {total_batches}). This completes the full deck.' if total_batches > 1 else ''
        intro = (
            f"You have now received all {total_batches} batches of cards from the deck \"{deck}\". "
            f"Analyze ALL cards across ALL batches as a single unified deck and produce your improvement plan now."
            if total_batches > 1 else
            f"You are an expert Anki deck curator. Analyze these {card_count} flashcards from the deck \"{deck}\" and produce a structured improvement plan."
        )
        prompt = f"""{intro}{batch_note}
{obsidian_block}{custom_block}
CARDS (this batch):
{cards_json}

Respond ONLY with a JSON object (no markdown, no explanation, just raw JSON) with this exact structure:
{{
  "summary": "2-3 sentence overview of deck quality and main issues found",
  "stats": {{
    "total_analyzed": <number>,
    "duplicates_found": <number>,
    "quality_issues": <number>,
    "retagging_needed": <number>
  }},
  "changes": [
    {{
      "type": "merge_duplicate",
      "card_ids": [<id1>, <id2>],
      "reason": "short reason",
      "new_front": "merged front text",
      "new_back": "merged back text",
      "new_tags": ["tag1", "tag2"]
    }},
    {{
      "type": "edit_card",
      "card_ids": [<id>],
      "reason": "short reason",
      "new_front": "improved front",
      "new_back": "improved back",
      "new_tags": ["tag1"]
    }},
    {{
      "type": "retag",
      "card_ids": [<id>],
      "reason": "short reason",
      "new_tags": ["tag1", "tag2"]
    }},
    {{
      "type": "delete",
      "card_ids": [<id>],
      "reason": "short reason — only for truly redundant cards already merged"
    }},
    {{
      "type": "add_card",
      "card_ids": [],
      "reason": "short reason why this card is being added",
      "new_front": "front text of the new card (for cloze cards, use {{{{c1::answer}}}} syntax here)",
      "new_back": "back text or extra info (leave empty for cloze cards if not needed)",
      "new_tags": ["tag1", "tag2"]
    }}
  ]
}}

Default rules (apply unless overridden by special instructions above):
- Be specific and actionable. Only suggest changes that genuinely improve the deck.
- For duplicates: merge into the better card, mark the other for deletion.
- For tagging: use hierarchical tags like "hematology::rbc" or "coagulation::factors".
- For edits: improve clarity, atomicity, and recall precision.
- Suggest as many changes as you find necessary, prioritizing the most impactful changes first. Stop when you have covered all genuine issues or when continuing would risk truncating your output — whichever comes first.
- If the special instructions ask you to add new cards, use the "add_card" type with empty card_ids [].
- For basic cards: put the question in new_front and answer in new_back.
- For cloze cards: put the full sentence with {{{{c1::hidden text}}}} syntax in new_front. You may use multiple cloze deletions (c1, c2, c3...). Leave new_back empty or use it for extra context.
- CRITICAL — MathJax preservation: Some cards contain MathJax math notation using \\(...\\) for inline math and \\[...\\] for block math. You MUST copy these delimiters and their contents exactly as they appear. Do NOT convert them to $...$ or $$...$$. Do NOT strip, rewrite, or paraphrase any math expression. If you cannot preserve the math notation exactly, do not suggest an edit or merge for that card — suggest a retag only.
- Return valid JSON only. No markdown fences. No preamble."""

    return jsonify({"prompt": prompt, "card_count": card_count, "is_hold_batch": is_hold_batch})


@app.route("/api/analyze-topics", methods=["POST"])
def analyze_topics():
    """Generate a topic-listing prompt — no card changes, just extract what subjects the deck covers.
    Supports the same hold/final batch pattern as export_prompt so the full deck is always covered.
    id and tags are intentionally omitted — topic mapping only needs front/back content.
    """
    data = request.json
    cards = data.get("cards", [])
    deck = data.get("deck", "selected deck")

    if not cards:
        return jsonify({"error": "No cards provided"}), 400

    batch_index   = data.get("batchIndex", 0)
    total_batches = data.get("totalBatches", 1)
    batch_size    = 100
    start         = batch_index * batch_size
    batch_cards   = cards[start:start + batch_size]
    card_count    = len(batch_cards)
    is_hold_batch = total_batches > 1 and batch_index < total_batches - 1

    # id and tags intentionally excluded — topic mapping only needs content
    cards_json = json.dumps([{
        "front": c["front"][:300], "back": c["back"][:300]
    } for c in batch_cards], indent=2)

    if is_hold_batch:
        prompt = f"""You are analyzing an Anki flashcard deck to extract a structured topic map. You are receiving the card data in multiple batches before producing any output.

This is Batch {batch_index+1} of {total_batches} from the deck "{deck}". There are more batches to come.

DO NOT produce a topic map yet. DO NOT list topics. DO NOT produce any output other than the acknowledgement below.
Simply store these cards in context and wait for the next batch.

Reply ONLY with exactly this text (filling in the batch numbers):
Batch {batch_index+1} of {total_batches} received. Waiting for next batch.

CARDS IN THIS BATCH:
{cards_json}"""
    else:
        batch_note = (
            f" — Final batch ({batch_index+1} of {total_batches}). This completes the full deck."
            if total_batches > 1 else ""
        )
        intro = (
            f"You have now received all {total_batches} batches of cards from the deck \"{deck}\". "
            f"Analyze ALL cards across ALL batches as a single unified deck and produce the topic map now."
            if total_batches > 1 else
            f"You are analyzing an Anki flashcard deck to extract a structured topic map."
        )

        prompt = f"""{intro}{batch_note}

Deck: "{deck}"
Total cards in this batch: {card_count}

Your ONLY job is to list every topic and subtopic covered by these cards.
Do NOT suggest improvements. Do NOT flag issues. Do NOT produce JSON.
Just produce a clean, structured topic list.

Format your response exactly like this example:
───────────────────────────────
TOPIC MAP — {deck}
───────────────────────────────

1. [Main Topic]
   • [Subtopic]
   • [Subtopic]

2. [Main Topic]
   • [Subtopic]
   • [Subtopic]
───────────────────────────────
OBSIDIAN NOTES NEEDED
───────────────────────────────
List only the topics above that would benefit most from a reference note in Obsidian before card improvement. One line each. Be specific.

Rules:
- Group related cards into logical subject areas
- Use the medical/scientific subject name as the main topic (e.g. "Coagulation Cascade", not "Blood stuff")
- Subtopics should be specific enough to search in a textbook or NotebookLM
- If a card's topic is already implied by the deck name, still list it explicitly
- List topics in order of how many cards cover them (most covered first)
- At the end, add the "OBSIDIAN NOTES NEEDED" section listing topics that are complex or foundational enough to warrant a reference note

CARDS (this batch):
{cards_json}"""

    return jsonify({"prompt": prompt, "card_count": card_count, "is_hold_batch": is_hold_batch})


@app.route("/api/parse-response", methods=["POST"])
def parse_response():
    """Parse the JSON response pasted back from Claude.ai"""
    data = request.json
    raw = data.get("response", "").strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # ── Parse: try raw first, then apply escape fix for other LLMs ──────────
    # Strategy: attempt json.loads() on the unmodified string first.
    # Claude's output is already valid JSON and must never be pre-processed.
    # Only if that fails do we apply the escape-fix regex, which corrects raw
    # backslashes written by ChatGPT/Gemini (e.g. \( \[ \times instead of \\( \\[ \\times).
    def _try_parse(s):
        try:
            return json.loads(s), None
        except json.JSONDecodeError as e:
            return None, e

    result, err = _try_parse(raw)
    if result is None:
        # Fix bare backslashes not followed by a valid JSON escape char.
        # The negative lookbehind (?<!\\) skips already-doubled backslashes.
        fixed = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', raw)
        # \f is a valid JSON escape (form feed) so Pass 1 skips it, but in
        # card content \f almost always means LaTeX \frac, \fbox, etc.
        # Re-double it when followed by a letter (only if still single).
        fixed = re.sub(r'(?<!\\)\\f(?=[a-zA-Z])', r'\\\\f', fixed)
        result, err = _try_parse(fixed)

    if result is None:
        return jsonify({"error": f"Could not parse response: {str(err)}. Make sure you copied the full response from Claude."}), 400

    # ── MathJax safety check ──────────────────────────────────────────────
    # Build a lookup from the original cards passed alongside the response
    original_cards = data.get("cards", [])
    card_map = {str(c["id"]): c for c in original_cards}

    math_warning_count = 0
    for change in result.get("changes", []):
        if check_math_warning(change, card_map):
            change["math_warning"] = True
            math_warning_count += 1
        else:
            change["math_warning"] = False

    if math_warning_count:
        result["math_warning_count"] = math_warning_count

    return jsonify(result)

# ── Routes: apply changes ────────────────────────────────────────────────────

@app.route("/api/apply", methods=["POST"])
def apply_changes():
    data = request.json
    changes = data.get("changes", [])
    results = []
    deck = data.get("deck", "Default")

    for change in changes:
        ctype = change.get("type")
        card_ids = change.get("card_ids", [])
        try:
            if ctype in ("edit_card", "merge_duplicate", "retag"):
                primary_id = card_ids[0]
                note_info = anki("notesInfo", notes=[primary_id])[0]
                field_names = list(note_info["fields"].keys())
                current_model = note_info.get("modelName", "")

                if ctype != "retag":
                    new_front = change.get("new_front", "")
                    is_cloze_target = "{{c" in new_front
                    is_cloze_current = "cloze" in current_model.lower()

                    if is_cloze_target != is_cloze_current:
                        # Model type mismatch — create a new note with the correct type, delete the old one
                        try:
                            model_names = anki("modelNames")
                        except Exception:
                            model_names = []

                        if is_cloze_target:
                            cloze_model = next((m for m in model_names if "cloze" in m.lower()), None)
                            if not cloze_model:
                                raise RuntimeError("No Cloze note type found in Anki. Please add one first.")
                            new_note = {
                                "deckName": deck,
                                "modelName": cloze_model,
                                "fields": {
                                    "Text": to_anki_html(new_front),
                                    "Back Extra": to_anki_html(change.get("new_back", ""))
                                },
                                "tags": change.get("new_tags", []),
                                "options": {"allowDuplicate": True, "duplicateScope": "deck"}
                            }
                        else:
                            model_name = "Basic" if "Basic" in model_names else (model_names[0] if model_names else "Basic")
                            new_note = {
                                "deckName": deck,
                                "modelName": model_name,
                                "fields": {
                                    "Front": to_anki_html(new_front),
                                    "Back": to_anki_html(change.get("new_back", ""))
                                },
                                "tags": change.get("new_tags", []),
                                "options": {"allowDuplicate": True, "duplicateScope": "deck"}
                            }

                        new_id = anki("addNote", note=new_note)
                        # Delete old note and any secondary duplicates
                        anki("deleteNotes", notes=card_ids)
                        results.append({"id": new_id, "status": "ok", "type": ctype, "model_converted": True})
                        continue

                    # No model mismatch — update fields in place as normal
                    update_fields = {}
                    if len(field_names) >= 1 and new_front:
                        update_fields[field_names[0]] = to_anki_html(new_front)
                    if len(field_names) >= 2 and change.get("new_back"):
                        update_fields[field_names[1]] = to_anki_html(change["new_back"])
                    if update_fields:
                        anki("updateNoteFields", note={"id": primary_id, "fields": update_fields})

                if change.get("new_tags"):
                    anki("updateNoteTags", note=primary_id, tags=" ".join(change["new_tags"]))
                # Delete secondary duplicates
                if ctype == "merge_duplicate" and len(card_ids) > 1:
                    anki("deleteNotes", notes=card_ids[1:])
                results.append({"id": primary_id, "status": "ok", "type": ctype})

            elif ctype == "delete":
                anki("deleteNotes", notes=card_ids)
                results.append({"ids": card_ids, "status": "ok", "type": "delete"})

            elif ctype == "add_card":
                try:
                    model_names = anki("modelNames")
                except Exception:
                    model_names = []
                is_cloze = "{{c" in change.get("new_front", "")
                if is_cloze:
                    cloze_model = next((m for m in model_names if "cloze" in m.lower()), None)
                    if not cloze_model:
                        raise RuntimeError("No Cloze note type found in Anki. Please add one first.")
                    note = {
                        "deckName": deck,
                        "modelName": cloze_model,
                        "fields": {
                            "Text": to_anki_html(change.get("new_front", "")),
                            "Back Extra": to_anki_html(change.get("new_back", ""))
                        },
                        "tags": change.get("new_tags", []),
                        "options": {"allowDuplicate": True, "duplicateScope": "deck"}
                    }
                else:
                    model_name = "Basic" if "Basic" in model_names else (model_names[0] if model_names else "Basic")
                    note = {
                        "deckName": deck,
                        "modelName": model_name,
                        "fields": {
                            "Front": to_anki_html(change.get("new_front", "")),
                            "Back": to_anki_html(change.get("new_back", ""))
                        },
                        "tags": change.get("new_tags", []),
                        "options": {"allowDuplicate": True, "duplicateScope": "deck"}
                    }
                new_id = anki("addNote", note=note)
                results.append({"id": new_id, "status": "ok", "type": "add_card"})

        except Exception as e:
            results.append({"ids": card_ids, "status": "error", "error": str(e), "type": ctype})

    return jsonify({"results": results})

# ── Routes: topic map ────────────────────────────────────────────────────────

@app.route("/api/save-topic-map", methods=["POST"])
def save_topic_map():
    """Create or update the '00 Topic Map' note for the selected deck.
    The note is immediately suspended (never reviewed) and flagged purple (flag 7).
    Only the topic list portion is saved — the Obsidian Notes Needed section is UI-only.
    """
    data = request.json
    deck = data.get("deck", "")
    content = data.get("content", "").strip()
    generated = data.get("generated", "")

    if not deck:
        return jsonify({"error": "No deck specified"}), 400
    if not content:
        return jsonify({"error": "No content provided"}), 400

    # ── Convert plain-text topic map to Anki-compatible HTML ─────────────────
    # Newlines are ignored in Anki's HTML renderer; we convert the structured
    # plain-text output (numbered topics, bullet subtopics, separator lines)
    # into styled HTML so it renders cleanly inside the card viewer.
    def topic_map_to_html(text):
        lines = text.splitlines()
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                html_lines.append('<br>')
            elif all(c in '─—- ' for c in stripped) and len(stripped) > 3:
                # Separator line
                html_lines.append('<hr style="border:none;border-top:1px solid #2a2d35;margin:6px 0;">')
            elif stripped.startswith('•'):
                item = stripped[1:].strip()
                html_lines.append(f'<div style="padding-left:1.4em;color:#b0b5c0;">&bull; {item}</div>')
            elif len(stripped) > 1 and stripped[0].isdigit() and '.' in stripped[:4]:
                html_lines.append(f'<div style="margin-top:0.7em;color:#c9a9f0;font-weight:500;">{stripped}</div>')
            else:
                html_lines.append(f'<div>{stripped}</div>')
        return '\n'.join(html_lines)

    content_html = topic_map_to_html(content)

    # ── Find existing topic map note for this deck ────────────────────────────
    existing_ids = anki("findNotes", query=f'note:"00 Topic Map" deck:"{deck}"')

    if existing_ids:
        # Update the existing note
        note_id = existing_ids[0]
        anki("updateNoteFields", note={
            "id": note_id,
            "fields": {
                "Deck": deck,
                "Generated": generated,
                "Content": content_html
            }
        })
        # Re-fetch the card id(s) for this note to suspend & flag
        card_ids = anki("findCards", query=f'nid:{note_id}')
        created = False
    else:
        # Create a new note
        note_id = anki("addNote", note={
            "deckName": deck,
            "modelName": "00 Topic Map",
            "fields": {
                "Deck": deck,
                "Generated": generated,
                "Content": content_html
            },
            "options": {"allowDuplicate": False, "duplicateScope": "deck"}
        })
        card_ids = anki("findCards", query=f'nid:{note_id}')
        created = True

    if not card_ids:
        return jsonify({"error": "Could not find card(s) for the saved note"}), 500

    # ── Suspend the card so it never appears in reviews ───────────────────────
    anki("suspend", cards=card_ids)

    # ── Flag purple (flag 7) ──────────────────────────────────────────────────
    for cid in card_ids:
        anki("setSpecificValueOfCard", card=cid, keys=["flags"], newValues=[7])

    return jsonify({
        "ok": True,
        "created": created,
        "note_id": note_id,
        "card_ids": card_ids
    })


# ── Static files ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    print("🃏 Anki AI Manager running → http://localhost:5050")
    app.run(port=5050, debug=False)
