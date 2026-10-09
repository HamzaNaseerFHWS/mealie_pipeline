# 04: How does the pipeline get into private Saved Lists?

Type: grilling
Status: resolved
Blocked by: none

## Question

Saved lists are private. Browser automation on the user's account, official data exports, or something else?

## Answer

A logged-in **Chrome** session driven by Playwright with a **separate pipeline profile**. The user logs in once per platform by hand, and cookies are exported to `cookies.txt` for yt-dlp. Data exports are only a fallback. Human-paced scrolling; stop on checkpoint/captcha. Recorded as `docs/adr/0005-separate-chrome-profile-for-logins.md`.
