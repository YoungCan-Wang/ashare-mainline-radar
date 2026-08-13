-- Shadow cash-book ledger (影子账户). Independent of radar_trade_plans.is_shadow,
-- which only marks the 3-day theme-exit paper challenger.

create table if not exists public.shadow_account (
    account_id text primary key default 'default',
    cash numeric not null check (cash >= 0),
    equity numeric not null,
    market_value numeric not null check (market_value >= 0),
    initial_capital numeric not null default 100000 check (initial_capital > 0),
    as_of date,
    updated_at timestamptz not null default now()
);

create table if not exists public.shadow_positions (
    account_id text not null default 'default' references public.shadow_account (account_id),
    symbol text not null,
    name text not null,
    shares integer not null check (shares > 0),
    sellable_shares integer not null check (sellable_shares >= 0 and sellable_shares <= shares),
    avg_cost numeric not null check (avg_cost > 0),
    buy_dt date not null,
    last_mark numeric,
    opened_at timestamptz not null default now(),
    exit_pending_reason text,
    primary key (account_id, symbol)
);

create table if not exists public.shadow_events (
    event_key text primary key,
    account_id text not null default 'default' references public.shadow_account (account_id),
    as_of date not null,
    symbol text,
    event_type text not null
        check (event_type in (
            'fill_buy',
            'fill_sell',
            'entry_blocked',
            'exit_delayed',
            'skip_insufficient_cash',
            'skip_t1',
            'mark'
        )),
    price numeric,
    qty integer,
    fees jsonb not null default '{}'::jsonb,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists shadow_events_as_of_idx
    on public.shadow_events (as_of, event_type);

create table if not exists public.shadow_nav_daily (
    as_of date primary key,
    cash numeric not null,
    market_value numeric not null,
    equity numeric not null,
    pnl_day numeric not null,
    pnl_total numeric not null
);

alter table public.shadow_account enable row level security;
alter table public.shadow_positions enable row level security;
alter table public.shadow_events enable row level security;
alter table public.shadow_nav_daily enable row level security;

revoke all on table public.shadow_account from anon, authenticated;
revoke all on table public.shadow_positions from anon, authenticated;
revoke all on table public.shadow_events from anon, authenticated;
revoke all on table public.shadow_nav_daily from anon, authenticated;

grant select, insert, update, delete on table public.shadow_account to service_role;
grant select, insert, update, delete on table public.shadow_positions to service_role;
grant select, insert, update, delete on table public.shadow_events to service_role;
grant select, insert, update, delete on table public.shadow_nav_daily to service_role;

grant select, insert, update, delete on table public.shadow_account to anon;
grant select, insert, update, delete on table public.shadow_positions to anon;
grant select, insert, update, delete on table public.shadow_events to anon;
grant select, insert, update, delete on table public.shadow_nav_daily to anon;

create policy shadow_account_ingest_select
    on public.shadow_account for select to anon
    using ((select public.radar_ingest_authorized()));
create policy shadow_account_ingest_insert
    on public.shadow_account for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy shadow_account_ingest_update
    on public.shadow_account for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy shadow_account_ingest_delete
    on public.shadow_account for delete to anon
    using ((select public.radar_ingest_authorized()));

create policy shadow_positions_ingest_select
    on public.shadow_positions for select to anon
    using ((select public.radar_ingest_authorized()));
create policy shadow_positions_ingest_insert
    on public.shadow_positions for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy shadow_positions_ingest_update
    on public.shadow_positions for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy shadow_positions_ingest_delete
    on public.shadow_positions for delete to anon
    using ((select public.radar_ingest_authorized()));

create policy shadow_events_ingest_select
    on public.shadow_events for select to anon
    using ((select public.radar_ingest_authorized()));
create policy shadow_events_ingest_insert
    on public.shadow_events for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy shadow_events_ingest_update
    on public.shadow_events for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy shadow_events_ingest_delete
    on public.shadow_events for delete to anon
    using ((select public.radar_ingest_authorized()));

create policy shadow_nav_daily_ingest_select
    on public.shadow_nav_daily for select to anon
    using ((select public.radar_ingest_authorized()));
create policy shadow_nav_daily_ingest_insert
    on public.shadow_nav_daily for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy shadow_nav_daily_ingest_update
    on public.shadow_nav_daily for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy shadow_nav_daily_ingest_delete
    on public.shadow_nav_daily for delete to anon
    using ((select public.radar_ingest_authorized()));
