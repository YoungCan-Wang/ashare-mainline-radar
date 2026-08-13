-- Commit one shadow-account session in a single transaction.
-- Python computes the next book in memory; this function is the only writer.

create or replace function public.apply_shadow_day(
    p_account jsonb,
    p_positions jsonb,
    p_events jsonb,
    p_nav jsonb
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    v_account_id text;
    v_as_of date;
begin
    if not public.radar_ingest_authorized() then
        raise exception 'radar ingest unauthorized';
    end if;

    v_account_id := p_account->>'account_id';
    v_as_of := (p_nav->>'as_of')::date;
    if v_account_id is null or v_account_id = '' or v_as_of is null then
        raise exception 'apply_shadow_day requires account_id and nav.as_of';
    end if;

    insert into public.shadow_account as t (
        account_id, cash, equity, market_value, initial_capital, as_of, updated_at
    )
    values (
        v_account_id,
        (p_account->>'cash')::numeric,
        (p_account->>'equity')::numeric,
        (p_account->>'market_value')::numeric,
        (p_account->>'initial_capital')::numeric,
        (p_account->>'as_of')::date,
        coalesce((p_account->>'updated_at')::timestamptz, now())
    )
    on conflict (account_id) do update set
        cash = excluded.cash,
        equity = excluded.equity,
        market_value = excluded.market_value,
        initial_capital = excluded.initial_capital,
        as_of = excluded.as_of,
        updated_at = excluded.updated_at;

    delete from public.shadow_positions p
    where p.account_id = v_account_id
      and not exists (
          select 1
          from jsonb_array_elements(coalesce(p_positions, '[]'::jsonb)) pos
          where pos->>'symbol' = p.symbol
      );

    insert into public.shadow_positions as t (
        account_id, symbol, name, shares, sellable_shares, avg_cost,
        buy_dt, last_mark, opened_at, exit_pending_reason
    )
    select
        coalesce(nullif(pos->>'account_id', ''), v_account_id),
        pos->>'symbol',
        pos->>'name',
        (pos->>'shares')::integer,
        (pos->>'sellable_shares')::integer,
        (pos->>'avg_cost')::numeric,
        (pos->>'buy_dt')::date,
        nullif(pos->>'last_mark', '')::numeric,
        coalesce((pos->>'opened_at')::timestamptz, now()),
        nullif(pos->>'exit_pending_reason', '')
    from jsonb_array_elements(coalesce(p_positions, '[]'::jsonb)) pos
    on conflict (account_id, symbol) do update set
        name = excluded.name,
        shares = excluded.shares,
        sellable_shares = excluded.sellable_shares,
        avg_cost = excluded.avg_cost,
        buy_dt = excluded.buy_dt,
        last_mark = excluded.last_mark,
        opened_at = excluded.opened_at,
        exit_pending_reason = excluded.exit_pending_reason;

    delete from public.shadow_events
    where account_id = v_account_id
      and as_of = v_as_of;

    insert into public.shadow_events (
        event_key, account_id, as_of, symbol, event_type, price, qty, fees, payload, created_at
    )
    select
        ev->>'event_key',
        coalesce(nullif(ev->>'account_id', ''), v_account_id),
        (ev->>'as_of')::date,
        nullif(ev->>'symbol', ''),
        ev->>'event_type',
        nullif(ev->>'price', '')::numeric,
        nullif(ev->>'qty', '')::integer,
        coalesce(ev->'fees', '{}'::jsonb),
        coalesce(ev->'payload', '{}'::jsonb),
        coalesce((ev->>'created_at')::timestamptz, now())
    from jsonb_array_elements(coalesce(p_events, '[]'::jsonb)) ev;

    insert into public.shadow_nav_daily as t (
        as_of, cash, market_value, equity, pnl_day, pnl_total
    )
    values (
        v_as_of,
        (p_nav->>'cash')::numeric,
        (p_nav->>'market_value')::numeric,
        (p_nav->>'equity')::numeric,
        (p_nav->>'pnl_day')::numeric,
        (p_nav->>'pnl_total')::numeric
    )
    on conflict (as_of) do update set
        cash = excluded.cash,
        market_value = excluded.market_value,
        equity = excluded.equity,
        pnl_day = excluded.pnl_day,
        pnl_total = excluded.pnl_total;
end;
$$;

revoke all on function public.apply_shadow_day(jsonb, jsonb, jsonb, jsonb) from public, authenticated;
grant execute on function public.apply_shadow_day(jsonb, jsonb, jsonb, jsonb) to anon, service_role;
