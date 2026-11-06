# Experiential Labs CLI

一个非官方、只读的 Experiential Labs 用量工具。Python 3.11+，运行时没有第三方依赖。

按模型查看请求数、输入/输出 tokens、平台实际扣款与 BYOK 估算费用，同时查看组织钱包余额和当前 key 的每日额度。API 客户端、汇总逻辑与终端展示分层，后续 portal 可在服务端复用。

## 快速开始

在仓库目录运行，无需安装依赖：

```sh
python3 -m explabs --env-file /absolute/path/to/.env
```

文件中使用：

```dotenv
EXPLABS_API_KEY=your_key_here
```

也可以使用已有变量名：

```sh
python3 -m explabs --env-file /absolute/path/to/.env --key-name OPENAI_API_KEY
```

指定文件后，key **只从该文件读取**，不被 shell 环境覆盖。支持 `export`、引号和注释；不执行文件，不展开变量或命令。未传 `--env-file` 时读取当前进程的 `EXPLABS_API_KEY`。不会自动搜索磁盘上的密钥文件。

```sh
# 最近 24 小时 / 7 天（默认）/ 30 天
python3 -m explabs --env-file ~/.config/explabs/.env --window 30d

# 模型过滤
python3 -m explabs --env-file ~/.config/explabs/.env --model MODEL_SLUG

# 指定调用 key 的 UUID（不是 key 明文）；钱包仍为组织范围
python3 -m explabs --env-file ~/.config/explabs/.env --api-key-id KEY_UUID

# JSON 可交给其他工具或未来 portal；USD 金额输出为精确十进制字符串
python3 -m explabs --env-file ~/.config/explabs/.env --json
```

可选：在项目虚拟环境安装终端命令（不用全局安装）：

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install .
.venv/bin/explabs --env-file /absolute/path/to/.env
```

## 读数含义与额度边界

| 内容 | 当前实现 |
| --- | --- |
| 每个已使用模型的请求数、tokens、费用 | 遍历 `/api/v1/usage` 全部分页，按模型汇总 |
| 实际平台扣款 | `cost_usd`，包括产生扣款的失败请求 |
| BYOK 费用 | `estimated_cost_usd`，仅归因估算，不是供应商账单 |
| 钱包余额 | `/api/v1/credits` 的 `total_credits - total_usage`，单位 USD |
| 当前 key 每日限额及今日剩余 | `/api/v1/key` 的 `limit`、`limit_remaining` |
| 每个模型的免费促销剩余额度 | **尚未支持**：已查阅的 Cost API 没有给出这类计数器，不将钱包余额冒充各模型额度 |

钱包和 key 日额度由模型共享。余额仅扣除已结算费用，未扣除 pending holds，因此不是新请求的保证可用额度。`null` 的已知 key 上限表示不封顶；缺失或读取失败显示 unavailable，不会伪装成零或无限。

用量默认是组织范围；受 customer plan 约束的 key 由服务端限制在其 identity 范围。过滤模型/key 不会改变钱包或所持 key 的额度范围。未使用的模型不出现在汇总中。缓存输入属于输入，reasoning 属于输出，不重复加进总 tokens。未知价格单独计数，零值不被解释为免费。

本工具读取实时结算流，不是冻结报表；查询期间新增结算、移动的回看窗口可能造成边界变化。适合日常查看，不作为最终对账凭据。默认最多读取 1,000 页；到达上限或检测到异常 cursor 时停止并报错，不输出看似完整的部分汇总。可用 `--max-pages` 调整。

退出码：`0` 完整获取所实现的数据；`2` 用量已获取，但余额/key 等辅助读取有警告；`1` 配置、网络或用量失败；`130` 用户中断。

## 官方接口依据

核对日期：2026-11-06。

- [Cost API](https://platform.experientiallabs.ai/docs/cost-api)：余额、结算明细、分页，以及 identity 限制。
- [Account API](https://platform.experientiallabs.ai/docs/account-api)：当前 key 每日限额；组织 Spend 报表需要 provisioning key。
- [Credits & billing](https://platform.experientiallabs.ai/docs/billing)：钱包、促销及 pending holds 的区别。
- [机器可读参考](https://platform.experientiallabs.ai/llms.txt)：支持的 `24h/7d/30d` 窗口和 cursor 语义。

Billing 页面仍有余额仅支持 web session 的说法，与 Cost API 文档不一致。本工具按 Cost API 调用，实际被拒绝时显示不可读取。模型促销、平台订阅、customer-plan 分组额度和所持 key 的日额度属于不同计量范围，不能互相替代。

## 安全与开发

只发 HTTPS GET 到 `api.experientiallabs.ai`，不调用推理、不充值、不修改账户。拒绝重定向，避免转发 Bearer key；错误不打印服务器响应体；输出对当前 key 进行脱敏。`.env`、`.env.*` 和 `*.env` 默认忽略，只有不含真实 key 的 `.env.example` 被跟踪。JSON 报表仍含账户用量信息，请自行选择保存位置。

```sh
python3 -m unittest discover -s tests -v
python3 -m explabs --help
```

- `explabs/client.py`：只读传输、超时、有限重试与错误处理。
- `explabs/config.py`：dotenv 读取。
- `explabs/service.py`：分页、金额精确汇总、报告结构；portal 应在服务端调用。
- `explabs/cli.py`：参数与表格/JSON 展示。

测试覆盖分页与截断、金额精度、重复记录、失败请求计费、未知价格、权限降级、dotenv、错误脱敏和传输约束。CI 在 Python 3.11、3.13、3.15 上运行；不会使用真实账户密钥。

首次交付尚未取得本地 `.env` 路径，因此账户余额、实际用量与 key 额度的真实凭据验证仍待完成。已执行无效 key 的线上只读鉴权检查，但这不能证明真实账户的接口兼容性。
