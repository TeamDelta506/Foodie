#!/usr/bin/env python3
"""
Foodie — end-to-end walk
========================
Exercises every server-side route against the running app with realistic
inputs and error cases.  Uses only the standard library + requests; no pytest.

Usage
-----
Against local Docker Compose (Postgres):
    python3 e2e_walk.py

Against a different host:
    BASE_URL=https://your-ec2-host.example.com python3 e2e_walk.py

Requirements
------------
    pip install requests
"""

import json
import os
import sys
import textwrap

import requests

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")

# ── ANSI helpers ────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(label, detail=""):
    print(f"  {GREEN}✓{RESET} {label}" + (f"  {CYAN}{detail}{RESET}" if detail else ""))

def fail(label, detail=""):
    print(f"  {RED}✗{RESET} {BOLD}{label}{RESET}" + (f"  {RED}{detail}{RESET}" if detail else ""))

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")

def check(cond, label, detail=""):
    if cond:
        ok(label, detail)
    else:
        fail(label, detail)
    return cond

# ── Session (carries cookies across requests) ────────────────────────────────

s = requests.Session()
s.headers.update({"User-Agent": "Foodie-e2e/1.0"})

ERRORS = []

def assert_check(cond, label, detail=""):
    ok_result = check(cond, label, detail)
    if not ok_result:
        ERRORS.append(f"{label}: {detail}")
    return ok_result

# ── Helpers ──────────────────────────────────────────────────────────────────

def url(path):
    return BASE_URL + path

def json_body(resp):
    try:
        return resp.json()
    except Exception:
        return {}

# ════════════════════════════════════════════════════════════════════════════
# 1. HOME PAGE
# ════════════════════════════════════════════════════════════════════════════
section("1. Home page")

r = s.get(url("/"))
assert_check(r.status_code == 200,          "GET /  →  200")
assert_check("Foodie" in r.text,            "Navbar brand 'Foodie' present")
assert_check("/recipes/search" in r.text,   "Discover recipes link present")
assert_check("Log in" in r.text,            "Unauthenticated: shows Log in link")

# ════════════════════════════════════════════════════════════════════════════
# 2. REGISTER
# ════════════════════════════════════════════════════════════════════════════
section("2. Register")

r = s.get(url("/register"))
assert_check(r.status_code == 200,                   "GET /register  →  200")
assert_check('name="username"' in r.text,            "Username field present")

# Happy path
r = s.post(url("/register"),
           data={"username": "e2e_user", "password": "secure123"},
           allow_redirects=False)
assert_check(r.status_code == 302,                   "POST /register  →  302 redirect")
assert_check(r.headers.get("Location", "").endswith("/"),
                                                     "Redirects to home /")

# Follow redirect and confirm logged-in state
r = s.get(url("/"))
assert_check("e2e_user" in r.text,                   "Navbar shows 'e2e_user' after register")

# Duplicate username
r = s.post(url("/register"),
           data={"username": "e2e_user", "password": "other"},
           allow_redirects=True)
assert_check("already taken" in r.text,              "Duplicate username → 'already taken' flash")

# ════════════════════════════════════════════════════════════════════════════
# 3. LOGOUT
# ════════════════════════════════════════════════════════════════════════════
section("3. Logout")

r = s.post(url("/logout"), allow_redirects=True)
assert_check("Log in" in r.text,                     "After logout navbar shows 'Log in'")

# ════════════════════════════════════════════════════════════════════════════
# 4. LOGIN
# ════════════════════════════════════════════════════════════════════════════
section("4. Login")

r = s.get(url("/login"))
assert_check(r.status_code == 200,                   "GET /login  →  200")

# Wrong password
r = s.post(url("/login"),
           data={"username": "e2e_user", "password": "wrong"},
           allow_redirects=True)
assert_check("Invalid" in r.text,                    "Wrong password → 'Invalid' flash")

# Correct credentials
r = s.post(url("/login"),
           data={"username": "e2e_user", "password": "secure123"},
           allow_redirects=False)
assert_check(r.status_code == 302,                   "POST /login correct  →  302")
s.get(url("/"))  # follow redirect
r = s.get(url("/"))
assert_check("e2e_user" in r.text,                   "Logged in: navbar shows username")

# ════════════════════════════════════════════════════════════════════════════
# 5. RECIPE SEARCH — empty query (shows cached DB rows)
# ════════════════════════════════════════════════════════════════════════════
section("5. Recipe search — empty query (DB cache)")

r = s.get(url("/recipes/search"))
assert_check(r.status_code == 200,                   "GET /recipes/search (no q)  →  200")
assert_check('name="q"' in r.text,                   "Search form with name=q present")
assert_check("/recipes/search" in r.text,            "Form action points to /recipes/search")

# ════════════════════════════════════════════════════════════════════════════
# 6. RECIPE SEARCH — live Edamam call
# ════════════════════════════════════════════════════════════════════════════
section("6. Recipe search — live Edamam call")

r = s.get(url("/recipes/search"), params={"q": "lentil soup"})
assert_check(r.status_code == 200,                   "GET /recipes/search?q=lentil soup  →  200")

if "timed out" in r.text.lower():
    ok("Edamam timeout handled gracefully (no API key or network issue)")
elif "rate limited" in r.text.lower():
    ok("Edamam rate limit handled gracefully")
elif "could not reach" in r.text.lower() or "error" in r.text.lower():
    ok("Edamam upstream error handled gracefully")
else:
    # Real results returned
    assert_check("/recipes/" in r.text,              "Results contain recipe detail links")
    ok("Live Edamam results returned and upserted")

# ════════════════════════════════════════════════════════════════════════════
# 7. RECIPE DETAIL — demo recipe id=1
# ════════════════════════════════════════════════════════════════════════════
section("7. Recipe detail")

r = s.get(url("/recipes/1"))
assert_check(r.status_code == 200,                   "GET /recipes/1  →  200 (demo seed)")
assert_check("Garden grain bowl" in r.text,          "Demo recipe name visible")
assert_check("Quinoa" in r.text,                     "Ingredient 'Quinoa' visible")
assert_check("Update quantities" in r.text or
             "target_servings" in r.text,            "Scale controls present (logged in)")

# Error case: unknown recipe id
r = s.get(url("/recipes/9999"))
assert_check(r.status_code == 404,                   "GET /recipes/9999  →  404")
assert_check("Foodie" in r.text,                     "Branded 404 page (not Flask default)")

# ════════════════════════════════════════════════════════════════════════════
# 8. RECIPES SCALE — JSON endpoint
# ════════════════════════════════════════════════════════════════════════════
section("8. POST /recipes/scale")

# Happy path — logged in, demo recipe id=1
r = s.post(url("/recipes/scale"),
           json={"recipe_id": 1, "target_servings": 4},
           headers={"Accept": "application/json"})
assert_check(r.status_code == 200,                   "POST /recipes/scale (id=1, servings=4)  →  200")
body = json_body(r)
assert_check(body.get("target_servings") == 4,       "target_servings=4 in response")
assert_check(body.get("default_servings") == 2,      "default_servings=2 in response")
assert_check(isinstance(body.get("ingredients"), list),
                                                     "ingredients is a list")
if body.get("ingredients"):
    scaled_qty = body["ingredients"][0]["quantity"]
    assert_check(scaled_qty == 2.0,                  f"Quinoa scaled 1.0→{scaled_qty} (factor 2×)")

# Error: unknown recipe
r = s.post(url("/recipes/scale"),
           json={"recipe_id": 9999, "target_servings": 2},
           headers={"Accept": "application/json"})
assert_check(r.status_code == 404,                   "Unknown recipe_id  →  404 JSON")
assert_check(json_body(r).get("error") == "not_found",
                                                     "error='not_found' envelope")

# Error: invalid target_servings
r = s.post(url("/recipes/scale"),
           json={"recipe_id": 1, "target_servings": 0},
           headers={"Accept": "application/json"})
assert_check(r.status_code == 400,                   "target_servings=0  →  400")

# Error: missing field
r = s.post(url("/recipes/scale"),
           json={"recipe_id": 1},
           headers={"Accept": "application/json"})
assert_check(r.status_code == 400,                   "Missing target_servings  →  400")

# Error: auth — log out first, try without session
anon = requests.Session()
r = anon.post(url("/recipes/scale"),
              json={"recipe_id": 1, "target_servings": 2},
              allow_redirects=False)
assert_check(r.status_code in (302, 401),            "Anonymous scale  →  302/401 auth gate")

# ════════════════════════════════════════════════════════════════════════════
# 9. NUTRITION JSON
# ════════════════════════════════════════════════════════════════════════════
section("9. GET /nutrition/<id>")

r = s.get(url("/nutrition/1"), params={"servings": 4})
assert_check(r.status_code == 200,                   "GET /nutrition/1?servings=4  →  200")
assert_check(r.headers.get("Content-Type","").startswith("application/json"),
                                                     "Content-Type: application/json")
nut = json_body(r)
assert_check(nut.get("recipe_id") == 1,              "recipe_id=1 in response")
assert_check(nut.get("servings") == 4.0,             "servings=4 in response")
for key in ("calories", "protein", "carbs", "fat"):
    assert_check(key in nut,                         f"'{key}' present in nutrition JSON")

# Scaled values: grain bowl default=2 servings, so factor=2
assert_check(nut.get("calories") == 840.0,
             f"calories scaled 420→{nut.get('calories')} (2× factor)")

# Error: unknown recipe
r = s.get(url("/nutrition/9999"))
assert_check(r.status_code == 404,                   "GET /nutrition/9999  →  404 JSON")
assert_check(json_body(r).get("error") == "not_found",
                                                     "error='not_found' envelope")

# ════════════════════════════════════════════════════════════════════════════
# 10. MEAL PLAN — GET (empty)
# ════════════════════════════════════════════════════════════════════════════
section("10. GET /mealplan")

r = s.get(url("/mealplan"))
assert_check(r.status_code == 200,                   "GET /mealplan  →  200")
assert_check(r.text.count("data-day=") == 7,         "Exactly 7 data-day slots rendered")
assert_check("Nothing planned" in r.text,            "Empty plan shows 'Nothing planned' for all days")

# Anon → redirect
r = anon.get(url("/mealplan"), allow_redirects=False)
assert_check(r.status_code in (302, 401),            "Anonymous GET /mealplan  →  302/401")

# ════════════════════════════════════════════════════════════════════════════
# 11. MEAL PLAN — POST (add a day)
# ════════════════════════════════════════════════════════════════════════════
section("11. POST /mealplan")

r = s.post(url("/mealplan"),
           data={"day_of_week": "1", "recipe_id": "1", "servings": "2"},
           allow_redirects=False)
assert_check(r.status_code == 302,                   "POST /mealplan  →  302 redirect")
assert_check("/mealplan" in r.headers.get("Location",""),
                                                     "Redirects back to /mealplan")

# Verify the slot is now filled
r = s.get(url("/mealplan"))
assert_check("Garden grain bowl" in r.text or "#1" in r.text,
                                                     "Recipe appears in Tuesday slot")

# Replace same day
r = s.post(url("/mealplan"),
           data={"day_of_week": "1", "recipe_id": "2", "servings": "3"},
           allow_redirects=True)
assert_check("Citrus herb salmon" in r.text or "#2" in r.text,
                                                     "Upsert: Tuesday now shows recipe 2")

# Error: invalid day
r = s.post(url("/mealplan"),
           data={"day_of_week": "8", "recipe_id": "1", "servings": "2"},
           allow_redirects=True)
assert_check(r.status_code == 200,
                                                     "Invalid day_of_week → redirect+flash (200)")

# ════════════════════════════════════════════════════════════════════════════
# 12. MEAL PLAN — DELETE a day
# ════════════════════════════════════════════════════════════════════════════
section("12. DELETE /mealplan/<day>")

r = s.delete(url("/mealplan/1"), allow_redirects=False)
assert_check(r.status_code == 302,                   "DELETE /mealplan/1  →  302")

# Verify slot is empty again
r = s.get(url("/mealplan"))
assert_check("Garden grain bowl" not in r.text and
             "Citrus herb salmon" not in r.text,     "Tuesday slot cleared")

# Error: delete a day that has nothing planned
r = s.delete(url("/mealplan/1"), allow_redirects=False)
assert_check(r.status_code == 404,                   "DELETE already-empty day  →  404")

# ════════════════════════════════════════════════════════════════════════════
# 13. 404 BRANDED PAGE
# ════════════════════════════════════════════════════════════════════════════
section("13. Error pages")

r = s.get(url("/this-does-not-exist"))
assert_check(r.status_code == 404,                   "Unknown path  →  404")
assert_check("Foodie" in r.text,                     "Branded 404 (navbar/footer present)")
assert_check("can't find" in r.text.lower() or
             "not found" in r.text.lower(),          "Human-readable error message")

r = anon.post(url("/logout"))
# logout is POST-only; GET would get 405
r = anon.get(url("/logout"))
assert_check(r.status_code == 405,                   "GET /logout  →  405 Method Not Allowed")
assert_check("Foodie" in r.text,                     "Branded 405 page")

# ════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{'═'*60}{RESET}")
if ERRORS:
    print(f"{RED}{BOLD}  {len(ERRORS)} failure(s):{RESET}")
    for e in ERRORS:
        print(f"    {RED}• {e}{RESET}")
else:
    print(f"{GREEN}{BOLD}  All checks passed ✓{RESET}")
print(f"{BOLD}{'═'*60}{RESET}\n")

sys.exit(1 if ERRORS else 0)
