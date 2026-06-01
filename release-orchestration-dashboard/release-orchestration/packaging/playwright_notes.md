# Playwright — packaging notes

**Status: excluded from Phase 1 and Phase 2 packaging.**

The `browser` trigger type is a Phase 3 feature. When it is ready, choose one of:

1. **Bundle browser binaries** — add `playwright install chromium` output to PyInstaller
   `datas`. Results in a large exe (~200 MB+) but is fully self-contained.

2. **Download on first run** — ship without browsers; on first launch detect if Playwright
   is needed and call `playwright install chromium`. Requires internet on first run.

3. **Exclude entirely** — if no browser triggers are needed for the target deployment,
   remove the `browser_executor` from the registry and document that browser steps
   require a separate installation step.

Decision deferred to Phase 3 (spec §06.6 open decision).
