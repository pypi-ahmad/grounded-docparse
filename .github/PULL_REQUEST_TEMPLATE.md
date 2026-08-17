## Summary

What changed and why.

## Public contracts and artifacts affected

List any changed public contract, schema, CLI flag, exported name, or
generated artifact. Write "none" if this PR doesn't touch one.

## Verification

```powershell
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
uv run grounded-docparse ingest --help
git diff --check
```

Paste the actual results, not just the commands. Note any check you could
not run and why.

## Consequences

- Provider cost, retention, or egress consequences: 
- Security or trust-boundary consequences: 
- Compatibility consequences: 
- Residual risks or checks not run: 

## Checklist

- [ ] I opened an issue first for substantial or schema-breaking work (or
      this is a small, self-contained fix).
- [ ] Documentation and `CHANGELOG.md` are updated for any behavior change.
- [ ] Every relative Markdown link I touched resolves, and fenced code
      blocks have a language identifier and closing fence.
- [ ] No API keys, bearer tokens, source documents, crops, local data, or
      raw provider responses are included.
- [ ] Any fixtures I added are synthetic or explicitly redistributable —
      see [DATA_RESPONSIBILITY.md](../DATA_RESPONSIBILITY.md).
- [ ] I have the right to submit this contribution under the [MIT
      License](../LICENSE).
