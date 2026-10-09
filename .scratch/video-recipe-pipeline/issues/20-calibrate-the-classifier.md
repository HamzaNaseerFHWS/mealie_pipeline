# 20: Calibrate the classifier on the pilot list

**What to build:** Measure and tune classification before the full run.
1. A labelling command `mp classify sample --n 50` picks a random stratified sample and records the user's true labels in a CSV.
2. `mp classify eval` prints precision and recall per label against those labels, plus a confusion matrix.
3. The agent tunes the rules in `classify_rules.yaml`, the prompt and the threshold until `recipe`/`recipe_partial` reach ≥ 95 % precision and ≥ 95 % recall on the sample. The final numbers and settings are recorded in Comments.

The commands are AFK work; the labelling and sign-off need the user.

**Blocked by:** 05, 19

**Status:** ready-for-human

- [ ] `mp classify sample` and `mp classify eval` are implemented and tested at the pipeline seam with fixture labels. The eval numbers in the test are hand-computed from the fixture.
- [ ] The user labels the 50 items (with the agent's help in the terminal).
- [ ] Tuning changes live only in config/prompt files. Before and after numbers are recorded in Comments.
- [ ] The user signs off on the final numbers.
