-- raw_fireblocks — crypto custody (Fireblocks API style: camelCase-ish ids,
-- ISO-Z timestamps as text, amounts as strings in some payload fields). NALA
-- uses Fireblocks vaults to custody stablecoin (USDC/USDT/PYUSD) treasury.
CREATE SCHEMA IF NOT EXISTS raw_fireblocks;

-- Lookup: supported assets in the Fireblocks workspace.
CREATE TABLE IF NOT EXISTS raw_fireblocks.supported_assets (
    asset_id          text PRIMARY KEY,       -- USDC / USDT / PYUSD / ETH / MATIC / SOL
    name              text NOT NULL,
    type              text NOT NULL,          -- BASE_ASSET / ERC20 / SPL
    contract_address  text,                   -- token contract (PII-ish; on-chain)
    native_asset      text,                   -- ETH / MATIC / SOL
    decimals          integer NOT NULL
);

-- Vault accounts (a logical custody container, may hold many assets).
CREATE TABLE IF NOT EXISTS raw_fireblocks.vault_accounts (
    id                text PRIMARY KEY,       -- fireblocks vault account id (numeric-as-string)
    name              text NOT NULL,
    "assetId"         text,                   -- primary asset (fireblocks camelCase)
    "customerRefId"   text,                   -- CUS_... when a customer-segregated vault, else null
    "hiddenOnUI"      boolean DEFAULT false,
    "autoFuel"        boolean DEFAULT false,
    address           text,                   -- deposit address (PII)
    "createdAt"       text NOT NULL,          -- ISO-Z string
    raw_payload       jsonb
);

-- Vault transactions (on-chain or internal Fireblocks transfers).
CREATE TABLE IF NOT EXISTS raw_fireblocks.vault_transactions (
    id                text PRIMARY KEY,       -- fireblocks tx id (uuid-ish)
    "assetId"         text NOT NULL,          -- USDC / USDT / ...
    "sourceId"        text,                   -- source vault account id
    "destinationId"   text,                   -- dest vault account id (null for external)
    "sourceAddress"   text,                   -- on-chain source address (PII)
    "destAddress"     text,                   -- on-chain destination address (PII)
    amount            text NOT NULL,          -- decimal string (Fireblocks returns strings)
    "amountUSD"       numeric(20,4),
    "netAmount"       text,
    fee               text,                   -- network fee, decimal string
    "feeCurrency"     text,
    "txHash"          text,                   -- on-chain hash (PII-ish)
    "operation"       text NOT NULL,          -- TRANSFER / MINT / BURN / TYPED_MESSAGE
    status            text NOT NULL,          -- COMPLETED / SUBMITTED / FAILED / CANCELLED
    "subStatus"       text,
    "createdAt"       bigint NOT NULL,        -- epoch ms (Fireblocks createdAt is ms)
    "lastUpdated"     bigint,                 -- epoch ms
    "customerRefId"   text,                   -- CUS_... dirty join key, often null
    "referenceId"     text,                   -- internal ref: transfer uuid / settlement id
    raw_payload       jsonb
);
