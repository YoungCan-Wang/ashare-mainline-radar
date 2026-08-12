# Project Agent Instructions

## Completion notifications

- After every user-requested task in this project is genuinely complete, send a concise Feishu direct message with `lark-cli`.
- Send as the bot identity (`--as bot`) to user open ID `ou_265396a9e26fff2541aed28ef025c2c2` (王涌恺).
- Use this message shape: `✅ ashare-mainline-radar 任务完成：<one-sentence outcome>\n验证：<tests/checks performed>`.
- Use a unique idempotency key no longer than 50 characters.
- Do not send a completion message while required work remains, when the task is blocked, or for intermediate status updates.
- Follow the installed `lark-shared` and `lark-im` skill safety and authentication instructions for every send.
