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
    sample = cards[:80]
    batch_note = f' (Batch {batch_index+1} of {total_batches})' if total_batches > 1 else ''
    cards_json = json.dumps([{
        "id": c["id"], "front": c["front"][:400], "back": c["back"][:400], "tags": c["tags"]
    } for c in sample], indent=2)

    custom = data.get("customInstructions", "").strip()
    custom_block = f"\n\nSPECIAL INSTRUCTIONS (follow these strictly, they override the default rules below):\n{custom}\n" if custom else ""
    prompt = f"""You are an expert Anki deck curator. Analyze these {len(sample)} flashcards from the deck "{deck}"{batch_note} and produce a structured improvement plan.
{custom_block}
CARDS:
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
- Limit to the 25 most impactful changes.
- If the special instructions ask you to add new cards, use the "add_card" type with empty card_ids [].
- For basic cards: put the question in new_front and answer in new_back.
- For cloze cards: put the full sentence with {{{{c1::hidden text}}}} syntax in new_front. You may use multiple cloze deletions (c1, c2, c3...). Leave new_back empty or use it for extra context.
- CRITICAL — MathJax preservation: Some cards contain MathJax math notation using \\(...\\) for inline math and \\[...\\] for block math. You MUST copy these delimiters and their contents exactly as they appear. Do NOT convert them to $...$ or $$...$$. Do NOT strip, rewrite, or paraphrase any math expression. If you cannot preserve the math notation exactly, do not suggest an edit or merge for that card — suggest a retag only.
- Return valid JSON only. No markdown fences. No preamble."""

    return jsonify({"prompt": prompt, "card_count": len(sample)})


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
                update_fields = {}
                note_info = anki("notesInfo", notes=[primary_id])[0]
                field_names = list(note_info["fields"].keys())
                if ctype != "retag":
                    if len(field_names) >= 1 and change.get("new_front"):
                        update_fields[field_names[0]] = change["new_front"]
                    if len(field_names) >= 2 and change.get("new_back"):
                        update_fields[field_names[1]] = change["new_back"]
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
                            "Text": change.get("new_front", ""),
                            "Back Extra": change.get("new_back", "")
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
                            "Front": change.get("new_front", ""),
                            "Back": change.get("new_back", "")
                        },
                        "tags": change.get("new_tags", []),
                        "options": {"allowDuplicate": True, "duplicateScope": "deck"}
                    }
                new_id = anki("addNote", note=note)
                results.append({"id": new_id, "status": "ok", "type": "add_card"})

        except Exception as e:
            results.append({"ids": card_ids, "status": "error", "error": str(e), "type": ctype})

    return jsonify({"results": results})

# ── Static files ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    print("🃏 Anki AI Manager running → http://localhost:5050")
    app.run(port=5050, debug=False)
