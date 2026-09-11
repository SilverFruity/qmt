# qmt-client

`qmt-client` 是 QMT 本地 HTTP / WebSocket 交易服务（仓库 `Xorcerer/qmt` 的 `server.py`）的 Python 客户端封装。
它把鉴权、Host 约束、超时、错误映射和批量分批等细节收进一个类，业务侧只调用方法。

- 传输：`requests`（同步 HTTP）+ `websocket-client`（行情推送）
- Python：>= 3.8
- 默认地址：`http://127.0.0.1:18080`

## 安装

本地开发安装：

~~~bash
pip install -e ".[dev]"
~~~

## 快速开始

~~~python
from qmt_client import QMTClient

client = QMTClient.from_env()          # 读取 QMT_AUTH_TOKEN / QMT_HOST / QMT_PORT / QMT_TIMEOUT
print(client.health())
print(client.positions())
print(client.quote("600000.SH"))
client.close()
~~~

也可以显式构造：

~~~python
client = QMTClient(token="...", host="127.0.0.1", port=18080, timeout=10)
~~~

## 配置与鉴权

服务端是 fail-closed：`auth_token` 为空时拒绝所有请求。客户端同样在 token 为空时抛出 `ValueError`，避免调用方误以为“没配 token 就是开放”。

~~~text
QMT_AUTH_TOKEN   必填，与服务端 server_config.json 中的 auth_token 一致
QMT_HOST         默认 127.0.0.1
QMT_PORT         默认 18080
QMT_TIMEOUT      默认 10 秒
QMT_DISCOVERY_SECRET  可选，局域网发现密钥；与服务端 discovery_secret 一致
QMT_DISCOVERY_PORT    可选，发现端口，默认 18081
~~~

说明：

- 默认发送 `Authorization: Bearer <token>`；构造参数 `auth_scheme="X-QMT-Token"` 时改用 `X-QMT-Token` 头。
- 服务端只接受 `127.0.0.1` / `localhost` 的 Host，不要用机器名或其它 IP 别名访问。
- WebSocket 握手沿用同一 token（`Authorization`，服务端也支持 `Sec-WebSocket-Protocol: qmt-token.<token>`）。
- 局域网部署：把 `host` 指向服务端网卡 IP（或设 `QMT_HOST`），服务端 `allowed_hosts` 需含该地址；
  该场景为明文传输，见主仓 README 的「局域网部署」与安全须知。

### 局域网发现

服务端启用发现后，客户端可以不做静态地址配置。发现密钥可显式给，也可从 `auth_token` 派生（两端一致）：

~~~python
from qmt_client import QMTClient, QMTDiscovery

client = QMTClient.discover()                                 # token 取 QMT_AUTH_TOKEN，密钥自动派生
client = QMTClient.discover(secret="<discovery_secret>")      # 或显式指定

for service in QMTDiscovery(token="<auth_token>").discover(): # 只取候选列表
    print(service.host, service.port, service.account_type)
~~~

发现基于 HMAC 签名的 UDP 主动探测，结果默认缓存 `30s`（`cache_ttl=0` 可关闭），未签名应答一律不采信。

### 命令行发现

安装后提供 `qmt-discover`：

~~~bash
qmt-discover --token "$QMT_AUTH_TOKEN"                        # 用 token 派生密钥，发现并验证
qmt-discover --secret "$QMT_DISCOVERY_SECRET"                 # 或显式密钥
qmt-discover --token ... --broadcast 192.168.1.255 --json     # 多网卡：指定子网广播地址
qmt-discover --token ... --broadcast auto                     # /24 子网广播自动推导（启发式）
qmt-discover --token ... --first                              # 第一个应答就返回
~~~

退出码：`0` 有可用 server，`1` 无候选或未通过验证，`2` 参数错误。`--account-type STOCK` 可过滤账号类型，`--cache-ttl` 控制结果缓存。

## 方法一览

| 方法 | 端点 |
| --- | --- |
| `root()` | `GET /` |
| `health()` | `GET /health` |
| `accounts()` | `GET /accounts` |
| `positions()` | `GET /positions` |
| `quotes()` | `GET /quotes` |
| `quote(symbol)` | `GET /quote` |
| `subscribe(symbol)` / `unsubscribe(symbol)` | `GET /subscribe` / `GET /unsubscribe` |
| `orders(...)` / `deals(...)` | `GET /orders` / `GET /deals` |
| `signals(symbol)` | `GET /signals` |
| `place_order(...)` | `GET /order` |
| `cancel_order(order_id, ...)` | `GET /cancel` |
| `can_cancel_order(order_id)` | `GET /can-cancel` |
| `candles(...)` | `GET /candles` |
| `candles_bulk(symbols, ...)` | `GET /candles-bulk` |
| `instrument(symbol)` / `instrument_bulk(symbols)` | `GET /instrument` / `GET /instrument-bulk` |
| `divid_factors(symbols, ...)` | `GET /divid-factors` |
| `turnover_rate(symbols, ...)` | `GET /turnover-rate` |
| `total_share(symbols)` | `GET /total-share` |
| `trading_dates(symbol, ...)` | `GET /trading-dates` |
| `sector(name, ...)` | `GET /sector` |
| `options(underlying, date, ...)` | `GET /options` |
| `option_trade_options()` | `GET /option-trade-options` |
| `longhubang(symbol, ...)` | `GET /longhubang` |
| `debug_trade()` | `GET /debug/trade` |
| `quote_stream(...)` | `ws://.../ws` |

### 下单

~~~python
result = client.place_order(
    symbol="600000.SH",
    side="BUY",
    price=10.5,
    volume=100,
    price_type=None,      # 默认限价(11)；也可传 "MARKET" / 18
    remark="my-strategy",
    batch_id="batch-0001",
    source="django",
)
~~~

注意：@@/order@@ 只在 QMT **实盘运行**下真正报单——回测模式只记虚拟买卖点，模拟模式交易函数无效；
@@status=submitted@@ 仅表示 @@passorder@@ 未抛异常。它是有副作用的非幂等请求，客户端不会自动重试。

### 撤单

~~~python
orders = client.orders(symbol="600000.SH", limit=50)
order_id = QMTClient.order_id_of(orders["orders"][-1])   # 委托号 order_sys_id，即 m_strOrderSysID

if client.can_cancel_order(order_id)["can_cancel"]:
    client.cancel_order(order_id)             # 非幂等，客户端不做自动重试
~~~

## 行情订阅（WebSocket）

后台线程 + 自动重连，适合 Django 这类同步调用方：

~~~python
stream = client.quote_stream(ping_interval=2.0)

def handle(snapshot):
    print(snapshot["quote_count"], snapshot["quotes"])

stream.start(on_snapshot=handle)
# ... 做别的事 ...
stream.stop()
~~~

阻塞迭代器风格：

~~~python
for snapshot in client.quote_stream().iter_quotes():
    process(snapshot)
~~~

关键点：服务端 5 秒无活动即断开，而且自己从不发 ping。客户端会在 `recv` 超时时发送心跳帧保持连接，断线后按指数退避自动重连。`ping_interval` 必须小于 5 秒（默认 2 秒）。

## 错误处理

~~~python
from qmt_client import (
    QMTAuthError, QMTHostError, QMTAPIError, QMTOrderRejected, QMTTransportError,
)

try:
    client.positions()
except QMTAuthError:
    ...        # 401：token 不正确，或服务端未配置 auth_token
except QMTHostError:
    ...        # 403：Host 不在白名单
except QMTAPIError as exc:
    ...        # 业务错误：非 2xx，或 HTTP 200 但 body 里带 error
except QMTTransportError:
    ...        # 连接失败 / 超时 / 非 JSON
~~~

服务端很多端点在 HTTP 200 的 body 里返回 `error`（例如 `/candles` 的 `get_market_data_failed`），客户端会统一抛出 `QMTAPIError`，不会静默返回空数据。下单失败会抛 `QMTOrderRejected`，其 `error` 是服务端原因（`notional_limit_exceeded`、`order_rate_limited` 等）。

## 与 server 交互时的注意事项

- `/order` 与 `/cancel` 都非幂等：客户端对二者禁用自动重试，失败后是否重试由调用方决定。
- `cancel_order(order_id)` 的 `order_id` 是委托号（`/orders` 的 `order_sys_id`，即 QMT `m_strOrderSysID`），不是 `m_nOrderID`；可用 `QMTClient.order_id_of(record)` 提取。
- 批量方法（`candles_bulk` / `instrument_bulk` / `divid_factors` / `turnover_rate` / `total_share`）会按 `batch_size`（默认 300）分批请求并合并结果。
- 服务端每个响应都带 `Connection: close`，没有 keep-alive，客户端不要指望连接复用。
- 当前服务端 `/options` 忽略 `with_iv` / `with_quote` / `auto_subscribe` 并强制为 True，因此本客户端未暴露这些开关。
- `place_order()` 的返回体包含 `account_before` / `debug_before` 等账号信息，不要原样写日志。
- 客户端只在连接层错误（ConnectionError / Timeout）时重试，不对 HTTP 状态码重试。
- `cancel_order()` / `can_cancel_order()` 依赖主仓 `server.py` 新增的 `/cancel`、`/can-cancel` 端点；对旧版 server 会得到 `not_found`。

## 测试

~~~bash
python3 -m pytest -q
~~~

- `test_client.py` / `test_stream.py`：用标准库起的假 HTTP / WebSocket 服务做单元测试，不依赖 QMT。
- `test_e2e_fake_qmt.py`：若存在 `server/` 与 `devtools/`（默认同仓 `../server`、`../devtools`，
  可用 `QMT_SERVER_DIR` / `QMT_DEVTOOLS_DIR` 指定），会启动 FakeQMT（真实 `server.py` + 假 QMT 环境）跑通完整链路；否则自动跳过。
