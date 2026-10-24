FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Shared tenant/SLA config read by app/config_loader.py (SHARED_CONFIG_DIR
# overrides it, e.g. a K8s ConfigMap mount).
COPY config ./config

# TODO (Phase 1 blocker to resolve before real deploy): `hermes kanban`
# write-path commands now route through the hermes-bridge service (see
# app/kanban_write.py and app/auth/magic_link.py — both are dual-mode,
# bridge-first when HERMES_BRIDGE_URL is set). So this container does NOT
# need the `hermes` CLI installed in it anymore for writes. It still reads
# kanban.db directly (bind-mounted below in docker-compose.yml), which is
# unaffected by this change.
#
# Set HERMES_BRIDGE_URL=http://host.docker.internal:8765 and
# HERMES_BRIDGE_API_KEY=<the bridge's key> in docker-compose.yml (already
# done) and this container is fully self-contained — no Hermes install
# needed inside it at all.

EXPOSE 8080
ENV PORTAL_BASE_URL=http://localhost:8080
# PORTAL_HOST/PORTAL_LISTEN_PORT matter with network_mode: host (Linux
# hosters), where 0.0.0.0 would expose the Portal on every host interface;
# bind it to the tailnet IP there. Bridged networking keeps the defaults.
ENV PORTAL_HOST=0.0.0.0 PORTAL_LISTEN_PORT=8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$PORTAL_HOST\" --port \"$PORTAL_LISTEN_PORT\""]
