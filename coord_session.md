# Coordinator–LLM Session — Foodie (Week 6)

**Project:** Foodie — Recipe Scaler and Meal Planner  
**Team:** TeamDelta506 (Sam, Asia, Justin, Sowmya)  
**Coordinator:** Sowmya Korasikha  
**LLM:** Claude (Anthropic) via Cursor IDE  
**Session date:** Wednesday, May 13, 2026 (PDT)  
**Working repo:** `github.com/TeamDelta506/Foodie` (default branch `master`, recreated from `lhhunghimself/week_5_506_starter`)

---

## Prologue — context the LLM gathered before we started

Before I (Sowmya) started making decisions, the LLM read and summarized:

1. **The team's agreed About page**
   (`https://raw.githubusercontent.com/sowmyakb/week_5_506/master/templates/about.html`) — Foodie's project pitch, 7 endpoints, 4-table schema, Edamam Recipe Search API as primary data source (USDA FoodData Central as backup), and our role assignments:
   - Sam — server-side  
   - Asia — client-side (frontend, UI/UX, JavaScript & CSS)  
   - Justin — database management, security, system design  
   - Sowmya — coordinator (`CONTRACTS.md`, integration testing, PR review)
2. **The team repo's state at session start** — Asia recreated `TeamDelta506/Foodie` on **2026-05-09** from the official `week_5_506_starter` template. At kickoff it was effectively the **raw skeleton**: starter `User` model, raw `session["user_id"]` auth, starter templates, `tests/test_auth.py`, placeholder `contracts/` notes — no Foodie-specific routes yet.
3. **The Brew Crew / StudySpot worked example** (`https://github.com/lhhunghimself/study_spot_demo`) — structural model for `CONTRACTS.md` depth (schema tables, endpoint envelopes, external API failure semantics, role boundaries).
4. **CI** — `.github/workflows/test.yml` was re-enabled on **`master`** (commit **`00bfdd0`**, CI job name **`test`**) *before* this contracts PR; branch protection (require status check `test`) was delegated to the org admin (Asia) as a follow-up click in GitHub Settings.

---

## How we ran this session

The LLM surfaced design forks **one at a time** (recipe cache semantics, `/nutrition` purpose, meal-plan granularity, Edamam failure/tuning, anon vs auth, identifier semantics). For each item Sowmya either chose a lane, pushed back, or **consulted teammates on Discord** when the call touched implementation load for Sam / Justin / Asia. The intent (per Canvas) is a transcript that shows **real engagement**, not coordinator-only dictation.

---

## Session log

<!-- Full decision log — mirrors the working notes file used during the live Cursor session -->

### Decision 1 — What is the `recipes` table for?

**LLM framing:** The About page lists `Recipes(id, api_id, name, image_url, calories, protein, carbs, fat)` — no `user_id`. The pitch says "save recipes …" Three options: **A** global Edamam cache, **B** per-user saved rows only, **C** cache + separate favorites table.

**Coordinator response:** Sowmya surfaced **A vs B** to **Sam and Justin** on Discord; both endorsed **A** quickly.

**Resolution:** **`recipes` is a shared cache**; “save” in Week 6 means **meal-plan assignment**, not a favorites feature. Documented as Known limitation §6 in `CONTRACTS.md`.

---

### Decision 4 — Is `/nutrition/<id>` redundant with `/recipes/<id>`?

**LLM framing:** Detail HTML already shows macros — standalone `/nutrition` looked redundant until repurposed.

**LLM pushback:** Initially argued drop; then reversed — repurposing as **scaled JSON** matches "Recipe Scaler" and keeps the About page’s **7-endpoint** plan intact.

**Coordinator response:** Sowmya chose **repurpose** (**Option B** in session).

**Resolution:** **`GET /nutrition/<id>?servings=N`** returns JSON scaled macros (omit `servings` → use `default_servings` on the recipe row).

---

### Decision 3 — Meal plan slots: per day vs per meal-type

**LLM framing:** Schema sketch has no `meal_type`; realistic apps often want /meal-types.

**Coordinator response:** Sowmya posted **A vs B** to the team**; channel quiet by cutoff → coordinator exercised the documented default.

**Resolution:** **One slot per weekday** (`UNIQUE (user_id, day_of_week)`). **0 = Monday … 6 = Sunday**. Multi-slot days → Week 7+ / §6 known limitation.

---

### Decision 5 — Edamam failure handling for search

**Resolution:** **4s** outbound timeout. **Four** user-facing codes: **`timeout`**, **`rate_limited`**, **`upstream_error`**, **`upstream_invalid`**. Upstream **401/403** fold into **`upstream_error`** with loud **server logs** — not a separate flash string. Search stays **HTTP 200** with visible alert on upstream failure; may still show cached hits. §6 **softened** language on indefinite caching vs production compliance paths (**Premium / TTL / USDA**).

---

### Decision 6 — Anonymous access footprint

**Resolution:** **Public read** for search + detail + nutrition JSON. **Login** for scale + all meal-plan routes (redirect to login).

---

### Decision 2 — Meaning of `<id>` in `/recipes/<id>` and `/nutrition/<id>`

**Resolution:** **`<id>` is always internal `recipes.id` (PK)**. **`api_id`** is for upsert/dedupe only.

---

## Teammate consultation summary

| Topic | Where raised | Outcome |
|--------|----------------|----------|
| Global cache vs favorites | Discord — Sam, Justin | Unanimous **A** (cache) |
| One meal vs three per day | Discord — whole dev team | Coordinator default **A** after quiet window |

---

## Artifacts delivered after this session

- `CONTRACTS.md` at repo root (binding spec).  
- **Four** new pytest modules under `tests/` — all **red** at opening merge; green when roles land.  
- Coordinator transcript (**this file**), lightly edited for clarity (typos / ordering only).

---

## Reflection

The useful friction in this session was deciding what *not* to build (favorites table, multi-meal days, extra error taxonomies) so Week 6 stays integration-shaped. The counterweight was **`/nutrition` repurposing** — a small surface area with high demo value.
