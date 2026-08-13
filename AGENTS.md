# Project Agent Instructions

## Database DDL

- Never `git add`, commit, or push `*.sql` files. Keep them local; `supabase/migrations/*.sql` is gitignored.
- Never apply DDL from CI, and never assume merging a PR will migrate the remote database.
- Required order: write SQL locally → execute it in the live Supabase SQL editor → confirm the object exists → update `supabase/schema_contract.json` → commit application code only.
- Do not merge until the PR pipeline is green. It fails if the diff contains `.sql`, or if live PostgREST is missing a contracted table or RPC.
- If code needs a new table or `apply_shadow_day`-style function, apply that DDL on live Supabase first. Merging first will break production.

## Completion notifications

- After every user-requested task in this project is genuinely complete, send a concise Feishu direct message with `lark-cli`.
- Send as the bot identity (`--as bot`) to user open ID `ou_265396a9e26fff2541aed28ef025c2c2` (王涌恺).
- Use this message shape: `✅ ashare-mainline-radar 任务完成：<one-sentence outcome>\n验证：<tests/checks performed>`.
- Use a unique idempotency key no longer than 50 characters.
- Do not send a completion message while required work remains, when the task is blocked, or for intermediate status updates.
- Follow the installed `lark-shared` and `lark-im` skill safety and authentication instructions for every send.
