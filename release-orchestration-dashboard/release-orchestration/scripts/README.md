# Scripts — Phase 3

Custom scripts live here. Each script must implement the bag-in / result-out contract
defined in `05-integration-and-triggers.md` §1.3.

**Input (stdin or function argument):**
```json
{
  "lane":         { "market": "HK", "package": "pkg-001", "jira_id": "PROJ-1" },
  "bag":          { "cr_no": "CR001", "build_url": "https://..." },
  "creds":        { "jenkins": { "token": "..." } },
  "market_config":{ "urls": { "build_url": "..." }, "portal": { ... } }
}
```

**Required output (stdout or return value):**
```json
{
  "status":   "SUCCESS",
  "produced": { "g3_url": "https://..." },
  "links":    [ { "label": "G3 job", "url": "https://..." } ],
  "message":  "Optional description for audit"
}
```

Rules:
- One generic script per *procedure* — never one per market.
- Read market-specific selectors/tabs/sub-links from `market_config`, not hardcoded.
- Never log raw credentials.
- Scripts run with a timeout enforced by the engine.
- Phase 3 only — no scripts are executed in Phase 1 or Phase 2.
