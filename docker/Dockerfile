FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# TODO (Phase 1 blocker to resolve before real deploy): `hermes kanban`
# write-path commands shell out to a `hermes` binary from inside this
# container (see app/kanban_write.py). That means either:
#   (a) install the full Hermes Agent CLI inside this image too, pointed at
#       the same HERMES_HOME as the real gateway (via a shared volume), or
#   (b) replace the subprocess calls with a thin HTTP shim that runs ON the
#       Hermes host and the container calls over the network instead.
# (a) is simpler short-term; (b) is cleaner once this is containerized
# separately from the Hermes host in prod. Decide before Phase 1 sign-off.
# Nothing installs `hermes` here yet — this image will fail on any write
# endpoint until that's resolved.

EXPOSE 8080
ENV PORTAL_BASE_URL=http://localhost:8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
