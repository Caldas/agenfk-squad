<!-- Base branch: beta. A pull request against main will be asked to change its base; main only takes releases (see docs/releasing.md). -->

## What changes

<!-- One or two sentences. Which agent, skill, hook rule or doc, and why. -->

## Evidence

<!-- What you measured or ran. For a watcher rule: the session behaviour that motivated it (numbers, not impressions). -->

- [ ] The base branch is `beta` (`main` only for a release or a hotfix)
- [ ] `python3 tests/test_watch.py` passes
- [ ] A hook change comes with a test that fails without it
- [ ] A new or changed denial tells the session how the work continues
- [ ] New environment variables are listed in `docs/configuration.md`
- [ ] No private paths, project names or session ids in the diff
