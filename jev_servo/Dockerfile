# Glama / MCP registry image: answers initialize + tools/list over stdio
# without requiring the local console, USB arm, or camera.
FROM python:3.12-slim-bookworm

WORKDIR /app

# Only the MCP stdio server is needed for introspection. Tool calls that
# need hardware will error cleanly when JEV_MCP_NO_SPAWN=1 and no console.
COPY jev_servo/ /app/jev_servo/

ENV PYTHONUNBUFFERED=1 \
    JEV_MCP_NO_SPAWN=1 \
    JEV_CONSOLE_URL=http://127.0.0.1:8765

# Run the stdio server directly (stdlib only for initialize / tools/list).
CMD ["python", "-u", "/app/jev_servo/mcp_server.py"]
