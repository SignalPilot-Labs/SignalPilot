#!/bin/bash
exec npx @playwright/mcp@latest --headless --no-sandbox "$@"
