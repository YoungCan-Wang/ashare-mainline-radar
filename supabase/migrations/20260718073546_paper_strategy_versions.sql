alter table public.radar_trade_plans
    add column if not exists strategy_version text not null default 'mainline-v1-theme-exit-2d',
    add column if not exists strategy_label text not null default '生产模拟｜连续2日退出',
    add column if not exists theme_exit_days integer not null default 2
        check (theme_exit_days between 1 and 20),
    add column if not exists is_shadow boolean not null default false;

alter table public.radar_trade_events
    add column if not exists strategy_version text not null default 'mainline-v1-theme-exit-2d';

drop index if exists public.radar_trade_plans_one_active_symbol_idx;

create unique index if not exists radar_trade_plans_one_active_symbol_strategy_idx
    on public.radar_trade_plans (symbol, strategy_version)
    where status in ('watching', 'triggered', 'open');

create index if not exists radar_trade_plans_strategy_status_idx
    on public.radar_trade_plans (strategy_version, status, signal_date desc);
