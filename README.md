# AShare Mainline Radar

用 TickFlow 行情数据和可插拔情报源，生成 A 股市场主线雷达报告。

这个项目的定位不是替你自动下单，而是每天回答五个实盘前必须清楚的问题：

1. 当下 A 股最强的市场主线是什么？
2. 这条主线的证据来自价格、成交、广度，还是新闻/政策/研报催化？
3. 哪些 ETF 或个股可以作为观察和参与载体？
4. 什么条件说明主线继续有效，什么条件说明该撤退或降仓？
5. 候选公司的最新财务是否兑现，增长、ROE、现金流和估值参考是否支持交易逻辑？

> 重要提示：本项目生成的是研究与交易准备材料，不构成投资建议。实盘交易需要你结合账户风险、仓位规则和人工确认。

## 为什么做项目，不只做 Skill

Skill 适合封装一次性工作流；主线参与需要长期运行、数据缓存、报告留痕、策略复盘、GitHub Actions 定时任务和后续迭代，所以更适合作为独立项目。以后可以再为这个项目补一个 Codex/OpenClaw skill，让 agent 调用本仓库的 CLI。

## 数据源

- TickFlow HTTP API：A 股/ETF/美股/港股的标的池、标的元数据、日 K、实时行情及核心财务指标等。
- 全市场扫描使用批量接口，并对 `429` 限流响应自动退避重试。
- A股 K 线时间戳按 `Asia/Shanghai` 转换交易日，避免周一行情被 UTC 截断成周日。
- 免费模式：无需 API key，可用日 K、标的池、标的信息，适合收盘后主线扫描。
- 完整模式：设置 `TICKFLOW_API_KEY` 后自动使用 `https://api.tickflow.org`，后续可扩展实时行情和分钟线。
- 情报源：`configs/intel_sources.json` 支持 RSS、资讯列表页、网页标题、手动导入研报文本/纪要。

TickFlow 文档：https://docs.tickflow.org/zh-Hans

## 快速开始

```bash
cd /Users/youngcan/stock/ashare-mainline-radar
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

没有 API key 也可以直接跑：

```bash
python3 scripts/run_daily.py --mode curated --lookback-days 180
```

输出：

- `reports/latest/mainline_report.md`
- `reports/latest/mainline_report.json`
- `reports/latest/feishu_card.json`

如果要扫描全市场：

```bash
python3 scripts/run_daily.py --mode universe --max-symbols 0 --lookback-days 180
```

为了避免免费接口请求太多，调试时可以限制样本：

```bash
python3 scripts/run_daily.py --mode universe --max-symbols 800
```

有 TickFlow API key 时：

```bash
export TICKFLOW_API_KEY="your-api-key"
python3 scripts/run_daily.py --mode universe --max-symbols 0
```

## 主线评分口径

当前评分由四部分构成：

- 价格趋势：5 日、20 日涨幅、是否接近 20 日高点。
- 成交热度：5 日成交额均值相对 20 日成交额均值。
- 主线广度：主题内上涨股票比例、有效成员数量、龙头强度。
- 催化证据：新闻、宏观、研报摘录中命中的主题关键词。
- 政策催化：官方政策源命中 `policy_keywords` 后单独计分，作为 A 股政策市确认项。
- 环境确认：A 股宽基、券商风险偏好、科技成长、外围科技映射、防御红利等环境组。
- 强势个股：从当前主线里筛选 5/20 日趋势、成交热度和接近 20 日高位的个股，并用历史信号回测。
- 低位资金介入：从扫描范围内找 60 日中低位、成交额均线抬升、短线跌势收敛的股票，作为观察/试错池。
- 市场交易闸门：以 A 股宽基单日跌幅和中期环境分为硬约束，输出“暂停新仓 / 只准试错仓 / 允许寻找买点”。
- 主线黄金坑：只在前三主线中寻找回撤可控、中期趋势未破、相对大盘抗跌或出现放量承接的核心股，并区分“坑位形成”和“止跌确认”。
- 基本面兑现：对候选池二次拉取营收同比、净利润同比、ROE、每股经营现金流和每股净资产，参与最终重排。

报告会把分数拆成证据，不把它做成黑箱。

政策催化口径：

- 官方政策源优先：发改委、证监会、央行、财政部、商务部等公开页面。
- 政策匹配使用主题里的 `policy_keywords`，和普通新闻/研报关键词分开，避免“资源”“金融”等宽词误匹配。
- 政策分只做主线加分和证据展示；没有价格、成交、广度确认时，不会单独变成买入理由。
- 每个政策源的抓取状态会写入“数据源状态”，源失败不会阻断行情报告。

强势个股回测口径：

- 用历史某一天之前可见的 5 日、20 日涨幅、成交热度和 20 日高位距离生成信号。
- 信号日后下一交易日开盘进入。
- 默认固定持有 5 个交易日，按收盘价退出。
- 报告输出信号数、胜率、平均收益、最差收益和平均最大回撤。

报告还会生成 `next_buy.primary`，也就是系统下一笔优先候选；同时 `next_buy.by_theme` 会按命中条件的活跃主线保留各自的顺势候选，所以不是只推荐第一主线。它不会输出无条件市价买入，而是给出：

- 买入候选标的和所属主线。
- 当前决策：如“等待回踩”“突破确认候选”“分批确认”。
- 触发/参与条件。
- 失效条件。
- 仓位提示和风险提示。

默认交易风格按持有约 10-20 个交易日设计，历史信号回测使用 15 个交易日作为中位基准。可通过 `--backtest-hold-days` 或 `MAINLINE_HOLD_DAYS` 调整。

报告还会生成 `accumulation.candidates`，专门回答“低位但资金开始介入的股票能不能找”。它和强势股不是同一张榜：

- 强势顺势候选：适合跟随已经走出来的主线，重点看趋势强度和历史信号回测。
- 低位资金介入候选：适合观察或试错，重点看 60 日位置、距离高点回撤、成交额 5/20 和 10/30 均线比、5 日止跌结构。
- 低位候选必须等触发条件确认；低位本身不是买点。

`golden_pits.candidates` 则寻找强主线急跌后的黄金坑，它和长期低位启动也不是同一类机会：

- 主线必须仍在前三且至少为“主线候选”，基本面不能是“基本面拖累”。
- 回撤必须处于可控区间，中期趋势不能已经破坏，并且个股相对三大指数抗跌或出现日内放量承接。
- “坑位形成”只观察；“止跌确认”还要满足重新站回短期均线并放量。
- `trading_gate` 为红色时，所有黄金坑都只观察，不允许转成新开仓提示。

报告还会生成 `target_prices.estimates`，给买入候选和低位候选配套目标价区间：

- 当前版本给的是交易/研究目标区间，不等同于券商正式目标价。
- 顺势候选用趋势高点、波动、回测收益和主线状态估算 2-8 周目标区间。
- 低位候选用 60 日压力位修复、成交额抬升和止跌结构估算 4-12 周观察目标。
- 如果本地研报文本里出现“目标价/合理价值/估值区间”，系统会提取为研报目标参考。
- 每个目标价都会同时给出失效价、到失效价回撤、赔率和信心等级。

报告还会生成 `fundamentals.snapshots`，用于区分“题材上涨”和“业绩兑现”：

- 财务接口只拉行情初筛后的候选池，避免对全市场重复请求高成本数据。
- 财务评分检查营收、净利润、ROE、经营现金流，以及相对上年同期的增长趋势变化。
- PB只作为估值参考，不跨行业使用统一贵贱阈值。
- `基本面拖累` 会让顺势候选降分并转为等待修复；无财务权限时系统明确标记未覆盖，但不阻断日报。
- TickFlow核心财务指标不含卖方一致预期上修，系统不会用股价上涨替代盈利预测修正证据。

## 主题配置

主题篮子在 `configs/theme_baskets.json`。第一版先维护常见 A 股主线：

- AI 算力
- 半导体国产替代
- 机器人
- 低空经济
- 固态电池
- 创新药
- 军工
- 有色金属与铜
- 券商金融
- 高股息红利
- 消费电子

后续可以接入更细的行业/概念库，让全市场扫描自动归因。

## 研报和新闻

券商研报多数受版权和登录限制影响，项目不内置抓取付费研报全文。建议把你有权限使用的研报摘要、纪要或 Markdown/TXT/HTML 放进：

```text
data/research_reports/inbox/
```

运行时会自动读取这些本地文本，并用主题关键词打标签，作为主线催化证据。

报告底部会输出“数据源状态”，用于检查 TickFlow、RSS、政策网页、本地研报箱是否成功拉取，避免某个源失败时误以为市场没有线索。

## GitHub Actions

`.github/workflows/daily-mainline.yml` 支持手动触发和交易日收盘后定时运行，报告作为 artifact 上传。

如果要使用完整 TickFlow 服务，在 GitHub 仓库设置 Secret：

```text
TICKFLOW_API_KEY
FEISHU_WEBHOOK_URL
TUSHARE_TOKEN
```

`FEISHU_WEBHOOK_URL` 配置后，工作流会发送红色交互卡片，按“可尝试建仓、已有仓位可继续持有、等待回踩、低位观察”组织结果，并展示入场触发、失效条件、目标区和15日回测。默认情况下，飞书侧临时失败不会阻断报告 artifact 上传；如果希望本地或 CI 严格失败，可以加 `--fail-on-feishu-error`。`TUSHARE_TOKEN` 目前作为预留数据源 secret，不会写入报告或仓库。

飞书通知状态会写入：

```text
reports/latest/notification_status.json
```

这个文件只记录 `sent` / `skipped` / `failed`、错误码和错误消息，不记录 webhook URL。也可以单独诊断 webhook：

```bash
FEISHU_WEBHOOK_URL="..." python3 scripts/check_feishu.py
```

常见飞书 webhook 状态：

- `sent`：飞书已接受消息。
- `failed` + `code=19007` + `Bot Not Enabled`：飞书侧机器人未启用、被禁用或被移除；需要在飞书群机器人设置里启用当前机器人，或换一个状态正常的新 webhook。
- `skipped`：没有配置 `FEISHU_WEBHOOK_URL`。

## 本地验证

```bash
python3 -m pytest
python3 scripts/run_daily.py --mode curated --output-dir reports/latest
```

## 下一步路线

- 接行业/概念库，让全市场股票自动归因到题材。
- 加 ETF/指数和外围市场联动确认。
- 加研报 PDF 解析与 LLM 摘要，但只处理你有权限的文件。
- 加实盘观察清单：入场触发、仓位上限、失效条件、复盘记录。
