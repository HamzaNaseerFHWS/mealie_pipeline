# 12: Where does everything run?

Type: task
Status: resolved
Blocked by: none

## Question

Which machine runs the pipeline, and how does it reach Mealie?

## Answer

The pipeline runs on the user's **Windows** laptop (native Python, GTX 1650, Chrome). Mealie runs on another PC on the user's Tailscale network at `http://mealie.taildce5a6.ts.net:9000`. Cloud agent sessions cannot reach it, so all code must be testable with fakes, and real-environment checks are run by the user on the laptop.
