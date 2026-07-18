create table if not exists public.radar_trade_plans (
    plan_key text primary key,
    source_run_key text not null,
    symbol text not null,
    name text not null,
    theme text not null,
    signal_date date not null,
    signal_price numeric not null check (signal_price > 0),
    status text not null default 'watching'
        check (status in ('watching', 'triggered', 'open', 'expired', 'cancelled', 'closed')),
    entry_mode text not null,
    entry_zone_low numeric not null,
    entry_zone_high numeric not null,
    confirm_price numeric not null,
    stop_price numeric not null,
    valid_for_days integer not null check (valid_for_days between 1 and 20),
    max_hold_days integer not null check (max_hold_days between 1 and 60),
    max_position_fraction numeric not null check (max_position_fraction > 0 and max_position_fraction <= 1),
    initial_position_fraction numeric not null check (initial_position_fraction > 0 and initial_position_fraction <= 1),
    trigger_date date,
    entry_date date,
    raw_entry_price numeric,
    entry_price numeric,
    buy_fee_rate numeric,
    exit_date date,
    exit_signal_date date,
    raw_exit_price numeric,
    exit_price numeric,
    sell_fee_rate numeric,
    net_return numeric,
    exit_reason text,
    exit_delay_days integer not null default 0,
    inactive_theme_days integer not null default 0,
    last_evaluated_date date,
    cost_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists radar_trade_plans_one_active_symbol_idx
    on public.radar_trade_plans (symbol)
    where status in ('watching', 'triggered', 'open');

create index if not exists radar_trade_plans_status_signal_idx
    on public.radar_trade_plans (status, signal_date desc);

create table if not exists public.radar_trade_events (
    event_key text primary key,
    plan_key text not null references public.radar_trade_plans(plan_key) on delete cascade,
    symbol text not null,
    event_type text not null
        check (event_type in ('created', 'triggered', 'opened', 'entry_blocked', 'expired', 'cancelled', 'exit_delayed', 'closed')),
    event_date date not null,
    price numeric,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists radar_trade_events_plan_date_idx
    on public.radar_trade_events (plan_key, event_date, created_at);

alter table public.radar_trade_plans enable row level security;
alter table public.radar_trade_events enable row level security;

revoke all on table public.radar_trade_plans from anon, authenticated;
revoke all on table public.radar_trade_events from anon, authenticated;
grant select, insert, update, delete on table public.radar_trade_plans to service_role;
grant select, insert, update, delete on table public.radar_trade_events to service_role;
grant select, insert, update, delete on table public.radar_trade_plans to anon;
grant select, insert, update, delete on table public.radar_trade_events to anon;

create policy radar_trade_plans_ingest_select
    on public.radar_trade_plans for select to anon
    using ((select public.radar_ingest_authorized()));
create policy radar_trade_plans_ingest_insert
    on public.radar_trade_plans for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy radar_trade_plans_ingest_update
    on public.radar_trade_plans for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy radar_trade_plans_ingest_delete
    on public.radar_trade_plans for delete to anon
    using ((select public.radar_ingest_authorized()));

create policy radar_trade_events_ingest_select
    on public.radar_trade_events for select to anon
    using ((select public.radar_ingest_authorized()));
create policy radar_trade_events_ingest_insert
    on public.radar_trade_events for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy radar_trade_events_ingest_update
    on public.radar_trade_events for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy radar_trade_events_ingest_delete
    on public.radar_trade_events for delete to anon
    using ((select public.radar_ingest_authorized()));
