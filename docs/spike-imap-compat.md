# IMAP 兼容性 Spike（D2.5）

> **日期**：2026-06-07（D2 阶段同步记录）
>
> **目的**：记录 IMAP 适配器在 QQ / Outlook / Gmail 三个邮箱服务商的**实施路径决策**。
>
> **结论（D1.1 收窄版）**：D2 **只实现 QQ 授权码模式**，Outlook/Gmail OAuth 2.0 推后到 D2.5 或独立 spike。

---

## 0. 一句话总结

| 邮箱 | D2 实施 | 复杂度 | 备注 |
|------|---------|--------|------|
| **QQ 邮箱** | ✅ **完成**（D2.2）| 低 | 16 位授权码，imapclient 同步 API 即可 |
| Outlook | ❌ **推后** | 高 | OAuth 2.0 + Microsoft Graph + 企业 MFA 复杂度高 |
| Gmail | ❌ **推后** | 高 | OAuth 2.0 + Google 自 2025 年起逐步停用"不够安全的应用"（最终弃用时间因域名配置而异），必须用 OAuth |

---

## 1. QQ 邮箱（imap.qq.com:993）

### 实施路径（已落地）

- **协议**：IMAP4 + SSL（端口 993）
- **凭证**：邮箱地址 + 16 位授权码（**不是密码**）
- **库**：`imapclient>=3.0.1`（PyPI 官方，支持 IMAP4 + XOAUTH2）
- **凭证存储**：macOS Keychain（service=`my-ai-employee.imap.qq`）
- **代码**：[src/my_ai_employee/connectors/imap.py](../src/my_ai_employee/connectors/imap.py)
- **CLI**：[scripts/test_imap.py](../scripts/test_imap.py)

### 用户一次性配置

1. 登录 QQ 邮箱网页版（[mail.qq.com](https://mail.qq.com)）
2. 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务
3. 开启 **IMAP/SMTP 服务**
4. 短信验证后生成 **16 位授权码**
5. 写入 Keychain：

   ```bash
   python scripts/test_imap.py --set-password your@qq.com
   # 粘贴 16 位授权码（不回显）
   ```

### 验证连通

```bash
python scripts/test_imap.py --check --email your@qq.com
# ✅ 健康检查通过: latency=200ms circuit_open=False
```

### 已知风险

- **mitm 风险**：imapclient 默认 `verify=True`，macOS 证书链完整，无需额外配置
- **授权码失效**：QQ 改密码后授权码会失效，需要重新生成
- **频率限制**：QQ IMAP 单连接 5 min 一次（5 min 轮询刚好边界）

---

## 2. Outlook（outlook.office365.com:993）— **推后**

### 为什么推后

- **OAuth 2.0 必选**：Microsoft 2022-10-01 起已**永久禁用 Basic Auth**（[Microsoft 公告](https://learn.microsoft.com/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online)）
- **必须用 Microsoft Graph** + OAuth 2.0 Authorization Code Flow
- **企业 MFA**：很多企业账号强制 MFA，token 刷新逻辑复杂
- **SDK 选择**：`msal`（官方）vs `requests-oauthlib`（轻量），需 spike 比较

### 推后决策

- **D2 不做**：复杂度 ≈ 1.5 天，但 D2 总预算 4h
- **D2.5 或独立 spike**：建议 D2.5 或后续 Week 1 末决策点评估
- **库候选**：`msal>=1.28.0` + `requests>=2.31.0`

### 何时重启

- QQ 跑稳 1 周后（证明 D2 链路无重大问题）
- 用户明确表示需要 Outlook 接入（典型场景：外企工作邮箱）

---

## 3. Gmail（imap.gmail.com:993）— **推后**

### 为什么推后（比 Outlook 更严）

- **Google 自 2025 年起逐步停用 "不够安全的应用" 访问**（[Google Account Help](https://support.google.com/accounts/answer/6010255) / [Workspace Admin Help](https://support.google.com/a/answer/14114704)）；Workspace 管理员对 IMAP/POP/SMTP 的基本认证最终弃用时间因域名配置而异
- **Basic Auth（邮箱 + 密码 / 应用专用密码）已完全失效**
- **必须用 OAuth 2.0**：Web 授权流程 + refresh_token 持久化
- **scope 复杂**：`https://mail.google.com/`（全权限）或 `https://www.googleapis.com/auth/gmail.readonly`（只读）

### 推后决策

- **D2 不做**：与 Outlook 同因
- **额外障碍**：Gmail API 还有**每日 10 亿单位配额**限制（个人用不到，但代码要处理 429）
- **库候选**：`google-auth-oauthlib>=1.2.0` + `google-api-python-client>=2.100.0`

### 何时重启

- 同 Outlook 的触发条件
- **额外要求**：用户必须在 Google Cloud Console 创建 OAuth client（一次性开发者操作）

---

## 4. 决策汇总

| 维度 | D2 范围 | 推后项 | 何时评估推后项 |
|------|---------|--------|---------------|
| **协议实现** | IMAP4 + SSL（QQ）| OAuth 2.0（Outlook/Gmail）| D2.5 spike 或 Week 1 末 |
| **凭证流** | 16 位授权码（QQ）| Authorization Code + refresh_token | 同上 |
| **SDK** | imapclient 3.x | msal / google-auth-oauthlib | 推后项启动时 |
| **Keychain service** | `my-ai-employee.imap.qq` | `my-ai-employee.imap.outlook` / `.gmail` | 推后项启动时 |
| **测试** | mock + 真实 QQ（用户手动）| mock-only（无测试 token） | 推后项启动时 |

### 设计原则（与 Agent Assistant 应急版范本对齐）

> "**小步快跑**比**一次到位**更稳"——D2 只做 QQ（4h 落地），不为了"全兼容"硬啃 OAuth 2.0 复杂度。
>
> Outlook/Gmail 的 OAuth 实现是**独立可拆分的 spike**，单独议定启动时间更稳。

---

## 5. 复用模式

D2.2 的 IMAPConnector 已经为 Outlook/Gmail 留好扩展点：

```python
# connectors/imap.py
SERVER_CONFIGS = {
    "qq": IMAPServerConfig(host="imap.qq.com", port=993, ...),
    "outlook": IMAPServerConfig(host="outlook.office365.com", port=993, ...),  # 待 OAuth
    "gmail": IMAPServerConfig(host="imap.gmail.com", port=993, ...),  # 待 OAuth
}
```

将来加 Outlook/Gmail **只需 2 处改动**：

1. `_connect_sync` 增加 OAuth 分支（用 `imapclient` 的 `XOAUTH2` 流程）
2. `keychain.set_imap_password` 拆分成 `set_imap_oauth_token`（存 refresh_token）

`source_name` / `safe_fetch` / 熔断 / 测试**全部复用**，零改动。

---

**最后更新**：2026-06-07（D2 收尾）
**当前模型**：MiniMax-M3
**维护者**：Mr-PRY
**状态**：QQ 已通，Outlook/Gmail 推后到 D2.5 spike 或独立排期
