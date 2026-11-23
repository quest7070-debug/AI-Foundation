# Only a builder for the fixed synthetic OpenCode canary.
# Both FROM values are temporary localhost aliases of inspected local image IDs.
# Upstream OpenCode and the Python runtime both use Alpine/musl.
ARG OPENCODE_LOCAL_REF
ARG PYTHON_LOCAL_REF
FROM ${OPENCODE_LOCAL_REF} AS reviewed_cli
FROM ${PYTHON_LOCAL_REF} AS canary
ARG EXPECTED_CLI_SHA256
COPY --from=reviewed_cli /usr/local/bin/opencode /usr/local/bin/opencode
# Copy only the pinned public upstream runtime libraries; no apk or network.
COPY --from=reviewed_cli /usr/lib/ /usr/lib/
COPY ai_foundation/ /opt/public-canary/ai_foundation/
ENV PYTHONPATH=/opt/public-canary
RUN test "$(sha256sum /usr/local/bin/opencode | cut -d' ' -f1)" = "$EXPECTED_CLI_SHA256" \
    && /usr/local/bin/opencode --version | grep -Eq '^opencode v2\.[0-9]+\.[0-9]+$' \
    && python3 -m compileall -q /opt/public-canary/ai_foundation
# No ENTRYPOINT or runtime user is trusted from this image.
# Host launcher enforces --network=none, read-only FS, nonroot, and no mounts.
