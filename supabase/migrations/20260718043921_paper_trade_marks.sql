alter table public.radar_trade_plans
    add column if not exists mark_date date,
    add column if not exists mark_price numeric;
