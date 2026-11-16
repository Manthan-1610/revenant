---
inclusion: fileMatch
fileMatchPattern: ["revenant/reanimate/**", "tests/reanimate/**", ".kiro/specs/reanimate/**"]
---

# Kiro CLI headless (Reanimate stage)

- Invoke `kiro-cli chat --v3 --no-interactive --trust-tools=<comma-separated V3 tool IDs>`
  with a narrowly scoped tool list.
- Always name the harness (`--v3`). `--trust-tools` accepts different tool names in V2 and
  V3, and a headless run that names no harness defaults to V2.
- Read `KIRO_API_KEY` from the environment. Never commit it.
- Check flags against https://kiro.dev/docs/cli/headless/ before relying on them.
