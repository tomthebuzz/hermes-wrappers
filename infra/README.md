# K8s deployment — Team Portal

```
kubectl apply -k infra/base/
```

## Before you apply this for real

1. **kanban.db access is resolved for writes, same as it ever was for
   reads.** Reads: bind-mounted file (Option C from the original note,
   now just "the normal way" since there's no cluster scheduling
   ambiguity on a single Docker host — this still applies in K8s too via
   a PVC, see cronjob manifests in hermes-team-bots for the mirror of
   this). Writes: route through **hermes-bridge**, a standalone service
   running natively next to the real Hermes install — this container
   execs nothing, it just calls the bridge over HTTP. See
   `../hermes-bridge/README.md`.

2. **Build and push a real image** — `deployment.yaml` points at a
   placeholder `ghcr.io/tomthebuzz/team-portal:latest`. Build from
   `docker/Dockerfile` at the repo root and push to whatever registry your
   cluster can pull from, then update the image reference (or template it
   via `kustomize edit set image`).

3. **Generate real secrets, don't apply the templates verbatim:**
   ```bash
   # session secret
   kubectl create secret generic team-portal-session \
     --from-literal=secret=$(openssl rand -hex 32) -n hermes-team \
     --dry-run=client -o yaml | kubectl apply -f -

   # users.yaml (real Telegram IDs — see repo root's users.yaml.example)
   kubectl create secret generic team-portal-users \
     --from-file=users.yaml=../../users.yaml -n hermes-team \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
   `infra/base/secret-users.example.yaml` is a template to show the shape,
   not something to `kubectl apply` as-is — it has an empty user list.

4. **Ingress is Phase 4 only** — it's deliberately commented out of
   `kustomization.yaml`'s resources list. Don't uncomment it until
   team-portal.example.com's DNS points at this cluster's ingress controller and a
   cert-manager ClusterIssuer actually exists. Until then, reach the
   Service via `kubectl port-forward svc/team-portal 8080:80 -n hermes-team`
   or a tailnet-exposed NodePort.

5. **Shared config drift** — `configMapGenerator` in `kustomization.yaml`
   builds `team-shared-config` from `config/tenants.yaml` +
   `config/sla-defaults.yaml` in THIS repo. The hermes-team-bots repo has
   its own copy of those same two files for its CronJobs. If both land in
   the same cluster/namespace, repoint hermes-team-bots' CronJob infra at
   this same generated ConfigMap name instead of generating a second one —
   see that repo's infra/README.md for the current (flagged) duplication.

## Scaling note

`replicas: 1` is deliberate, not a placeholder forgotten at 1. The
magic-link auth module keeps its pending-token store in process memory
(see `app/auth/magic_link.py`). Scaling to >1 replica today means a login
link issued by one pod can fail verification on another. Fix before
scaling: move that store to Redis (or switch to the Telegram Login Widget
once team-portal.example.com exists, which doesn't need server-side pending state
the same way).
