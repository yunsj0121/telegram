create table if not exists public.telegram_relay_cursors (
    source_channel text not null,
    target_channel text not null,
    last_source_message_id bigint not null default 0,
    updated_at timestamptz not null default now(),
    primary key (source_channel, target_channel)
);

create table if not exists public.telegram_relay_message_map (
    source_channel text not null,
    target_channel text not null,
    source_message_id bigint not null,
    target_message_id bigint not null,
    grouped_id bigint,
    source_edit_date timestamptz,
    created_at timestamptz not null default now(),
    primary key (source_channel, target_channel, source_message_id)
);

alter table public.telegram_relay_cursors enable row level security;
alter table public.telegram_relay_message_map enable row level security;

revoke all on table public.telegram_relay_cursors
    from public, anon, authenticated, service_role;
revoke all on table public.telegram_relay_message_map
    from public, anon, authenticated, service_role;

grant select, insert, update, delete
    on table public.telegram_relay_cursors to service_role;
grant select, insert, update, delete
    on table public.telegram_relay_message_map to service_role;
