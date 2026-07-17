create table if not exists public.radar_symbol_selections (
    symbol text primary key,
    name text not null,
    primary_theme text,
    first_selected_at timestamptz not null,
    first_market_date date not null,
    first_selected_price numeric not null check (first_selected_price > 0),
    first_run_key text not null,
    first_roles text[] not null default '{}',
    latest_selected_at timestamptz not null,
    latest_market_date date not null,
    latest_run_key text not null,
    updated_at timestamptz not null default now()
);

comment on table public.radar_symbol_selections is
    'Permanent first-selection basis for symbols that entered an actionable radar role.';

create table if not exists public.radar_symbol_quotes (
    symbol text primary key references public.radar_symbol_selections(symbol) on delete cascade,
    quote_at timestamptz not null,
    quote_date date not null,
    latest_price numeric not null check (latest_price > 0),
    prev_close numeric,
    daily_change_pct numeric,
    session text,
    source text not null,
    refreshed_at timestamptz not null default now()
);

comment on table public.radar_symbol_quotes is
    'Latest TickFlow quote for each actionable radar selection.';

create index if not exists radar_symbol_selections_latest_date_idx
    on public.radar_symbol_selections (latest_market_date desc);
create index if not exists radar_symbol_quotes_refreshed_at_idx
    on public.radar_symbol_quotes (refreshed_at desc);

alter table public.radar_symbol_selections enable row level security;
alter table public.radar_symbol_quotes enable row level security;

revoke all on table public.radar_symbol_selections from anon, authenticated;
revoke all on table public.radar_symbol_quotes from anon, authenticated;

grant select, insert, update, delete on table public.radar_symbol_selections to service_role;
grant select, insert, update, delete on table public.radar_symbol_quotes to service_role;
grant select, insert, update, delete on table public.radar_symbol_selections to anon;
grant select, insert, update, delete on table public.radar_symbol_quotes to anon;

create policy radar_symbol_selections_ingest_select
    on public.radar_symbol_selections for select to anon
    using ((select public.radar_ingest_authorized()));
create policy radar_symbol_selections_ingest_insert
    on public.radar_symbol_selections for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy radar_symbol_selections_ingest_update
    on public.radar_symbol_selections for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy radar_symbol_selections_ingest_delete
    on public.radar_symbol_selections for delete to anon
    using ((select public.radar_ingest_authorized()));

create policy radar_symbol_quotes_ingest_select
    on public.radar_symbol_quotes for select to anon
    using ((select public.radar_ingest_authorized()));
create policy radar_symbol_quotes_ingest_insert
    on public.radar_symbol_quotes for insert to anon
    with check ((select public.radar_ingest_authorized()));
create policy radar_symbol_quotes_ingest_update
    on public.radar_symbol_quotes for update to anon
    using ((select public.radar_ingest_authorized()))
    with check ((select public.radar_ingest_authorized()));
create policy radar_symbol_quotes_ingest_delete
    on public.radar_symbol_quotes for delete to anon
    using ((select public.radar_ingest_authorized()));

with first_rows as (
    select distinct on (symbol)
        symbol,
        name,
        primary_theme,
        coalesce(updated_at, market_date::timestamptz) as selected_at,
        market_date,
        last_close,
        run_key,
        roles
    from public.radar_symbol_snapshots
    where last_close > 0
      and roles && array[
          'next_buy', 'strong_stock', 'golden_pit', 'accumulation', 'monthly_base', 'expectation_gap'
      ]::text[]
    order by symbol, market_date, updated_at, run_key
), latest_rows as (
    select distinct on (symbol)
        symbol,
        name,
        primary_theme,
        coalesce(updated_at, market_date::timestamptz) as selected_at,
        market_date,
        run_key
    from public.radar_symbol_snapshots
    where last_close > 0
      and roles && array[
          'next_buy', 'strong_stock', 'golden_pit', 'accumulation', 'monthly_base', 'expectation_gap'
      ]::text[]
    order by symbol, market_date desc, updated_at desc, run_key desc
)
insert into public.radar_symbol_selections (
    symbol,
    name,
    primary_theme,
    first_selected_at,
    first_market_date,
    first_selected_price,
    first_run_key,
    first_roles,
    latest_selected_at,
    latest_market_date,
    latest_run_key,
    updated_at
)
select
    first_rows.symbol,
    latest_rows.name,
    latest_rows.primary_theme,
    first_rows.selected_at,
    first_rows.market_date,
    first_rows.last_close,
    first_rows.run_key,
    first_rows.roles,
    latest_rows.selected_at,
    latest_rows.market_date,
    latest_rows.run_key,
    now()
from first_rows
join latest_rows using (symbol)
on conflict (symbol) do nothing;

with latest_rows as (
    select distinct on (symbol)
        symbol,
        coalesce(updated_at, market_date::timestamptz) as quote_at,
        market_date,
        last_close
    from public.radar_symbol_snapshots
    where last_close > 0
      and roles && array[
          'next_buy', 'strong_stock', 'golden_pit', 'accumulation', 'monthly_base', 'expectation_gap'
      ]::text[]
    order by symbol, market_date desc, updated_at desc, run_key desc
)
insert into public.radar_symbol_quotes (
    symbol, quote_at, quote_date, latest_price, source, refreshed_at
)
select symbol, quote_at, market_date, last_close, 'daily_report', now()
from latest_rows
on conflict (symbol) do nothing;

create or replace function public.sync_radar_symbol_tracking()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.last_close is null
       or new.last_close <= 0
       or not (
           new.roles && array[
               'next_buy', 'strong_stock', 'golden_pit', 'accumulation', 'monthly_base', 'expectation_gap'
           ]::text[]
       ) then
        return new;
    end if;

    insert into public.radar_symbol_selections (
        symbol,
        name,
        primary_theme,
        first_selected_at,
        first_market_date,
        first_selected_price,
        first_run_key,
        first_roles,
        latest_selected_at,
        latest_market_date,
        latest_run_key,
        updated_at
    )
    values (
        new.symbol,
        new.name,
        new.primary_theme,
        coalesce(new.updated_at, now()),
        new.market_date,
        new.last_close,
        new.run_key,
        new.roles,
        coalesce(new.updated_at, now()),
        new.market_date,
        new.run_key,
        now()
    )
    on conflict (symbol) do update set
        name = excluded.name,
        primary_theme = excluded.primary_theme,
        latest_selected_at = excluded.latest_selected_at,
        latest_market_date = excluded.latest_market_date,
        latest_run_key = excluded.latest_run_key,
        updated_at = now()
    where excluded.latest_selected_at >= public.radar_symbol_selections.latest_selected_at;

    insert into public.radar_symbol_quotes (
        symbol, quote_at, quote_date, latest_price, source, refreshed_at
    )
    values (
        new.symbol,
        coalesce(new.updated_at, now()),
        new.market_date,
        new.last_close,
        'daily_report',
        now()
    )
    on conflict (symbol) do update set
        quote_at = excluded.quote_at,
        quote_date = excluded.quote_date,
        latest_price = excluded.latest_price,
        prev_close = null,
        daily_change_pct = null,
        session = null,
        source = excluded.source,
        refreshed_at = excluded.refreshed_at
    where excluded.quote_at >= public.radar_symbol_quotes.quote_at;

    return new;
end;
$$;

revoke all on function public.sync_radar_symbol_tracking() from public, authenticated;
grant execute on function public.sync_radar_symbol_tracking() to anon, service_role;

drop trigger if exists sync_radar_symbol_tracking_trigger on public.radar_symbol_snapshots;
create trigger sync_radar_symbol_tracking_trigger
after insert or update on public.radar_symbol_snapshots
for each row execute function public.sync_radar_symbol_tracking();
