# mealie_pipeline

A personal pipeline that turns the user's **saved video lists** (YouTube playlists, Instagram saved "All posts", Facebook saved items) into clean recipes in a self-hosted **Mealie** instance. For each video it collects the URL, classifies it (recipe or not), scrapes the linked website, transcribes when needed, extracts the recipe with evidence, parses ingredients into Mealie foods and units, tags it, verifies it, and uploads it. Videos with several recipes produce several independent Mealie recipes.

- **Spec (source of truth for the build):** `.scratch/video-recipe-pipeline/spec.md`
- **Implementation tickets:** `.scratch/video-recipe-pipeline/issues/NN-*.md`, worked in number order on the frontier (see below)
- **Planning map (open decisions, HITL tasks):** `.scratch/wayfinder-video-recipes/map.md`
- **Design reference (research, API details, rationale):** `PIPELINE_SPEC.md`. When a ticket and this document disagree, the ticket and spec win.
- **Domain language:** `GLOSSARY.md`. **Decisions:** `docs/adr/`.

## Environment facts (do not re-decide these)

- Runs on the user's **Windows** laptop: native Python 3.12 (not WSL), NVIDIA **GTX 1650 (4 GB)**, Chrome.
- Mealie runs on **another PC** reached over Tailscale at `http://mealie.taildce5a6.ts.net:9000`. Nothing of Mealie's own import, scraper, AI or ingredient parser is used. Mealie is storage plus tag/food/unit lookup only.
- AI calls go through the **Claude Code CLI** (`claude -p`) on the user's **Claude Pro** subscription. There is no Anthropic API key. Never use `--bare` (it ignores the subscription login). OpenAI is an emergency fallback only, off unless `--allow-openai` is passed, with a hard spend cap.
- Transcription is local `faster-whisper` on the GPU.
- Cloud/agent sessions usually **cannot reach** the Mealie PC, the user's browser logins or the GPU. Everything must be testable with the fakes described in the spec. Real-environment checks are listed as manual verification steps in each ticket, for the user to run on the laptop.

## Working on a ticket

1. Pick the ticket: the lowest-numbered file in `.scratch/video-recipe-pipeline/issues/` whose `Status:` is `ready-for-agent` and whose blockers are all finished. A blocker is finished when its implementation ticket is `done`, or its wayfinder ticket (`.scratch/wayfinder-video-recipes/issues/`) is `resolved`. Set the ticket's `Status:` to `in-progress` and commit that change first, so parallel sessions skip it. If a wayfinder blocker isn't resolved, stop and say so; don't guess its answer.
2. Run `/implement` with the ticket path. Follow `/tdd` at the seams listed in the spec's *Testing Decisions*. Don't invent new seams.
3. Before finishing: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` (or mypy if the ticket set that up), `uv run pytest`. All must pass.
4. Append a `## Comments` section to the ticket with what was built, anything deferred, and the manual verification steps for the user. Set `Status: done`. Commit.
5. One ticket per session. Don't start the next ticket in the same session.

Never weaken, skip or delete a test to get green. Never commit secrets: `.env`, `cookies.txt`, `secrets/`, `data/` and `work/` are git-ignored.

## Agent skills

### Issue tracker

Local markdown under `.scratch/`: one folder per effort, one file per ticket. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line. Ticket progress also uses `in-progress` and `done`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

Skills are vendored from [mattpocock/skills](https://github.com/mattpocock/skills) (MIT) under `.claude/skills/`. See `.claude/skills/VENDORED.md`.
