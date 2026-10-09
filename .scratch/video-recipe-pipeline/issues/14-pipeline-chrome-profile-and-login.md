# 14: `mp login`: one pipeline Chrome profile, cookies for yt-dlp, private YouTube lists

**What to build:**
- **Browser adapter:** a persistent Playwright context using real Chrome (`channel="chrome"`) on its own profile under `secrets/browser_profile/`.
- **Login:** `mp login youtube|instagram|facebook` opens a visible window at the platform's login page and waits until the user is logged in (it detects a logged-in marker, or the user presses Enter in the terminal). It then exports the profile's cookies to `secrets/cookies.txt` (Netscape format) for yt-dlp.
- **Doctor:** `mp doctor` shows per platform whether a session exists and how old the cookies are.
- **Private YouTube lists:** Watch Later (`list=WL`), Liked (`list=LL`) and private playlists now collect through yt-dlp with the cookies.
- **Stop signals:** the adapter detects login walls, checkpoint/challenge pages and rate-limit pages and raises `NeedsHumanLogin`. The run stops that platform with a clear message and never tries to get around it.

**Blocked by:** 04

**Status:** ready-for-agent

**Read first:** `docs/adr/0005`; `PIPELINE_SPEC.md` §3.1 "Login and session handling".

- [ ] The profile directory and `cookies.txt` are git-ignored and never logged. A doctor test confirms that cookie values never appear in output.
- [ ] The cookie export is pure (Playwright cookie dicts → Netscape lines, incl. `#HttpOnly_` prefix and expiry) and table-tested.
- [ ] Stop-signal detection is pure (URL/title/body markers per platform from config) and table-tested with saved HTML snippets.
- [ ] The YouTube collector passes `cookiefile` when cookies exist. The ticket 04 test for private lists now passes when a cookie file is present (fake) and still gives the login hint when it's absent.
- [ ] The Browser adapter is thin and verified manually. Tests use a fake browser.

**Manual check on the laptop (user):** `uv run mp login youtube` (log in), then `uv run mp lists add "https://www.youtube.com/playlist?list=WL"` and `uv run mp sync`. Watch Later items should appear in `mp lists`.
