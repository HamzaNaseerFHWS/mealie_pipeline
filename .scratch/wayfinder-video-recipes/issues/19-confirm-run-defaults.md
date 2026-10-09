# 19: Confirm run defaults before the full run

Type: grilling
Status: open
Blocked by: 13, 20
Mode: HITL

## Question

Are these defaults right for the full run over every Saved List? Each one is a config switch already built in.

1. Auto-create missing English Foods and Units in Mealie, logged to CSV. (Default: yes)
2. Tags only (no categories or tools). The pipeline creates exactly one tag of its own, `To Review`. New tag ideas go to `suggested_tags.csv`. (Default: yes)
3. Recipes already in Mealie from a previous run: skip (`--mode skip`). (Default: skip)
4. Image: website image, else the Recipe Part's start frame, else the thumbnail. (Default: yes)
5. Quality Score: ≥ 80 upload, 60–79 upload with `To Review`, < 60 Review Queue only. (Default: yes)
6. Which of the user's existing tags should rule-based tagging map to (vegetarian, quick, cuisine, drinks…)? This needs the tag list from ticket 13. Propose a mapping, then confirm.

Auto Sync, after the full run (spec module 17, tickets 23 and 24):

7. Schedule: run an Auto Sync Cycle every 6 h while you're logged on to the laptop, catching up after sleep, and never waking it. (Default: yes. Or fixed times, for example 08:00 and 20:00?)
8. Check intervals per platform: YouTube every 6 h, Instagram and Facebook at most once every 24 h, stopping after 10 already-known Videos. (Default: yes)
9. At most 30 new Videos processed per cycle, and AI calls still limited to your `--window`. (Default: yes, with the same window as the full run)
10. Notifications: a Windows toast when recipes were uploaded, a login is needed, a recipe went to the Review Queue, or Mealie has been unreachable for 2 or more cycles in a row. (Default: all on)

Resolve with `/grilling` in a live session with the user. Never answer on the user's behalf.

## Answer

_pending_
