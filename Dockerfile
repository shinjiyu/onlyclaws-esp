# Glama / MCP registry image: answers initialize + tools/list over stdio
# without requiring the local console, USB arm, or camera.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY jev_servo/ /app/jev_servo/

ENV PYTHONUNBUFFERED=1 \
    JEV_MCP_NO_SPAWN=1 \
    JEV_CONSOLE_URL=http://127.0.0.1:8765

CMD ["python", "-u", "/app/jev_servo/mcp_server.py"]
