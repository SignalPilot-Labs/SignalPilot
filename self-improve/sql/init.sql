-- Self-Improve Audit Database Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    branch_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    pr_url TEXT,
    total_tool_calls INT DEFAULT 0,
    total_cost_usd DOUBLE PRECISION DEFAULT 0,
    total_input_tokens BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    rate_limit_info JSONB,
    error_message TEXT,
    sdk_session_id TEXT,
    custom_prompt TEXT,
    duration_minutes DOUBLE PRECISION DEFAULT 0,
    base_branch TEXT DEFAULT 'main',
    rate_limit_resets_at BIGINT,
    diff_stats JSONB  -- git diff summary: [{path, added, removed, status}]
);

CREATE TABLE tool_calls (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    phase TEXT NOT NULL CHECK (phase IN ('pre', 'post')),
    tool_name TEXT NOT NULL,
    input_data JSONB,
    output_data JSONB,
    duration_ms INT,
    permitted BOOLEAN NOT NULL DEFAULT TRUE,
    deny_reason TEXT,
    agent_role TEXT NOT NULL DEFAULT 'worker',
    tool_use_id TEXT  -- SDK correlation ID linking pre→post pairs
);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'
);

-- Control signals: pause, resume, inject prompt, stop
CREATE TABLE control_signals (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal TEXT NOT NULL CHECK (signal IN ('pause', 'resume', 'inject', 'stop', 'unlock')),
    payload TEXT,  -- for 'inject': the prompt to send; for 'stop': optional reason
    consumed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_control_signals_run_id ON control_signals(run_id);
CREATE INDEX idx_control_signals_pending ON control_signals(run_id, consumed) WHERE NOT consumed;

-- Notify agent of new control signals
CREATE OR REPLACE FUNCTION notify_control_signal() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('control_signal', json_build_object(
        'id', NEW.id,
        'run_id', NEW.run_id,
        'signal', NEW.signal,
        'payload', NEW.payload
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER control_signal_notify
    AFTER INSERT ON control_signals
    FOR EACH ROW EXECUTE FUNCTION notify_control_signal();

CREATE INDEX idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX idx_tool_calls_ts ON tool_calls(ts);
CREATE INDEX idx_audit_log_run_id ON audit_log(run_id);
CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);

-- Real-time notification trigger for the monitor UI
CREATE OR REPLACE FUNCTION notify_tool_call() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('tool_call_inserted', json_build_object(
        'id', NEW.id,
        'run_id', NEW.run_id,
        'ts', NEW.ts,
        'phase', NEW.phase,
        'tool_name', NEW.tool_name,
        'input_data', NEW.input_data,
        'output_data', NEW.output_data,
        'duration_ms', NEW.duration_ms,
        'permitted', NEW.permitted,
        'deny_reason', NEW.deny_reason,
        'agent_role', NEW.agent_role,
        'tool_use_id', NEW.tool_use_id
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tool_call_notify
    AFTER INSERT ON tool_calls
    FOR EACH ROW EXECUTE FUNCTION notify_tool_call();

-- Notification for audit events too
CREATE OR REPLACE FUNCTION notify_audit() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('audit_inserted', json_build_object(
        'id', NEW.id,
        'run_id', NEW.run_id,
        'ts', NEW.ts,
        'event_type', NEW.event_type,
        'details', NEW.details
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_notify
    AFTER INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION notify_audit();
