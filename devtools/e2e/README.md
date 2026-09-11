# Docker 跨端点 LAN E2E（可选）

用两个 Docker 容器模拟两个网络端点，验证**真实 `server/server.py`（由 `devtools/fake_qmt` 驱动）**与**真实 `qmt_client`** 跨网络的完整交互：

- server 容器：监听 `0.0.0.0:18080`，另开 UDP 发现端口
- client 容器：真实 `qmt_client`
- 两者在同一自定义 bridge 的**不同 IP** 上（不同网络命名空间）

这是**可选**测试：需要 Docker daemon，不进入默认 pytest。

## 运行

```bash
python3 devtools/e2e/docker_lan_e2e.py
```

退出码：`0` 通过（无 Docker 时打印 `SKIP` 并返回 `0`），`1` 有检查失败，`2` 环境/启动失败。

常用参数：`--token` `--port` `--discovery-port` `--subnet` `--server-ip` `--client-ip` `--keep`（保留容器/网络排查）`--keep-image`。

首次运行会拉取 `python:3.12-slim` 并 `pip install requests websocket-client`（需联网）。

## 覆盖

TCP health、account、positions、下单、可撤查询、撤单、K 线、行情快照、WebSocket、`/openapi.json` 公开、无 token 401，以及服务发现的单播 / 子网广播 / `255.255.255.255`。

## 与物理 LAN 的差异

- Docker bridge 是 Linux 虚拟网桥：没有 AP 客户端隔离、没有 Windows 防火墙、没有 VLAN/ACL
- 容器共享宿主时钟，跨机时钟偏差未覆盖
- server 跑在 Linux + Python 3.12；生产是 Windows + QMT 的 Python 3.6.8

真机双机验收：在 A 机跑
`python3 devtools/run_fake_qmt.py --host 0.0.0.0 --port 18080 --token <t> --allowed-hosts <A-ip>:18080 --discovery --discovery-port 18081`，
在 B 机跑 `qmt-discover --token <t> --broadcast auto`，并放行 A 的 TCP 18080 / UDP 18081。
