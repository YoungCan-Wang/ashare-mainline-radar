create table if not exists public.radar_runs (
    run_key text primary key,
    market_date date not null,
    generated_at timestamptz not null,
    mode text not null,
    universe text not null,
    scanned_symbols integer not null default 0 check (scanned_symbols >= 0),
    top_theme text,
    gate_level text,
    gate_state text,
    gate_score numeric,
    summary jsonb not null default '{}'::jsonb check (jsonb_typeof(summary) = 'object'),
    updated_at timestamptz not null default now()
);

comment on table public.radar_runs is
    'One idempotent A-share radar run per market date, mode, and universe.';

create table if not exists public.radar_theme_snapshots (
    run_key text not null references public.radar_runs(run_key) on delete cascade,
    market_date date not null,
    theme text not null,
    rank integer not null check (rank > 0),
    status text,
    score numeric,
    lifecycle_stage text,
    snapshot jsonb not null default '{}'::jsonb check (jsonb_typeof(snapshot) = 'object'),
    lifecycle jsonb not null default '{}'::jsonb check (jsonb_typeof(lifecycle) = 'object'),
    updated_at timestamptz not null default now(),
    primary key (run_key, theme)
);

comment on table public.radar_theme_snapshots is
    'Ranked theme snapshots for each radar run, including lifecycle evidence.';

create table if not exists public.radar_symbol_snapshots (
    run_key text not null references public.radar_runs(run_key) on delete cascade,
    market_date date not null,
    symbol text not null,
    exchange text,
    name text not null,
    primary_theme text,
    themes text[] not null default '{}',
    roles text[] not null default '{}',
    action_state text,
    priority_score numeric,
    last_close numeric,
    market_metrics jsonb not null default '{}'::jsonb check (jsonb_typeof(market_metrics) = 'object'),
    signal_payload jsonb not null default '{}'::jsonb check (jsonb_typeof(signal_payload) = 'object'),
    fundamental_payload jsonb not null default '{}'::jsonb check (jsonb_typeof(fundamental_payload) = 'object'),
    target_payload jsonb not null default '{}'::jsonb check (jsonb_typeof(target_payload) = 'object'),
    trade_plan jsonb not null default '{}'::jsonb check (jsonb_typeof(trade_plan) = 'object'),
    updated_at timestamptz not null default now(),
    primary key (run_key, symbol)
);

comment on table public.radar_symbol_snapshots is
    'One normalized row per selected symbol and radar run; multiple signal roles are merged.';

create index if not exists radar_runs_market_date_idx
    on public.radar_runs (market_date desc);
create index if not exists radar_theme_snapshots_theme_date_idx
    on public.radar_theme_snapshots (theme, market_date desc);
create index if not exists radar_symbol_snapshots_symbol_date_idx
    on public.radar_symbol_snapshots (symbol, market_date desc);
create index if not exists radar_symbol_snapshots_roles_idx
    on public.radar_symbol_snapshots using gin (roles);
create index if not exists radar_symbol_snapshots_themes_idx
    on public.radar_symbol_snapshots using gin (themes);

alter table public.radar_runs enable row level security;
alter table public.radar_theme_snapshots enable row level security;
alter table public.radar_symbol_snapshots enable row level security;

revoke all on table public.radar_runs from anon, authenticated;
revoke all on table public.radar_theme_snapshots from anon, authenticated;
revoke all on table public.radar_symbol_snapshots from anon, authenticated;

grant select, insert, update, delete on table public.radar_runs to service_role;
grant select, insert, update, delete on table public.radar_theme_snapshots to service_role;
grant select, insert, update, delete on table public.radar_symbol_snapshots to service_role;
