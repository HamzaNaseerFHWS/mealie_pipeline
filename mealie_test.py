"""Minimal Mealie API smoke test (stdlib only).

Usage (PowerShell):
  $env:MEALIE_URL="http://localhost:9925"
  $env:MEALIE_TOKEN="<token>"
  python mealie_test.py check
  python mealie_test.py url https://example.com/some-recipe
  python mealie_test.py manual
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ["MEALIE_URL"].rstrip("/")
TOKEN = os.environ["MEALIE_TOKEN"]


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = r.read().decode()
            return r.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    mode = sys.argv[1]
    if mode == "check":
        print(call("GET", "/api/users/self"))
    elif mode == "url":
        print(call("POST", "/api/recipes/create/url", {"url": sys.argv[2], "includeTags": False}))
    elif mode == "manual":
        status, slug = call("POST", "/api/recipes", {"name": "Pipeline Test Recipe"})
        print("create:", status, slug)
        status, recipe = call("GET", f"/api/recipes/{slug}")
        recipe["description"] = "Created via API smoke test"
        recipe["recipeIngredient"] = [
            {"note": "200 g spaghetti"},
            {"note": "2 cloves garlic"},
            {"note": "3 tbsp olive oil"},
        ]
        recipe["recipeInstructions"] = [
            {"text": "Boil the spaghetti until al dente."},
            {"text": "Fry garlic in olive oil, toss with pasta."},
        ]
        print("patch:", call("PATCH", f"/api/recipes/{slug}", recipe)[0])
        print(f"Open: {BASE}/g/home/r/{slug}")


main()
