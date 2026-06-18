"""
gen_raw_fireblocks — crypto custody (Fireblocks API style).

Schema: raw_fireblocks
Tables: supported_assets (lookup), vault_accounts, vault_transactions.

Fireblocks quirks reproduced:
  * camelCase column names (assetId, createdAt, customerRefId).
  * createdAt / lastUpdated as epoch MILLISECONDS (bigint).
  * vault_accounts.createdAt as ISO-Z STRING.
  * amount / netAmount / fee as decimal STRINGS (Fireblocks returns strings).
  * customerRefId is the dirty cross-source join key (CUS_...), often null.

Idempotent: ensure schema -> apply DDL -> truncate -> load.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from common import (
    N, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null,
    ts_isoz, ts_epoch_ms, STABLECOINS,
)

DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_fireblocks.sql"
SCHEMA = "raw_fireblocks"

CHAINS = {"ethereum": "ETH", "polygon": "MATIC", "solana": "SOL"}

SUPPORTED_ASSETS = [
    ("USDC",       "USD Coin",     "ERC20",      "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "ETH",   6),
    ("USDC_POLYGON", "USD Coin (Polygon)", "ERC20", "0x2791bca1f2de4661ed88a30c99a7a9449aa84174", "MATIC", 6),
    ("USDT",       "Tether USD",   "ERC20",      "0xdac17f958d2ee523a2206206994597c13d831ec7", "ETH",   6),
    ("PYUSD",      "PayPal USD",   "ERC20",      "0x6c3ea9036406852006290770bedfcaba0e23a0e8", "ETH",   6),
    ("USDC_SOL",   "USD Coin (Solana)", "SPL",   "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "SOL", 6),
    ("ETH",        "Ethereum",     "BASE_ASSET", None, "ETH",   18),
    ("MATIC",      "Polygon",      "BASE_ASSET", None, "MATIC", 18),
    ("SOL",        "Solana",       "BASE_ASSET", None, "SOL",   9),
]
CUSTODY_STABLES = ["USDC", "USDC_POLYGON", "USDT", "PYUSD", "USDC_SOL"]
N_VAULTS = 60  # treasury vaults + customer-segregated vaults


def hex_address(r):
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(40))


def sol_address(r):
    b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(r.choice(b58) for _ in range(44))


def tx_hash(r, chain):
    if chain == "SOL":
        return sol_address(r) + sol_address(r)[:44]
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(64))


def addr_for(r, asset):
    return sol_address(r) if asset.endswith("SOL") else hex_address(r)


def gen_assets():
    for a in SUPPORTED_ASSETS:
        yield a


def build_vaults():
    """Return (rows, vault_ids list of (id, primary_asset))."""
    rows = []
    vault_ids = []
    cust = customer_master()
    r = rng("fb", "vaults")
    chosen = r.sample(range(N["customers"]), min(N_VAULTS - 6, N["customers"]))

    # 6 treasury vaults (no customer ref).
    for i in range(6):
        vr = rng("fb", "vault", i)
        asset = vr.choice(CUSTODY_STABLES)
        created = rand_datetime(vr, start=dt.date(2021, 1, 1))
        rows.append((
            str(1000 + i), f"NALA Treasury {asset} #{i}", asset, None,
            False, vr.random() < 0.3, addr_for(vr, asset),
            ts_isoz(created),
            json.dumps({"vaultType": "treasury", "assetId": asset}),
        ))
        vault_ids.append((str(1000 + i), asset))

    # Customer-segregated vaults.
    vid = 2000
    for cid in chosen:
        c = cust[cid]
        vr = rng("fb", "custvault", cid)
        asset = vr.choice(CUSTODY_STABLES)
        created = rand_datetime(vr, start=dt.date(2022, 1, 1))
        rows.append((
            str(vid), f"Customer Vault {c.code}", asset,
            maybe_null(c.code, 0.15, vr),   # ~15% missing the customer ref (dirty)
            vr.random() < 0.1, vr.random() < 0.2, addr_for(vr, asset),
            ts_isoz(created),
            json.dumps({"vaultType": "customer", "customerRefId": c.code}),
        ))
        vault_ids.append((str(vid), asset))
        vid += 1

    return rows, vault_ids


def gen_vault_txns(vault_ids):
    """FACT-ish: scaled to a fraction of transfers (treasury moves are fewer)."""
    n_target = max(200, N["transfers"] // 12)
    cust = customer_master()
    for i in range(n_target):
        r = rng("fb", "vtx", i)
        src_asset = r.choice(CUSTODY_STABLES)
        chain = {"USDC": "ETH", "USDC_POLYGON": "MATIC", "USDT": "ETH",
                 "PYUSD": "ETH", "USDC_SOL": "SOL"}[src_asset]
        source_id, _ = r.choice(vault_ids)
        external = r.random() < 0.35
        dest_id = None if external else r.choice(vault_ids)[0]
        amount = round(r.uniform(10, 500_000), 6)
        fee = round(r.uniform(0.5, 40), 6)
        net = round(amount - fee, 6)
        op = r.choices(["TRANSFER", "MINT", "BURN", "TYPED_MESSAGE"],
                       weights=[88, 4, 4, 4])[0]
        status = r.choices(["COMPLETED", "SUBMITTED", "FAILED", "CANCELLED"],
                           weights=[90, 4, 4, 2])[0]
        created = rand_datetime(r, start=dt.date(2022, 1, 1))
        last_upd = created + dt.timedelta(minutes=r.randint(1, 120))
        # customerRefId: dirty join key, mostly null on treasury-internal moves.
        cref = None
        if r.random() < 0.4:
            cref = cust[r.randrange(N["customers"])].code
        # referenceId: internal transfer/settlement link
        ref = None
        if r.random() < 0.5:
            ref = det_uuid(("settlement", r.randrange(max(1, N["transfers"] // 50))))
        yield (
            det_uuid(("fb_tx", i)), src_asset, source_id, dest_id,
            addr_for(r, src_asset),
            addr_for(r, src_asset) if external else None,
            f"{amount:.6f}",
            round(amount, 4),    # amountUSD (stables ~= USD)
            f"{net:.6f}", f"{fee:.6f}", chain,
            tx_hash(r, chain) if status == "COMPLETED" else None,
            op, status,
            maybe_null("CONFIRMED" if status == "COMPLETED" else "PENDING_SIGNATURE", 0.3, r),
            ts_epoch_ms(created), ts_epoch_ms(last_upd),
            cref, ref,
            json.dumps({"operation": op, "assetId": src_asset}),
        )


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn,
             f"{SCHEMA}.vault_transactions",
             f"{SCHEMA}.vault_accounts",
             f"{SCHEMA}.supported_assets")

    bulk_copy(conn, f"{SCHEMA}.supported_assets",
              ["asset_id", "name", "type", "contract_address", "native_asset", "decimals"],
              gen_assets())

    vault_rows, vault_ids = build_vaults()
    bulk_copy(conn, f"{SCHEMA}.vault_accounts",
              ["id", "name", "assetId", "customerRefId", "hiddenOnUI", "autoFuel",
               "address", "createdAt", "raw_payload"], vault_rows)

    n = bulk_copy(conn, f"{SCHEMA}.vault_transactions",
              ["id", "assetId", "sourceId", "destinationId", "sourceAddress",
               "destAddress", "amount", "amountUSD", "netAmount", "fee",
               "feeCurrency", "txHash", "operation", "status", "subStatus",
               "createdAt", "lastUpdated", "customerRefId", "referenceId",
               "raw_payload"], gen_vault_txns(vault_ids))

    print(f"[{SCHEMA}] supported_assets={len(SUPPORTED_ASSETS)} "
          f"vault_accounts={len(vault_rows)} vault_transactions={n}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
