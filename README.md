# AShare Mainline Radar

用 TickFlow 行情数据和可插拔情报源，生成 A 股市场主线雷达报告。

这个项目的定位不是替你自动下单，而是每天回答四个实盘前必须清楚的问题：

1. 当下 A 股最强的市场主线是什么？
2. 这条主线的证据来自价格、成交、广度，还是新闻/政策/研报催化？
3. 哪些 ETF 或个股可以作为观察和参与载体？
4. 什么条件说明主线继续有效，什么条件说明该撤退或降仓？

> 重要提示：本项目生成的是研究与交易准备材料，不构成投资建议。实盘交易需要你结合账户风险、仓位规则和人工确认。

## 为什么做项目，不只做 Skill

Skill 适合封装一次性工作流；主线参与需要长期运行、数据缓存、报告留痕、策略复盘、GitHub Actions 定时任务和后续迭代，所以更适合作为独立项目。以后可以再为这个项目补一个 Codex/OpenClaw skill，让 agent 调用本仓库的 CLI。

## 数据源

- TickFlow HTTP API：A 股/ETF/美股/港股的标的池、标的元数据、日 K、实时行情等。
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
- 环境确认：A 股宽基、券商风险偏好、科技成长、外围科技映射、防御红利等环境组。
- 强势个股：从当前主线里筛选 5/20 日趋势、成交热度和接近 20 日高位的个股，并用历史信号回测。

报告会把分数拆成证据，不把它做成黑箱。

强势个股回测口径：

- 用历史某一天之前可见的 5 日、20 日涨幅、成交热度和 20 日高位距离生成信号。
- 信号日后下一交易日开盘进入。
- 默认固定持有 5 个交易日，按收盘价退出。
- 报告输出信号数、胜率、平均收益、最差收益和平均最大回撤。

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

`FEISHU_WEBHOOK_URL` 配置后，工作流会在生成报告后向飞书机器人发送主线、环境和强势个股候选摘要。默认情况下，飞书侧临时失败不会阻断报告 artifact 上传；如果希望本地或 CI 严格失败，可以加 `--fail-on-feishu-error`。`TUSHARE_TOKEN` 目前作为预留数据源 secret，不会写入报告或仓库。

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
