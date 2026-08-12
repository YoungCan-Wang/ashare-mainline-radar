-- Free-tier DB: expectation_gap stays in daily report artifacts only (ranked in
-- JSON/MD/Feishu). Do not expand quote/selection tracking for that role.
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
               'next_buy', 'strong_stock', 'golden_pit', 'accumulation', 'monthly_base'
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
        prev_close = case
            when excluded.quote_date = public.radar_symbol_quotes.quote_date
                then public.radar_symbol_quotes.prev_close
            else null
        end,
        daily_change_pct = case
            when excluded.quote_date = public.radar_symbol_quotes.quote_date
                then public.radar_symbol_quotes.daily_change_pct
            else null
        end,
        session = case
            when excluded.quote_date = public.radar_symbol_quotes.quote_date
                then public.radar_symbol_quotes.session
            else null
        end,
        source = excluded.source,
        refreshed_at = excluded.refreshed_at
    where excluded.quote_at >= public.radar_symbol_quotes.quote_at;

    return new;
end;
$$;
