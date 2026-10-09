"""Check that the Mealie API is reachable and usable for the pipeline.

Standard library only, so it runs on a fresh Windows Python without installing anything:

    py scripts\\check_mealie.py --url http://mealie.taildce5a6.ts.net:9000
    py scripts\\check_mealie.py --url http://mealie.taildce5a6.ts.net:9000 --write-test

The token is read from the MEALIE_TOKEN environment variable, or asked for interactively.
--write-test creates a throwaway recipe with a parsed ingredient and a tag, reads it back, and deletes it.
A summary without the token is written to mealie_check_report.json for sharing.
"""

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPORT_FILE = "mealie_check_report.json"


class Mealie:
    def __init__(self, base_url: str, token: str | None):
        self.base = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, body=None, auth: bool = True):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:500]

    def get_all(self, path: str):
        status, body = self.request("GET", f"{path}?perPage=-1")
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}: {body}")
        return body["items"]


def step(report: dict, name: str, ok: bool, detail=""):
    report["steps"].append({"step": name, "ok": ok, "detail": detail})
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    return ok


def write_test(api: Mealie, report: dict, tags: list, foods: list, units: list):
    name = f"zz pipeline test {int(time.time())}"
    status, slug = api.request("POST", "/api/recipes", {"name": name})
    if not step(report, "create recipe", status == 201, f"status {status}, slug {slug}"):
        return

    try:
        food = next((f for f in foods if f["name"].lower() in ("onion", "onions")), foods[0] if foods else None)
        unit = next((u for u in units if u["name"].lower() in ("cup", "cups")), units[0] if units else None)
        ingredient = {
            "quantity": 2,
            "note": "finely chopped",
            "originalText": "2 cups onion, finely chopped",
            "referenceId": "8c1a6f5e-3b0f-4b8a-9d0e-0e6a1f2b3c4d",
        }
        if food:
            ingredient["food"] = {"id": food["id"], "name": food["name"]}
        if unit:
            ingredient["unit"] = {"id": unit["id"], "name": unit["name"]}

        test_url = f"https://example.com/pipeline-test/{slug}"
        patch = {
            "description": "Temporary recipe created by check_mealie.py",
            "recipeServings": 2,
            "recipeIngredient": [ingredient],
            "recipeInstructions": [{"text": "Chop the onion."}],
            "orgURL": test_url,
            "extras": {"item_key": "test:check#1"},
        }
        if tags:
            patch["tags"] = [{"id": tags[0]["id"], "name": tags[0]["name"], "slug": tags[0]["slug"]}]

        status, body = api.request("PATCH", f"/api/recipes/{slug}", patch)
        step(report, "patch recipe (ingredients, steps, tags, orgURL, extras)", status == 200,
             f"status {status}" + ("" if status == 200 else f": {body}"))

        status, recipe = api.request("GET", f"/api/recipes/{slug}")
        if step(report, "read back recipe", status == 200, f"status {status}"):
            ing = (recipe.get("recipeIngredient") or [{}])[0]
            step(report, "ingredient food linked", not food or (ing.get("food") or {}).get("id") == food["id"],
                 f"food={(ing.get('food') or {}).get('name')}, unit={(ing.get('unit') or {}).get('name')}, "
                 f"qty={ing.get('quantity')}, display={ing.get('display')!r}")
            step(report, "tag saved", not tags or len(recipe.get("tags") or []) == 1,
                 f"tags={[t['name'] for t in recipe.get('tags') or []]}")
            step(report, "orgURL and extras saved",
                 recipe.get("orgURL") == test_url and (recipe.get("extras") or {}).get("item_key") == "test:check#1",
                 f"orgURL={recipe.get('orgURL')}, extras={recipe.get('extras')}")

        q = urllib.parse.quote(f'org_url="{test_url}"')
        status, body = api.request("GET", f"/api/recipes?queryFilter={q}")
        found = status == 200 and any(r["slug"] == slug for r in body.get("items", []))
        step(report, "find recipe by org_url filter (idempotency)", found, f"status {status}")
    finally:
        status, _ = api.request("DELETE", f"/api/recipes/{slug}")
        step(report, "delete test recipe", status == 200, f"status {status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("MEALIE_URL", "http://mealie.taildce5a6.ts.net:9000"))
    parser.add_argument("--write-test", action="store_true", help="create, verify and delete a test recipe")
    args = parser.parse_args()

    report = {"url": args.url, "steps": []}
    api = Mealie(args.url, None)

    try:
        status, about = api.request("GET", "/api/app/about", auth=False)
    except urllib.error.URLError as e:
        step(report, "reach Mealie", False, f"{e.reason}. Is Tailscale connected on this machine?")
        return finish(report)
    if not step(report, "reach Mealie", status == 200, f"version {about.get('version') if status == 200 else status}"):
        return finish(report)
    report["version"] = about.get("version")

    api.token = os.environ.get("MEALIE_TOKEN") or getpass.getpass("Mealie API token (input hidden): ").strip()
    status, me = api.request("GET", "/api/users/self")
    if not step(report, "API token works", status == 200,
                f"user {me.get('username')}, group {me.get('group')}, household {me.get('household')}, admin {me.get('admin')}"
                if status == 200 else f"status {status}: {me}"):
        return finish(report)

    tags = api.get_all("/api/organizers/tags")
    categories = api.get_all("/api/organizers/categories")
    foods = api.get_all("/api/foods")
    units = api.get_all("/api/units")
    status, recipes = api.request("GET", "/api/recipes?perPage=1")
    report["counts"] = {
        "recipes": recipes.get("total") if status == 200 else None,
        "tags": len(tags), "categories": len(categories), "foods": len(foods), "units": len(units),
    }
    report["tag_names"] = sorted(t["name"] for t in tags)
    report["unit_names"] = sorted(u["name"] for u in units)
    step(report, "read tags, categories, foods, units", True, json.dumps(report["counts"]))
    step(report, "at least one tag exists", bool(tags), "the pipeline needs existing tags to choose from")

    if args.write_test:
        write_test(api, report, tags, foods, units)

    return finish(report)


def finish(report: dict) -> int:
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    ok = all(s["ok"] for s in report["steps"])
    print(f"\n{'All checks passed' if ok else 'Some checks failed'}. Report: {REPORT_FILE} (no token inside)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
