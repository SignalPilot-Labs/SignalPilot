-- Add auto-generated descriptive name column to runs
ALTER TABLE runs ADD COLUMN IF NOT EXISTS name TEXT;
