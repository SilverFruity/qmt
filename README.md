# QMT HTTP / WebSocket 服务

## 目的
- 在 QMT 策略脚本环境内启动一个本地 HTTP / WebSocket 服务。
- 对外暴露持仓、账户、委托、成交、行情、K 线、信号点和下单能力。
- 让外部程序通过 `127.0.0.1:18080` 与 QMT 交互，而不必直接运行在 QMT 的 Python 解释器里。

## 项目边界
- `server/` 内的 Python 代码只依赖标准库和同目录模块，运行时依赖 QMT 提供的 `ContextInfo`、`run_time(...)`、`get_trade_detail_data(...)`、行情订阅等接口。
- `client/` 是可选的 Python 客户端包（依赖 `requests` / `websocket-client`），供外部程序调用本服务，不参与 QMT 运行时。
- `docs/` 下是 QMT 官方文档的提取与导航，供查 API 使用，不是本项目自己的部署文档。

## 目录说明

仓库分为 `server/`（QMT 策略内运行）与 `client/`（外部 Python 客户端）两部分。

### server/
- `loader.py`：复制到 QMT 策略脚本目录，由 QMT 调用；负责热加载 `server.py`
- `server.py`：HTTP / WebSocket 服务主入口
- `server_http_utils.py`：HTTP / WebSocket 握手与帧工具
- `server_market_utils.py`：行情、K 线、龙虎榜、信号点整理
- `server_fundamental_utils.py`：复权因子、批量标的、换手率、股本、交易日历、板块成分
- `server_socket_utils.py`：非阻塞 socket 轮询
- `server_runtime_utils.py`：运行时状态与序列化工具
- `server_config.json.example`：示例配置；`server_config.json` 为本地真实配置，不应提交到仓库
- `server_openapi.py`：OpenAPI 3.0 规范（纯标准库，`/openapi.json` 与 `/docs` 的数据源）

### devtools/（不参与部署）

- `fake_qmt/`：假 QMT 环境（`ContextInfo` / QMT 全局函数 / 内存账户），仅开发与测试使用
- `run_fake_qmt.py`：在本机加载真实 `server/server.py` 的命令行入口
- `export_openapi.py`：把 OpenAPI 规范导出成 `openapi.json`，便于导入 Postman 等工具
- `e2e/`：跨端点 Docker E2E（两个容器分别跑真实 server 与 client），用法见 `devtools/e2e/README.md`

### client/
- `pyproject.toml`：`qmt-client` 包定义（`pip install -e client`）
- `src/qmt_client/`：`QMTClient`（HTTP 同步）与 `QuoteStream`（WebSocket 行情订阅）
- `tests/`：单元测试，以及针对真实 `server.py` + FakeQMT 的端到端测试
- `README.md`：客户端用法与接口映射

### 其他
- `docs/`：QMT 文档索引与提取内容
- `requirements.txt`：说明文件（server 侧仅标准库）

## 运行前提
- Windows 环境
- QMT 策略脚本模式
- `loader.py` 和 `server.py` 语法需兼容 Python 3.6.8
- QMT 已能正常调用 `init / after_init / handlebar / run_time / 回调函数`

## 依赖
- 本项目自身不依赖额外 pip 包。
- 运行依赖来自 QMT 内置环境，因此 `requirements.txt` 仅作为说明文件保留。

## 部署方式

1. QMT GUI新建策略，然后将 `loader.py` 的内容复制到策略中，保存。
2. 将仓库 `server/` 目录下的 `server.py`、`server_*_utils.py`、`server_config.json`（由 `.example` 复制而来）放到 `C:\server\`。
3. 启动 QMT 策略（可以设置为随GUI启动）。

`loader.py` 会按以下顺序寻找 `server.py`：
- 环境变量 `QMT_WATCH_DIR`
- `C:\server`
- `loader.py` 所在目录

### 自定义路径
- 可通过环境变量 `QMT_WATCH_DIR` 指向 `server.py` 所在目录。
- 目录中至少需要包含：
  - `server.py`
  - `server_http_utils.py`
  - `server_market_utils.py`
  - `server_fundamental_utils.py`
  - `server_runtime_utils.py`
  - `server_socket_utils.py`

## 局域网部署

默认只监听 `127.0.0.1`。要让局域网内的客户端直连，改 `server/server_config.json`：

```json
{
  "bind_host": "192.168.1.20",
  "bind_port": 18080,
  "allowed_hosts": ["192.168.1.20:18080", "qmt.lan:18080"]
}
```

- `bind_host` 填本机在局域网中的网卡 IP；`0.0.0.0` 表示所有网卡。
- `allowed_hosts` 是 **Host 头白名单**，必须包含客户端实际使用的主机名/IP（带端口）。若用 `0.0.0.0` 而
  不写 `allowed_hosts`，局域网请求会被 403 拒绝（回环仍可用）。
- 保存即生效，配置热加载会自动重建监听。
- 客户端侧无需改动：`QMTClient(host="192.168.1.20", port=18080)`，或设 `QMT_HOST` / `QMT_PORT`。

### 安全须知（明文）

局域网直连意味着传输是**明文 HTTP/WS**：

- token 放在 `Authorization` 头里明文传输，可被同网段的嗅探 / ARP 欺骗截获；**拿到 token 就能下真实委托、撤单**。
- Host 白名单只防 DNS rebinding，**不是鉴权**，不要当作访问控制。
- 建议：只在隔离网段或 VPN 内使用，并用防火墙只放行客户端 IP 到该端口；更稳妥的是加一层 TLS 反向代理
  （nginx / Caddy / stunnel），服务端仍监听 `127.0.0.1`，由代理对外提供 https/wss。
- 当前只靠 token、不限来源 IP，所以 token 强度是关键：用
  `python -c "import secrets;print(secrets.token_urlsafe(40))"` 生成并定期轮换。

## 服务发现（局域网）

客户端可以不做静态地址配置，通过 **HMAC 签名的 UDP 主动探测** 找到 server：

- 客户端向广播地址的发现端口发 probe：`{"service":"qmt","probe":1,"nonce":...,"ts":...,"sig":...}`
- 服务端校验签名后**单播**回：`{"service":"qmt","version":1,"http_port":...,"account_type":...,"nonce":...,"ts":...,"sig":...}`
- 客户端以数据包来源地址作为 server 地址（因此 `bind_host` 填 `0.0.0.0` 也能发现），验签通过后再用 token 调 `/health` 复核，返回可用的客户端。

配置（`server_config.json`），二选一：

```json
{
  "discovery_enabled": true,
  "discovery_port": 18081,
  "discovery_secret": ""
}
```

- `discovery_secret` 留空且 `discovery_enabled=true` 时，服务端用
  `HMAC-SHA256(auth_token, 'qmt-discovery-v1')` **派生**发现密钥，客户端同样派生——
  **只维护 `auth_token` 一份密钥**；`/health` 的 `discovery_secret_source` 显示 `derived` 或 `explicit`。
- 也可以显式填 `discovery_secret`（客户端用 `QMT_DISCOVERY_SECRET` 对齐），便于单独轮换。
- **既没有 `discovery_secret` 又没有派生来源时不对外发现**（fail-closed）；未签名的应答一律不被信任。
- 密钥只用于签名/验签，**不会**出现在日志或 `/health` 中。
- 探针与应答都带 `ts`，超出时间窗（默认 300s）丢弃，降低重放风险。
- 发现端口是 UDP，注意防火墙放行。

客户端用法：

```python
from qmt_client import QMTClient, QMTDiscovery

client = QMTClient.discover()                 # token 取 QMT_AUTH_TOKEN，密钥自动派生
client = QMTClient.discover(secret="...")     # 或显式给 discovery_secret

for service in QMTDiscovery(token="...").discover():
    print(service.host, service.port, service.account_type)
```

也可以直接用命令行工具 `qmt-discover`（安装 `client` 后可用）：`qmt-discover --token "$QMT_AUTH_TOKEN" --broadcast auto`。

## 配置
1. 将 `server/server_config.json.example` 复制为 `server/server_config.json`
2. 按本机账户与订阅需求填写

示例字段：
- `account_id`：账户号；如果 `ContextInfo` 能自动识别，可留空
- `account_type`：默认 `STOCK`
- `auth_token`：访问令牌，**必填**。为空时服务器拒绝所有请求（fail-closed），不要留空来“关闭鉴权”
- `bind_host`：监听地址，默认 `127.0.0.1`；局域网改为本机网卡 IP 或 `0.0.0.0`
- `bind_port`：监听端口，默认 `18080`
- `allowed_hosts`：Host 头白名单（见下文「局域网部署」）
- `quote_symbols`：启动时自动订阅的行情代码
- `quote_period`：默认 `tick`
- `quote_dividend_type`：默认 `none`

注意：
- `server_config.json` 是本地环境文件，不应提交到仓库。
- 示例里的 `_comments` 字段只作说明，服务端只读取已知键，会忽略它。
- 示例是「局域网开箱即用」取向：`bind_host: 0.0.0.0`、`allowed_hosts: ["*"]`、`discovery_enabled: true`，且
  `auth_token` 只是占位符 `auth_token`（发现密钥由它派生）。**上线前务必替换 `auth_token`**；
  要保留 Host 防护就把 `allowed_hosts` 改成客户端实际使用的 `IP:端口` 列表，或把 `discovery_secret` 设为独立密钥。
- 当前代码会热加载 `server_config.json`，修改后无需重启 Python 进程即可生效。

## 鉴权
本服务能提交真实委托，因此鉴权是 **fail-closed** 的：

- `auth_token` 为空（或配置文件读取失败）：**拒绝所有请求**，返回 `401 {"error":"unauthorized"}`
- `auth_token` 非空，以下任一方式通过即可：
  - HTTP `Authorization: Bearer <token>`
  - HTTP `X-QMT-Token: <token>`
  - WebSocket 握手支持上述 Header
  - WebSocket 也支持 `Sec-WebSocket-Protocol: qmt-token.<token>`

令牌比较使用 `hmac.compare_digest`，避免时序侧信道。

调用方（algo_monitor 的 Django 后端）从 `config.yaml` 的 `qmt_auth_token` 或环境变量
`QMT_AUTH_TOKEN` 读取同一个令牌，两边必须一致。

### 其他访问控制
- **Host 白名单**：默认只接受 `127.0.0.1[:18080]` / `localhost[:18080]`；可用 `allowed_hosts` 扩展，
  其他 Host 返回 `403 {"error":"host_not_allowed"}`，用于阻断 DNS rebinding。
  设为 `["*"]`（或 `["any"]`）可**完全关闭**该检查——会失去 DNS rebinding 防护，只在完全可信网络里用；
  `/health` 的 `host_check_enabled` 会显示当前是否生效
- **不返回任何 CORS 头**（`CORS_ALLOW_ORIGIN = ''`）：唯一调用方是同机的 Django 后端，
  不需要浏览器跨域；一旦返回 `Access-Control-Allow-Origin: *`，本机浏览器打开的任意
  网页都能读账户并调用 `/order`

### 下单限额
`server.py` 顶部的常量对每一笔委托做硬性约束，超限直接拒绝并记入 `/health`：

- `MAX_ORDER_NOTIONAL`（单笔金额上限，默认 200000）
- `MAX_ORDER_VOLUME`（单笔数量上限，默认 100000）
- `MAX_ORDERS_PER_MINUTE`（每分钟报单数上限，默认 30）
- `MAX_CANCELS_PER_MINUTE`（每分钟撤单数上限，默认 60）

建议：
- 令牌用 `python -c "import secrets;print(secrets.token_urlsafe(40))"` 生成
- 不要把真实 `server_config.json` 或令牌提交到仓库
- NAS 日更 **不直连** 本服务，只打 Django `/api/ingest/qmt/...`（Bearer `ALGO_MONITOR_API_TOKEN`）；Django 再用本段 `QMT_AUTH_TOKEN` 调 `127.0.0.1:18080`
- 在 benben 上探测本服务时用 `curl.exe`（PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名，会挂死无输出）：

```powershell
curl.exe -s --max-time 10 -H "Authorization: Bearer <auth_token>" http://127.0.0.1:18080/health
```

公网 `https://benben.cafe/qmt/` 是 Django staff 代理，未登录 401，不是本端口。

## 运行机制
- 默认监听 `127.0.0.1:18080`
- 不启动阻塞线程，而是通过 `ContextInfo.run_time("server_tick", "10nMilliSecond", ...)` 驱动非阻塞 socket 轮询
- `handlebar` 保留为策略语义入口
- `server_tick` 专门处理 HTTP / WebSocket 轮询
- 持仓、委托、成交、行情快照都会缓存在运行时状态中

## 本地 FakeQMT（macOS 开发 / 测试）

没有 Windows / QMT 时，可以用 `devtools/fake_qmt` 在本机加载**真实的 `server/server.py`**：它注入假的 QMT 全局函数
（`passorder` / `cancel` / `can_cancel_order` / `get_trade_detail_data`）和一个假的
`ContextInfo`（行情订阅、`get_market_data`、复权因子、板块、期权等），并自行驱动
`init / after_init / server_tick`。因此 HTTP / WebSocket 行为与真机一致，只有交易与行情是模拟的。

```bash
cd devtools
python3 run_fake_qmt.py --port 18080 --token dev-token
curl -s -H "Authorization: Bearer dev-token" http://127.0.0.1:18080/health
```

组成（`devtools/` 下）：

- `fake_qmt/store.py`：内存账户 / 持仓 / 委托 / 成交，支持下单、撤单、可撤查询
- `fake_qmt/context.py`：`ContextInfo` 假实现（订阅行情、K 线、基本面、期权、龙虎榜）
- `fake_qmt/globals.py`：注入 `server.py` 命名空间的 QMT 全局函数
- `fake_qmt/runner.py`：加载并驱动真实 `server.py` 的 `FakeQMTServer`，默认指向同仓 `server/`
- `run_fake_qmt.py`：命令行入口（`--port` / `--token` / `--discovery-secret` 等）

它**不在部署范围内**：`server/` 里没有任何代码 import 它。`client/tests/test_e2e_fake_qmt.py` 会用它启动真实
`server.py` 跑端到端测试（找不到 `server/` 或 `devtools/` 时自动跳过）。

## API 文档（OpenAPI / Swagger）

服务端内置一份 OpenAPI 3.0 规范（`server/server_openapi.py`），与路由同源维护：

- `GET /openapi.json`：规范本身（**无需鉴权**，仅受 Host 白名单约束）
- `GET /docs`：Swagger UI 页面（**无需鉴权**），顶部可填 `auth_token` 用于 Try it out

```bash
open http://127.0.0.1:18080/docs
```

`/docs` 的前端资源默认走 `https://unpkg.com/swagger-ui-dist@5`；离线环境可用环境变量
`QMT_SWAGGER_UI_BASE` 指向本地 swagger-ui-dist 目录（例如 `file:///C:/swagger-ui-dist` 或内网静态站）。

不启动服务也可以直接导出规范：

```bash
cd server
python3 export_openapi.py > openapi.json
```

安全说明：只放行 `/docs` 与 `/openapi.json` 两个只读文档端点，二者不含任何账户或委托数据；
其余接口仍然 fail-closed 需要令牌。`client/tests/test_e2e_openapi.py` 会校验规范路径与
`/` 返回的端点列表一致，防止二者漂移。

## HTTP / WebSocket 接口

### 状态与基础信息
- `GET /`：服务名、模式、公开端点列表
- `GET /health`：运行状态、配置状态、最近错误、订阅状态
- `GET /accounts`：账户信息
- `GET /positions`：持仓信息

### 行情与订阅
- `GET /quotes`：当前缓存的全部行情
- `GET /quote?symbol=000300.SH`：单个标的行情
- `GET /subscribe?symbol=000300.SH`：手动加入订阅列表
- `GET /unsubscribe?symbol=000300.SH`：手动移除订阅列表
- `GET /ws`：WebSocket 行情推送，推送类型为 `quote_snapshot`

### 交易与成交
- `GET /orders`：委托列表；支持 `symbol`、`strategy_name`、`remark`、`limit`
- `GET /deals`：成交列表；支持 `symbol`、`strategy_name`、`remark`、`limit`
- `GET /signals?symbol=000300.SH`：从成交记录推导买卖点、最低买入价、最高买入价
- `GET /order?...`：提交股票下单请求；关键参数：
  - `symbol`
  - `side=BUY|SELL`
  - `price`
  - `volume`
  - `price_type`
  - `remark`
  - `batch_id`
  - `source`
- `GET /cancel?order_id=...`：撤销单笔委托；`order_id` 为委托号（`/orders` 返回的
  `order_sys_id`，即 QMT `m_strOrderSysID`），可选 `account_type`，也接受 `order_sys_id`
- `GET /can-cancel?order_id=...`：查询委托是否可撤销，返回 `can_cancel` 布尔值

说明：
- **运行模式决定一切**：`/order`、`/cancel`、`/can-cancel` 只在 QMT **实盘运行**下有意义。
  **回测模式**中交易函数调用虚拟账号、只在历史 K 线上记买卖点，`/order` 不会产生真实委托，`/cancel`/`/can-cancel` 无实际意义；
  **模拟运行模式下交易函数无效**。
- `status: submitted` 只代表 `passorder` 未抛异常，**不代表柜台已受理**；是否成功以 `/orders`、`/deals` 为准。
- `/cancel` 与 `/order` 一样受每分钟次数限制；`signaled` 表示是否已发出撤销信号；`order_id` 用 `/orders` 返回的 `order_sys_id`。
- 服务端在 `server_tick`（`run_time` 定时器）里调用 `passorder`，不在 `handlebar` 内，因此使用 `quickTrade=2`（不判断 bar 状态）：
  **实盘运行下 API 调用即触发报单**（下单即挂单）；回测/模拟下仍不会产生真实委托。

### K 线、标的信息与期权
- `GET /candles?symbol=000300.SH&period=1d&count=240`：K 线
- `GET /candles-bulk?symbols=600000.SH,000001.SZ&period=1d&start=&end=`：批量日 K（NAS ingest 经 Django 转发）
- `GET /instrument?symbol=000300.SH`：标的基本信息
- `GET /instrument-bulk?symbols=600000.SH,000001.SZ`：批量标的信息
- `GET /divid-factors?symbols=...&start=&end=`：复权因子
- `GET /turnover-rate?symbols=...&start=&end=`：换手率
- `GET /total-share?symbols=...`：总股本
- `GET /trading-dates?symbol=000001.SZ&start=&end=`：交易日历
- `GET /sector?name=沪深300`：板块 / 指数成分
- `GET /options?...`：期权列表与可选附加信息
- `GET /option-trade-options`：期权交易相关选项

### 其他数据
- `GET /longhubang?symbol=000300.SH&start=YYYYMMDD&end=YYYYMMDD`：龙虎榜数据
- `GET /debug/trade`：聚合调试视图，返回 health / accounts / positions / orders / deals / quotes / signals

## 常见问题

### 找不到 `server.py`
- 优先检查 `QMT_WATCH_DIR`
- 如果未设置，检查 `C:\server\server.py` 是否存在
- 再检查 `loader.py` 同目录是否有 `server.py`

### 修改配置后不生效
- `server_config.json` 依赖文件修改时间触发热加载
- 先确认写入的确是 `loader.py` 当前监听目录中的配置文件

### 外部程序连不上
- 检查 QMT 策略是否已启动
- 检查本机 `127.0.0.1:18080` 是否被监听
- 远程请用 `curl.exe`，不要用 `curl`
- 401：缺 Bearer / `X-QMT-Token`，或 `auth_token` 为空（fail-closed）
- 403 `host_not_allowed`（局域网）：`allowed_hosts` 未包含客户端使用的 IP/主机名
- 局域网连不上：核对 `bind_host`、`allowed_hosts`，以及防火墙是否放行 `bind_port`
- 查看 `/health` 输出中的 `last_error`、`listener_ready`、`account_source`

### 订阅没有推送
- 先调用 `/subscribe`
- 检查 `/quotes` 是否已有缓存
- 检查账户持仓和 `quote_symbols` 是否为空

## 发布卫生
- 不提交真实 `server_config.json`
- 不提交日志、缓存和 `__pycache__/`
- 对外发布 server 侧时至少包含：
  - `server/loader.py`
  - `server/server.py`
  - `server/server_*_utils.py`
  - `server/server_config.json.example`
  - `README.md`
  - `docs/`（可选，作为 QMT API 参考）
- 客户端可单独发布：`pip install ./client`
- **部署到 QMT 机器的只有 `server/` 下的运行文件**（`server.py`、`server_*_utils.py`、`server_config.json`）；
  `devtools/`、`client/`、`docs/` 都不要拷进 `C:\server\`
