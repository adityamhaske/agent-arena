# syntax=docker/dockerfile:1

# The engine is stdlib-only; PyYAML is its one dependency. Provider SDKs stay
# optional at runtime everywhere else in this project, and that continues
# here: pass --build-arg EXTRA=anthropic (or "all") only if you want a real
# provider's SDK baked into the image rather than installed at container
# start against a mounted requirements file.
FROM python:3.12-slim
ARG EXTRA=""
# For an internal mirror, or to build against a pre-release on TestPyPI —
# e.g. --build-arg PIP_INDEX_URL=https://test.pypi.org/simple/. Empty by
# default, which leaves pip's own default index in effect.
ARG PIP_INDEX_URL=""

WORKDIR /data

RUN INDEX_FLAG=""; \
    if [ -n "$PIP_INDEX_URL" ]; then \
      INDEX_FLAG="--index-url $PIP_INDEX_URL --extra-index-url https://pypi.org/simple/"; \
    fi; \
    if [ -n "$EXTRA" ]; then \
      pip install --no-cache-dir $INDEX_FLAG "agent-arena[$EXTRA]"; \
    else \
      pip install --no-cache-dir $INDEX_FLAG agent-arena; \
    fi

# `arena ui` has no authentication by design — see docs/security/ — because it
# is a single-user tool meant for one trusted operator on localhost. Inside a
# container, --host 0.0.0.0 is required for anything outside the container to
# reach it at all, which means anyone who can reach the published port can
# read and edit every mounted project and spend API credit through it. Put
# this behind your own network boundary (an internal Docker network, a
# reverse proxy with its own auth, an SSH tunnel) — never publish the port
# straight to the open internet.
EXPOSE 8420

ENTRYPOINT ["arena"]
# `arena ui` looks for a `projects/` folder under the working directory by
# default, and WORKDIR here is /data — so mount your projects folder to
# exactly /data/projects:
#   docker run -p 8420:8420 -v $(pwd)/projects:/data/projects IMAGE
# Override the command for one-shot CLI use instead of the UI, e.g.
#   docker run -v $(pwd):/data IMAGE evaluate --project projects/my_project
CMD ["ui", "--host", "0.0.0.0", "--no-browser"]
