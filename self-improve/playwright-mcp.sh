#!/bin/bash
exec node /usr/lib/node_modules/@playwright/mcp/cli.js --headless --no-sandbox --browser chromium "$@"
