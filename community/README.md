# Community skill packs

A skill pack is a JSONL file with one command per line. Drop one into
`community/`, and users can install it with:

```bash
./.venv/bin/lever-runner-import community/<pack>.jsonl
# or, with the Makefile:
make install-pack PACK=k8s-ops
```

## Format

Each line is a JSON object:

```json
{"intent_phrase": "list running pods", "command": "kubectl get pods"}
```

Optional fields override the default trust score (50):

```json
{"intent_phrase": "rollback a deployment",
 "command": "kubectl rollout undo",
 "trust_score": 60}
```

Embeddings are **not** stored in the export — `lever-runner-import`
re-encodes on the receiving machine. This keeps the file small and
the export portable across machines with different embedding models.

## Available packs

| Pack | Description |
|---|---|
| [k8s-ops.jsonl](k8s-ops.jsonl) | Kubernetes day-to-day operations: pods, services, logs, deployments, rollouts. *Demo pack — do not install on a host without `kubectl` configured.* |

## Authoring a pack

1. Write one `{intent_phrase, command}` per line. Aim for 3–8 word
   intents phrased the way a real user would type them.
2. Test: `make install-pack PACK=my-pack` then `/do` a few queries
   from your phone to make sure cosine similarity lands correctly.
3. Adjust phrasing until the matches are right. If a phrase is
   matching the wrong command, rephrase to disambiguate.
4. Submit a PR adding `community/<pack>.jsonl` to this repo, or
   keep it as a gist and link it from your own README.

## Exporting your own pack

```bash
./.venv/bin/lever-runner-export --include-stats > my-pack.jsonl
# or, with the Makefile:
make export > my-pack.jsonl
```

The `--include-stats` flag embeds the current trust score, success
count, and failure count for each row. Re-importing preserves these,
which is useful for migrating a curated table between machines.
