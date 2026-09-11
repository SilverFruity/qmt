# -*- coding: utf-8 -*-
"""OpenAPI 3.0 description of the QMT HTTP server.

Standard library only and Python 3.6 compatible, so server.py can serve it from
inside QMT with no extra packages. Keep the paths here in sync with the route
dispatch in server.py; client/tests/test_e2e_openapi.py asserts that.
"""

import os

API_TITLE = 'QMT HTTP / WebSocket 服务'
API_VERSION = '1.0.0'
# Relative so Swagger UI targets whatever host the page was opened from
# (loopback or a LAN address); absolute would break Try it out over LAN.
SERVER_BASE_URL = '/'
SWAGGER_UI_ASSET_BASE = os.environ.get('QMT_SWAGGER_UI_BASE') or 'https://unpkg.com/swagger-ui-dist@5'

_JSON = 'application/json'

STRING = {'type': 'string'}
INTEGER = {'type': 'integer'}
NUMBER = {'type': 'number'}
LOOSE_OBJECT = {'type': 'object', 'additionalProperties': True}
SYMBOL = {'type': 'string', 'description': '标的代码，形如 600000.SH', 'example': '600000.SH'}
SYMBOLS = {'type': 'string', 'description': '逗号分隔的标的列表', 'example': '600000.SH,000001.SZ'}
BOOL_FLAG = {'type': 'string', 'enum': ['0', '1', 'true', 'false', 'yes', 'no'], 'description': '布尔开关'}
SIDE = {'type': 'string', 'enum': ['BUY', 'SELL']}
DATE = {'type': 'string', 'description': 'YYYYMMDD', 'example': '20240101'}
DATETIME = {'type': 'string', 'description': 'YYYYMMDDHHMMSS', 'example': '20240102093000'}

SWAGGER_UI_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>QMT API 文档</title>
<link rel="stylesheet" href="__ASSET_BASE__/swagger-ui.css"/>
<style>
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  #qmt-bar { position: sticky; top: 0; z-index: 10; display: flex; gap: 8px; align-items: center;
             padding: 10px 16px; background: #1b1b1f; color: #eee; flex-wrap: wrap; }
  #qmt-bar input { flex: 0 0 320px; padding: 6px 8px; border-radius: 4px; border: 1px solid #555;
                   background: #2a2a2f; color: #eee; }
  #qmt-bar button { padding: 6px 14px; border-radius: 4px; border: 0; background: #4990e2; color: #fff; cursor: pointer; }
  #qmt-bar span { font-size: 12px; color: #aaa; }
</style>
</head>
<body>
<div id="qmt-bar">
  <strong>QMT</strong>
  <input id="qmt-token" type="password" placeholder="auth_token" autocomplete="off"/>
  <button id="qmt-apply">应用令牌</button>
  <span>令牌仅存于本页 sessionStorage，用于 Try it out；接口本身 fail-closed。</span>
</div>
<div id="swagger-ui"></div>
<script src="__ASSET_BASE__/swagger-ui-bundle.js"></script>
<script>
(function () {
  var KEY = 'qmt_auth_token';
  var input = document.getElementById('qmt-token');
  input.value = sessionStorage.getItem(KEY) || '';
  document.getElementById('qmt-apply').onclick = function () {
    sessionStorage.setItem(KEY, input.value.trim());
    document.getElementById('qmt-apply').textContent = '已应用';
  };
  function interceptor(request) {
    var token = sessionStorage.getItem(KEY);
    if (token) {
      request.headers['Authorization'] = 'Bearer ' + token;
    }
    return request;
  }
  window.ui = SwaggerUIBundle({
    url: '/openapi.json',
    dom_id: '#swagger-ui',
    deepLinking: true,
    persistAuthorization: true,
    requestInterceptor: interceptor
  });
})();
</script>
</body>
</html>
'''


def build_swagger_ui_html(asset_base=None):
    base = (asset_base or SWAGGER_UI_ASSET_BASE).rstrip('/')
    return SWAGGER_UI_HTML.replace('__ASSET_BASE__', base)


def _q(name, description, schema=None, required=False):
    return {
        'name': name,
        'in': 'query',
        'required': bool(required),
        'description': description,
        'schema': schema or dict(STRING),
    }


def _ref(name):
    return {'$ref': '#/components/schemas/%s' % name}


def _json_ok(description, schema=None):
    return {
        'description': description,
        'content': {_JSON: {'schema': schema or dict(LOOSE_OBJECT)}},
    }


def _error_responses():
    return {
        '400': _json_ok('参数错误或业务拒绝', _ref('Error')),
        '401': _json_ok('未鉴权（fail-closed）', _ref('Error')),
        '403': _json_ok('Host 不在白名单', _ref('Error')),
        '404': _json_ok('路径不存在', _ref('Error')),
        '405': _json_ok('方法不允许', _ref('Error')),
        '500': _json_ok('服务器内部错误', _ref('Error')),
    }


def _op(tag, summary, parameters=None, schema=None, description='成功', security=None):
    responses = {'200': _json_ok(description, schema)}
    responses.update(_error_responses())
    operation = {
        'tags': [tag],
        'summary': summary,
        'parameters': parameters or [],
        'responses': responses,
    }
    if security is not None:
        operation['security'] = security
    return operation


def _paths():
    return {
        '/': {'get': _op('状态', '服务名、模式与公开端点列表')},
        '/health': {'get': _op('状态', '运行状态、配置状态、最近错误与订阅状态', schema=_ref('Health'))},
        '/accounts': {'get': _op('状态', '账户信息与最近一次账户快照')},
        '/positions': {'get': _op('状态', '当前持仓列表')},

        '/quotes': {'get': _op('行情', '当前缓存的全部行情快照')},
        '/quote': {'get': _op('行情', '单个标的的行情快照', [
            _q('symbol', '标的代码', SYMBOL, required=True),
        ])},
        '/subscribe': {'get': _op('行情', '手动加入行情订阅列表', [
            _q('symbol', '标的代码', SYMBOL, required=True),
        ])},
        '/unsubscribe': {'get': _op('行情', '手动移除行情订阅列表', [
            _q('symbol', '标的代码', SYMBOL, required=True),
        ])},

        '/orders': {'get': _op('交易', '委托列表', [
            _q('symbol', '按标的过滤', SYMBOL),
            _q('strategy_name', '按备注中的策略名过滤', STRING),
            _q('remark', '按备注过滤', STRING),
            _q('limit', '最多返回条数，默认 200', INTEGER),
        ])},
        '/deals': {'get': _op('交易', '成交列表', [
            _q('symbol', '按标的过滤', SYMBOL),
            _q('strategy_name', '按备注中的策略名过滤', STRING),
            _q('remark', '按备注过滤', STRING),
            _q('limit', '最多返回条数，默认 200', INTEGER),
        ])},
        '/signals': {'get': _op('交易', '从成交记录推导买卖点与买入价区间', [
            _q('symbol', '不传则返回全部标的', SYMBOL),
        ], schema=_ref('Signals'))},
        '/order': {'get': _op('交易', '提交股票下单请求（非幂等）', [
            _q('symbol', '标的代码', SYMBOL, required=True),
            _q('side', '买卖方向', SIDE, required=True),
            _q('price', '委托价格，需大于 0', NUMBER, required=True),
            _q('volume', '委托数量，需大于 0', INTEGER, required=True),
            _q('price_type', '价格类型：LIMIT/FIX=11，MARKET/BEST=18，或直接传数字', {'type': 'string', 'example': 'LIMIT'}),
            _q('remark', '备注', STRING),
            _q('batch_id', '调用方批次号，用于串联', STRING),
            _q('source', '调用来源标识', STRING),
        ], schema=_ref('OrderSubmitResult'))},
        '/cancel': {'get': _op('交易', '撤销单笔委托（非幂等）', [
            _q('order_id', '委托号，即 /orders 的 order_sys_id（QMT m_strOrderSysID）', STRING, required=True),
            _q('order_sys_id', 'order_id 的别名', STRING),
            _q('account_type', '账号类型，默认取运行时配置', STRING),
        ], schema=_ref('CancelResult'))},
        '/can-cancel': {'get': _op('交易', '查询委托是否可撤销', [
            _q('order_id', '委托号，即 /orders 的 order_sys_id', STRING, required=True),
            _q('account_type', '账号类型，默认取运行时配置', STRING),
        ], schema=_ref('CanCancelResult'))},

        '/candles': {'get': _op('数据', '单个标的 K 线', [
            _q('symbol', '标的代码', SYMBOL, required=True),
            _q('period', '周期，如 1d / 1m / tick，默认 1d', {'type': 'string', 'default': '1d'}),
            _q('count', 'K 线数量，默认 240', INTEGER),
            _q('start', '开始时间', DATE),
            _q('end', '结束时间', DATE),
            _q('dividend_type', '复权方式，如 none / front_ratio', STRING),
        ])},
        '/candles-bulk': {'get': _op('数据', '批量 K 线，服务端按 300 只分批', [
            _q('symbols', '逗号分隔的标的列表', SYMBOLS, required=True),
            _q('period', '周期，默认 1d', {'type': 'string', 'default': '1d'}),
            _q('start', '开始时间', DATE),
            _q('end', '结束时间', DATE),
            _q('dividend_type', '复权方式，默认 none', {'type': 'string', 'default': 'none'}),
        ])},
        '/instrument': {'get': _op('数据', '单个标的基本信息', [
            _q('symbol', '标的代码', SYMBOL, required=True),
        ])},
        '/instrument-bulk': {'get': _op('数据', '批量标的基本信息', [
            _q('symbols', '逗号分隔的标的列表', SYMBOLS, required=True),
        ])},
        '/divid-factors': {'get': _op('数据', '批量复权因子', [
            _q('symbols', '逗号分隔的标的列表', SYMBOLS, required=True),
            _q('start', '开始日期', DATE),
            _q('end', '结束日期', DATE),
        ])},
        '/turnover-rate': {'get': _op('数据', '批量换手率', [
            _q('symbols', '逗号分隔的标的列表', SYMBOLS, required=True),
            _q('start', '开始日期', DATE),
            _q('end', '结束日期', DATE),
        ])},
        '/total-share': {'get': _op('数据', '批量总股本', [
            _q('symbols', '逗号分隔的标的列表', SYMBOLS, required=True),
        ])},
        '/trading-dates': {'get': _op('数据', '交易日历', [
            _q('symbol', '标的代码', SYMBOL, required=True),
            _q('start', '开始日期', DATE),
            _q('end', '结束日期', DATE),
            _q('count', '返回数量', INTEGER),
            _q('period', '周期，默认 1d', {'type': 'string', 'default': '1d'}),
        ])},
        '/sector': {'get': _op('数据', '板块 / 指数成分', [
            _q('name', '板块或指数名称', STRING, required=True),
            _q('with_weight', '是否返回权重', BOOL_FLAG),
            _q('index_code', '权重对应的指数代码', STRING),
            _q('realtime', 'realtime 参数，透传 QMT', INTEGER),
        ])},
        '/options': {'get': _op('数据', '期权列表（服务端强制附带详情 / IV / 行情）', [
            _q('underlying', '标的代码', SYMBOL, required=True),
            _q('date', '到期月份或日期，YYYYMM 或 YYYYMMDD', STRING, required=True),
            _q('type', 'CALL / PUT，空为全部', {'type': 'string', 'enum': ['CALL', 'PUT', '']}),
            _q('available', '是否仅可交易', BOOL_FLAG),
            _q('limit', '最多返回条数，默认 200', INTEGER),
            _q('sort', '排序：strike_asc / strike_desc / expire_asc', {'type': 'string', 'default': 'strike_asc'}),
        ])},
        '/option-trade-options': {'get': _op('数据', '期权交易动作常量表')},
        '/longhubang': {'get': _op('数据', '龙虎榜数据', [
            _q('symbol', '标的代码', SYMBOL, required=True),
            _q('start', '开始日期，默认今天', DATE),
            _q('end', '结束日期，默认今天', DATE),
        ])},
        '/debug/trade': {'get': _op('状态', '聚合调试视图：health/accounts/positions/orders/deals/quotes/signals')},

        '/openapi.json': {'get': _op('文档', '本 OpenAPI 文档（无需鉴权）', security=[], schema=LOOSE_OBJECT)},
        '/docs': {'get': {
            'tags': ['文档'],
            'summary': 'Swagger UI 页面（无需鉴权；前端资源走 CDN，可用 QMT_SWAGGER_UI_BASE 覆盖）',
            'security': [],
            'responses': {
                '200': {'description': 'HTML 页面', 'content': {'text/html': {'schema': {'type': 'string'}}}},
                '500': _json_ok('服务器内部错误', _ref('Error')),
            },
        }},
    }


def _components():
    return {
        'securitySchemes': {
            'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'description': 'Authorization: Bearer <token>'},
            'qmtToken': {'type': 'apiKey', 'in': 'header', 'name': 'X-QMT-Token'},
        },
        'schemas': {
            'Error': {
                'type': 'object',
                'required': ['error'],
                'properties': {
                    'error': {'type': 'string', 'description': '机器可读的错误码'},
                    'detail': {'type': 'string'},
                },
            },
            'Health': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'server_version': {'type': 'integer'},
                    'listener_ready': {'type': 'boolean'},
                    'auth_enabled': {'type': 'boolean'},
                    'http_mode': {'type': 'string'},
                    'http_host': {'type': 'string'},
                    'http_port': {'type': 'integer'},
                    'account_id': {'type': 'string', 'nullable': True},
                    'account_type': {'type': 'string', 'nullable': True},
                    'account_source': {'type': 'string', 'nullable': True},
                    'bind_host': {'type': 'string', 'description': '实际绑定地址，默认 127.0.0.1'},
                    'bind_port': {'type': 'integer', 'description': '实际监听端口'},
                    'allowed_hosts': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Host 头白名单'},
                    'configured_bind_host': {'type': 'string', 'nullable': True},
                    'configured_bind_port': {'type': 'integer', 'nullable': True},
                    'config_path': {'type': 'string'},
                    'position_count': {'type': 'integer'},
                    'order_snapshot_count': {'type': 'integer'},
                    'deal_snapshot_count': {'type': 'integer'},
                    'quote_subscription_count': {'type': 'integer'},
                    'quote_snapshot_count': {'type': 'integer'},
                    'active_client_count': {'type': 'integer'},
                    'max_order_notional': {'type': 'number'},
                    'max_order_volume': {'type': 'integer'},
                    'max_orders_per_minute': {'type': 'integer'},
                    'max_cancels_per_minute': {'type': 'integer'},
                    'last_error': {'type': 'string', 'nullable': True},
                    'last_error_at': {'type': 'number', 'nullable': True},
                },
            },
            'Position': {
                'type': 'object',
                'properties': {
                    'code': {'type': 'string', 'description': '归一化后的标的代码'},
                    'symbol': {'type': 'string'},
                    'volume': {'type': 'integer'},
                    'can_use_volume': {'type': 'integer'},
                    'open_price': {'type': 'number'},
                    'market_value': {'type': 'number'},
                },
            },
            'Quote': {
                'type': 'object',
                'properties': {
                    'stock_code': {'type': 'string'},
                    'data': LOOSE_OBJECT,
                    'ts': {'type': 'number', 'description': '缓存时间戳（epoch 秒）'},
                },
            },
            'Order': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string'},
                    'side': {'type': 'string', 'enum': ['BUY', 'SELL', 'UNKNOWN']},
                    'price': {'type': 'number'},
                    'traded_price': {'type': 'number'},
                    'volume': {'type': 'integer'},
                    'traded_volume': {'type': 'integer'},
                    'order_id': {'type': 'integer', 'description': 'QMT m_nOrderID'},
                    'order_sys_id': {'type': 'string', 'description': '委托号 m_strOrderSysID，撤单使用'},
                    'remark': {'type': 'string'},
                    'commission': {'type': 'number'},
                    'status': {'type': 'integer'},
                    'time': DATETIME,
                },
            },
            'Deal': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string'},
                    'side': {'type': 'string', 'enum': ['BUY', 'SELL', 'UNKNOWN']},
                    'price': {'type': 'number'},
                    'volume': {'type': 'integer'},
                    'trade_id': {'type': 'string'},
                    'order_sys_id': {'type': 'string'},
                    'remark': {'type': 'string'},
                    'commission': {'type': 'number'},
                    'time': DATETIME,
                },
            },
            'CandleBar': {
                'type': 'object',
                'properties': {
                    'time': {'type': 'string', 'nullable': True},
                    'open': {'type': 'number', 'nullable': True},
                    'high': {'type': 'number', 'nullable': True},
                    'low': {'type': 'number', 'nullable': True},
                    'close': {'type': 'number', 'nullable': True},
                    'volume': {'type': 'number', 'nullable': True},
                    'amount': {'type': 'number', 'nullable': True},
                },
            },
            'Signals': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string', 'nullable': True},
                    'point_count': {'type': 'integer'},
                    'lowest_buy_price': {'type': 'number', 'nullable': True},
                    'highest_buy_price': {'type': 'number', 'nullable': True},
                    'points': {'type': 'array', 'items': LOOSE_OBJECT},
                },
            },
            'OrderSubmitResult': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string', 'enum': ['submitted']},
                    'symbol': {'type': 'string'},
                    'side': SIDE,
                    'price': {'type': 'number'},
                    'price_type': {'type': 'integer'},
                    'volume': {'type': 'integer'},
                    'remark': {'type': 'string'},
                    'batch_id': {'type': 'string'},
                    'source': {'type': 'string'},
                    'account_id': {'type': 'string'},
                    'submitted_at': {'type': 'number'},
                    'passorder_result': {'nullable': True},
                    'passorder_args_count': {'type': 'integer'},
                    'quote_before': LOOSE_OBJECT,
                    'account_before': LOOSE_OBJECT,
                    'debug_before': LOOSE_OBJECT,
                    'order_info': {'nullable': True},
                    'deal_info': {'nullable': True},
                    'last_error': {'nullable': True},
                },
            },
            'CancelResult': {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string', 'enum': ['cancel_requested']},
                    'order_id': {'type': 'string'},
                    'account_id': {'type': 'string'},
                    'account_type': {'type': 'string'},
                    'signaled': {'type': 'boolean', 'nullable': True, 'description': 'QMT cancel() 的返回值'},
                    'cancel_result': {'nullable': True},
                    'cancel_args_count': {'type': 'integer'},
                    'requested_at': {'type': 'number'},
                },
            },
            'CanCancelResult': {
                'type': 'object',
                'properties': {
                    'order_id': {'type': 'string'},
                    'account_id': {'type': 'string'},
                    'account_type': {'type': 'string'},
                    'can_cancel': {'type': 'boolean'},
                    'raw': {'nullable': True},
                    'checked_at': {'type': 'number'},
                },
            },
        },
    }


def build_openapi_spec():
    return {
        'openapi': '3.0.3',
        'info': {
            'title': API_TITLE,
            'version': API_VERSION,
            'description': (
                'QMT 策略内本地 HTTP 服务。除 /openapi.json 与 /docs 外，所有接口都需要令牌'
                '（fail-closed），只接受 127.0.0.1 / localhost 的 Host。'
                'WebSocket 行情推送位于 GET /ws（101 升级，推送类型 quote_snapshot），'
                'OpenAPI 无法表达，请使用客户端的 QuoteStream。'
                '监听地址与 Host 白名单通过 server_config.json 的 bind_host / bind_port / '
                'allowed_hosts 配置，默认仅回环。若绑定到局域网地址，请把客户端使用的 IP/主机名 '
                '加入 allowed_hosts；该场景下传输为明文 HTTP，仅适合可信内网，建议加防火墙或前置 TLS 代理。'
            ),
        },
        'servers': [{'url': SERVER_BASE_URL, 'description': '本地 QMT 服务'}],
        'tags': [
            {'name': '状态'},
            {'name': '行情'},
            {'name': '交易', 'description': '会修改真实账户，调用前请确认；/order 与 /cancel 非幂等'},
            {'name': '数据'},
            {'name': '文档'},
        ],
        'security': [{'bearerAuth': []}, {'qmtToken': []}],
        'paths': _paths(),
        'components': _components(),
    }
