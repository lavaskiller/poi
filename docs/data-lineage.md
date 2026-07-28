# Data lineage: candidate-snapshot registry

The candidate set (MapKit nearby results) is as much a part of a release as the
selector code. The repo already stores each probe as an immutable snapshot:

```
poi-data/generated/
  candidate-snapshots/<snapshot-id>/
      metadata.json          # status, candidate_artifact, candidate_artifact_sha256
      mapkit_candidates.jsonl
  active-mapkit-candidate-snapshot.json   # the active pointer match_score verifies
```

`match_score.active_mapkit_candidate_file()` reads the pointer fail-loud: it
re-hashes the artifact against `metadata.candidate_artifact_sha256` and raises if
anything is incomplete or tampered.

`tools/snapshot_registry.py` adds the lineage/rollback layer on top:

| command | effect |
|---|---|
| `scan` | list snapshot ids on disk |
| `register [--snapshot-id ID]` | add snapshot(s) to `snapshot-registry.json` (content hash + records); skips any whose artifact hash ≠ metadata |
| `inspect ID` | validate one snapshot (complete + hash matches) |
| `current` | show the active pointer |
| `promote ID --reason ...` | **atomically** switch the active pointer after verifying the snapshot, and append an audit record (previous → new, content hash, actor, reason) to `snapshot-registry.audit.jsonl` |
| `history` | print the append-only promotion log |
| `rollback --reason ...` | restore the previously-active snapshot from the log |

Key properties:

- **Content-addressed** — every registry entry carries the artifact SHA-256, so
  a snapshot is identified by *what it contains*, not just its id.
- **Verified promotion** — `promote` refuses a snapshot whose artifact hash does
  not match its metadata, and only ever writes the exact pointer format
  `match_score` consumes. An unusable snapshot can never become active.
- **Audited + reversible** — every switch is logged with who/when/from-what/why,
  and `rollback` is one command.

The registry index and audit log live under the gitignored `poi-data/generated/`
tree with the data they describe (never committed). What *is* reproducible and
tracked is the mechanism here plus the frozen split policy
(`docs/release-gate.md`) — together they make "which candidates + which split +
which code" a single, versioned release identity, per the target architecture in
`docs/mlops-review-2026-03-28.md`.
