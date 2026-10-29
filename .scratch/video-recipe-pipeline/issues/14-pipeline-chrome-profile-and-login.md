# 14: `mp login`: one pipeline Chrome profile, cookies for yt-dlp, private YouTube lists

**What to build:**
- **Browser adapter:** a persistent Playwright context using real Chrome (`channel="chrome"`) on its own profile under `secrets/browser_profile/`.
- **Login:** `mp login youtube|instagram|facebook` opens a visible window at the platform's login page and waits until the user is logged in (it detects a logged-in marker, or the user presses Enter in the terminal). It then exports the profile's cookies to `secrets/cookies.txt` (Netscape format) for yt-dlp.
- **Doctor:** `mp doctor` shows per platform whether a session exists and how old the cookies are.
- **Private YouTube lists:** Watch Later (`list=WL`), Liked (`list=LL`) and private playlists now collect through yt-dlp with the cookies.
- **Stop signals:** the adapter detects login walls, checkpoint/challenge pages and rate-limit pages and raises `NeedsHumanLogin`. The run stops that platform with a clear message and never tries to get around it.

**Blocked by:** 04

**Status:** done

**Read first:** `docs/adr/0005`; `PIPELINE_SPEC.md` §3.1 "Login and session handling".

- [x] The profile directory and `cookies.txt` are git-ignored and never logged. A doctor test confirms that cookie values never appear in output.
- [x] The cookie export is pure (Playwright cookie dicts → Netscape lines, incl. `#HttpOnly_` prefix and expiry) and table-tested.
- [x] Stop-signal detection is pure (URL/title/body markers per platform from config) and table-tested with saved HTML snippets.
- [x] The YouTube collector passes `cookiefile` when cookies exist. The ticket 04 test for private lists now passes when a cookie file is present (fake) and still gives the login hint when it's absent.
- [x] The Browser adapter is thin and verified manually. Tests use a fake browser.

**Manual check on the laptop (user):** `uv run mp login youtube` (log in), then `uv run mp lists add "https://www.youtube.com/playlist?list=WL"` and `uv run mp sync`. Watch Later items should appear in `mp lists`.

## Comments

**Built**
- `mp login youtube|instagram|facebook` (`login.py`): opens the platform's login page in the pipeline's own Chrome profile (`secrets/browser_profile/`), polls every 2 s for the platform's session cookies, and stops waiting when they appear, when you press Enter, or after 15 min. It then exports every cookie of the profile to `secrets/cookies.txt` (Netscape format, one file for all platforms) and records the login time in `secrets/logins.json`. It prints only counts, never values.
- `sessions.py` (pure): `to_netscape` / `parse_netscape` (`#HttpOnly_` prefix; session cookies get expiry 0), `has_session` (all session cookies present on the platform domain and not expired), `session_statuses` (per platform: logged in, age, days until the session cookie expires), `stop_signal` (URL/title/body markers → `checkpoint`, `rate_limit` or `login_wall`, most specific first).
- `config/platforms.yaml`: login URL, cookie domain, session cookie names (`SID` / `sessionid` / `c_user` + `xs`) and stop-signal markers per platform. Edit the markers there when a platform changes its pages.
- `Browser` port (`adapters/browser.py`): `PlaywrightBrowser`, real Chrome via `channel="chrome"` on a persistent context, plus `show`, `cookies`, `open` and `close`. `open` raises `NeedsHumanLogin` on a stop signal or HTTP 429. `FakeBrowser` for tests.
- `mp doctor` shows one line per platform: `logged in N days ago, cookies expire in M days`, or a WARN with the `mp login` hint. It never fails the doctor (only private lists need it).
- The YouTube collector passes `secrets/cookies.txt` to yt-dlp (`cookiefile`) when the file exists. WL/LL/private playlists then collect. Without the file they still fail with the `mp login youtube` hint.
- `mp sync` turns `NeedsHumanLogin` into a per-list failure: "stopped on a checkpoint page … Run `mp login youtube`". It never retries around it.
- Smoke-tested the real `PlaywrightBrowser` headless on a throwaway profile on this laptop: Chrome launched, a page opened, the real Instagram login page was detected as `login_wall`, and cookies read back.

**Deferred**
- `metadata` (per-Video yt-dlp) doesn't use the cookie file yet. Private or members-only Videos inside Watch Later may fail at that stage. The fix is small (pass `cookiefile` in `YtDlpVideoSource.metadata`), but it wasn't in this ticket's scope.
- Response listening and `fetch_rendered` on the Browser come with tickets 15/16/17, which need them. The adapter has `open` only.
- No bot-detection workarounds: if Google refuses to sign in inside the automated Chrome window ("This browser or app may not be secure"), that's reported, not worked around (ADR 0005).

**Manual check on the laptop (user)**
1. `uv run mp login youtube`: a Chrome window opens on Google sign-in. Log in. The terminal should say `logged in to youtube; exported N cookies to secrets\cookies.txt` by itself within a few seconds.
2. `uv run mp doctor`: `youtube session: logged in today, cookies expire in … days`.
3. `uv run mp lists add "https://www.youtube.com/playlist?list=WL"`, then `uv run mp sync`. Watch Later items appear and `uv run mp lists` shows the count.
4. Optional: `uv run mp login instagram` and `uv run mp login facebook` (needed for tickets 15/16). Doctor should then show all three.
5. If Google blocks the sign-in in step 1, note the exact message and tell me.
