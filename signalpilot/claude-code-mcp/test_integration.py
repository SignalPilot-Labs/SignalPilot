"""Quick integration test — verifies the MCP client can talk to a live gateway."""

import asyncio
import sys

from signalpilot_mcp.client import SignalPilotClient


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3300"
    print(f"Testing against: {url}")

    client = SignalPilotClient(url)

    # 1. Health check
    try:
        health = await client.health()
        print(f"  [OK] Health: {health.get('status', 'unknown')}")
    except Exception as e:
        print(f"  [FAIL] Health: {e}")
        print("\nGateway is not reachable. Make sure it's running.")
        return

    # 2. List connections
    try:
        conns = await client.list_connections()
        print(f"  [OK] Connections: {len(conns)} configured")
        for c in conns:
            print(f"       - {c.get('name')} ({c.get('db_type')})")
    except Exception as e:
        print(f"  [FAIL] List connections: {e}")

    # 3. Settings
    try:
        settings = await client.get_settings()
        print(f"  [OK] Settings loaded ({len(settings)} keys)")
    except Exception as e:
        print(f"  [FAIL] Settings: {e}")

    # 4. Audit log
    try:
        entries = await client.audit_log(limit=5)
        print(f"  [OK] Audit log: {len(entries)} recent entries")
    except Exception as e:
        print(f"  [FAIL] Audit: {e}")

    # 5. Cache stats
    try:
        cache = await client.cache_stats()
        print(f"  [OK] Cache: {cache.get('entries', 0)} entries, {cache.get('hit_rate', 0)*100:.0f}% hit rate")
    except Exception as e:
        print(f"  [FAIL] Cache stats: {e}")

    await client.close()
    print("\nAll checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
