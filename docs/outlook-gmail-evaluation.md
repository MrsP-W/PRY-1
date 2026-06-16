# outlook/gmail SMTP provider 拆分评估(2026-06-16)

> **状态**:🎯 docs-only 评估(2026-06-16 晚)· **承接**:D5.6.5 真实 1 封 SMTP 实化 + D5 业务调度器锁定(`smtp.qq.com:465` 唯一实化 provider)· **决策**:推荐 **方案 A (provider 工厂模式)** + OAuth 2.0 框架抽象延后 · **下一棒**:v0.2.1 启动前用户最终决策(本轮 docs-only 不实施代码)
>
> **背景**:B 类延后清单 5 项中 outlook/gmail 是第 5 项,优先级 P3,1 docs-only commit 落定评估结论。**注意**:outlook / gmail 真实 OAuth 2.0 凭据流**复杂度高**(Azure App Registration + refresh token 流程),本轮 docs-only 仅评估**架构方向**,具体凭据流实施留 v0.2.1+ 决策。

---

## 1. 现状摸底(2026-06-16 晚)

### 1.1 已有代码

| 文件 | 内容 |
|------|------|
| `src/my_ai_employee/connectors/smtp.py:375` | `_SMTP_PROVIDERS: Final[tuple[str, ...]] = ("qq", "outlook", "gmail")` — 已支持 3 provider 白名单 |
| `src/my_ai_employee/connectors/smtp.py:388-407` | `SERVER_CONFIGS` 字典已含 qq / outlook / gmail 3 个 `SMTPServerConfig`(host / port / description) |
| `src/my_ai_employee/connectors/smtp.py:462-466` | `SMTPConnector.__init__` 严判: **仅 provider="qq" 通过**,outlook / gmail 抛 `NotImplementedError` |
| `src/my_ai_employee/connectors/smtp.py:525-532` | `connect()` 内部 `keychain.get_smtp_password()` — 当前只支持**授权码**(QQ 模式) |
| `pyproject.toml` | 未装 MSAL / google-auth(仅 smtplib 标准库 + uv 自带) |
| `D5.6.5 真实 1 封验证` | smtp.qq.com:465 SSL 真实 SMTP 端到端实测通过(`d5-6-5-real-send` 范本) |

### 1.2 outlook/gmail OAuth 2.0 凭据流复杂度

| 维度 | QQ(已实化) | Outlook | Gmail |
|------|----------|---------|-------|
| **凭据模式** | 16 位授权码 | OAuth 2.0 refresh token | OAuth 2.0 refresh token |
| **获取流程** | 网页设置 → 短信验证 → 16 位授权码 | Azure App Registration + admin consent + OAuth scope | Google Cloud Console + OAuth client + scope |
| **Token 刷新** | 不需(静态授权码) | MSAL refresh_token → access_token(60min TTL) | google-auth refresh_token → access_token(60min TTL) |
| **依赖库** | 无(标准库 smtplib) | `msal>=1.24` (~3MB wheel) | `google-auth` + `google-auth-oauthlib` (~5MB wheel) |
| **凭据存储** | Keychain 1 字段(`SMTP_AUTHCODE`) | Keychain 4 字段(`CLIENT_ID` + `CLIENT_SECRET` + `TENANT_ID` + `REFRESH_TOKEN`) | Keychain 4 字段(`CLIENT_ID` + `CLIENT_SECRET` + `REFRESH_TOKEN` + `SCOPES`) |
| **首次用户操作** | 1 步(网页 + 短信) | 5+ 步(Azure 注册 + admin 授权 + 首次 OAuth flow + 拿 refresh token) | 3+ 步(Google Cloud + OAuth client + 首次 OAuth flow + 拿 refresh token) |
| **维护负担** | 低 | 中(每次 client_secret 轮换需重走 flow) | 中(类似 Outlook) |

### 1.3 关键约束

| # | 约束 | 范本 |
|---|------|------|
| 1 | **不破坏现有 D5 业务调度器**(QQ 已实化, 1563 passed) | D5.6.5 真实 1 封范本,1563 tests 9 质量门 9/9 全绿 |
| 2 | **不引入大依赖**(msal + google-auth 合计 ~8MB wheel) | pyproject 体积敏感(沿 D1.1 范本) |
| 3 | **B4 黑名单 hot-path 双层防御**(D9.6 + B4.3 锁定) | outlook/gmail 接入后**必须沿用** B4.3 黑名单 SMTP 二次防御范本 |
| 4 | **4 重防误发**(D5.6.5 锁定) | outlook/gmail 必须沿用 `SMTP_REAL_NETWORK=1` 门控 + dry-run + confirm |
| 5 | **macOS Keychain 唯一凭据源** | outlook/gmail OAuth refresh token 也存 Keychain(与 QQ 授权码同源) |
| 6 | **D2 IMAP 同步已支持 outlook/gmail** | outlook/gmail SMTP 实施时可参考 D2 IMAP 凭据流(但 D2 IMAP 也不收 outlook/gmail,D2.5 OAuth 推后) |

---

## 2. 3 候选方案对比

### 方案 A:provider 工厂模式(`SmtpProviderFactory.create(provider_name)`)

**核心**:`connectors/smtp.py` 拆 `BaseSmtpTransport` + `QqSmtpTransport` / `OutlookSmtpTransport` / `GmailSmtpTransport`,工厂方法 `SmtpProviderFactory.create(provider_name: str) -> BaseSmtpTransport`。QQ 沿用现有授权码模式,Outlook/Gmail 各自封装 OAuth 2.0 token 刷新。

**实现要点**:
```python
# connectors/smtp_provider_factory.py 新建
class BaseSmtpTransport(Protocol):
    def connect(self) -> None: ...
    def send_message(self, message: EmailMessage) -> SMTPSendResult: ...

class QqSmtpTransport(BaseSmtpTransport):
    """QQ 授权码模式(沿用现有 SmtpLibTransport 逻辑)。"""
    def __init__(self, email: str, authcode: str) -> None: ...

class OutlookSmtpTransport(BaseSmtpTransport):
    """Outlook OAuth 2.0 + MSAL refresh token 流程。"""
    def __init__(self, email: str, client_id: str, client_secret: str,
                 tenant_id: str, refresh_token: str) -> None:
        self._msal_app = msal.ConfidentialClientApplication(...)

class SmtpProviderFactory:
    @staticmethod
    def create(provider: str, **kwargs) -> BaseSmtpTransport:
        if provider == "qq": return QqSmtpTransport(**kwargs)
        elif provider == "outlook": return OutlookSmtpTransport(**kwargs)
        elif provider == "gmail": return GmailSmtpTransport(**kwargs)
        else: raise ValueError(f"未知 provider: {provider!r}")
```

**优点**:
- **扩展性最佳**:新 provider 添加只需新建 1 个 class + 工厂注册 1 行
- **基类抽象统一接口**:现有 `SMTPTransport` Protocol 已稳定,工厂产出物仍 duck type 兼容
- **OAuth 2.0 框架清晰**:每个 provider 独立封装 token 刷新逻辑,不污染基类
- **测试隔离**:每个 provider 独立单元测试,沿 D5.6.4 spike 100 范本

**缺点**:
- **中等**: 工厂类 + 3 个 provider 类 + OAuth 抽象层 = 4-5 新文件,改动规模大
- **中等**: 需要 OAuth 2.0 mock 库(msal / google-auth 测试模式)
- **中等**: Keychain 凭据 schema 变化(从 1 字段扩到 4 字段 per OAuth provider)
- **依赖增量**: `msal>=1.24` + `google-auth` 合计 ~8MB wheel

**评分**:⭐⭐⭐⭐(4/5)— **推荐**

---

### 方案 B:多配置平行类(`QQSmtpTransport / OutlookSmtpTransport / GmailSmtpTransport`)

**核心**:不抽象基类,直接 3 个平行 transport class,各自实现 connect / login / send_message 三方法,`SMTPConnector.__init__` 严判 provider 后实例化对应 class。

**实现要点**:
```python
# connectors/smtp_qq.py / smtp_outlook.py / smtp_gmail.py 三个独立模块
class QQSmtpTransport:
    def __init__(self, email: str, authcode: str) -> None: ...
    def connect(self) -> None: ...
    def send_message(self, message: EmailMessage) -> SMTPSendResult: ...

class OutlookSmtpTransport:
    def __init__(self, email: str, ...) -> None: ...
    def connect(self) -> None: ...
    def send_message(self, message: EmailMessage) -> SMTPSendResult: ...
```

**优点**:
- 简单直接,无抽象层
- 各 provider 独立模块,可单独 disable / 重写

**缺点**:
- **致命**: 代码重复(connect / send_message 三方法在 3 个 class 各写一次)
- **致命**: D5.6.5 真实 1 封验证 + D5.6.4 spike 范本全在 `SmtpLibTransport`,重写 = 推翻现有 1563 tests
- **中等**: D9.6 + B4.3 黑名单 hot-path 双层防御需要改 3 处
- **中等**: 不符合 D4.7.3 Protocol 范本(已有 `SMTPTransport` Protocol 类)

**评分**:⭐⭐(2/5)— 不推荐

---

### 方案 C:只支持 outlook(放弃 gmail,因 OAuth 2.0 配置复杂)

**核心**:实施 1 个 OAuth provider(outlook, 用 MSAL),gmail 显式不实施,降低复杂度。理由:Outlook 用户群大于 gmail(企业用户居多)。

**实现要点**:
- 仅新建 `OutlookSmtpTransport` class(沿方案 A 框架,但只 1 个 provider)
- `SmtpProviderFactory.create(provider="outlook")` 实化,gmail 抛 NotImplementedError

**优点**:
- 实施范围小(仅 1 个 OAuth provider)
- 依赖增量小(仅 `msal>=1.24`,3MB)

**缺点**:
- **中等**: 不支持 gmail 限制用户群(个人 gmail 用户被排除)
- **中等**: 未来加 gmail 仍需重构(从"只有 outlook"扩到"outlook + gmail",代码结构需调整)
- **中等**: 与 D2 IMAP 策略不一致(D2 IMAP 同样 outlook/gmail 都不收,但本方案部分实施反而打破一致性)

**评分**:⭐⭐⭐(3/5)— 中等推荐(若用户决定不实施 gmail 可选)

---

## 3. 推荐方案 + 决策

### 3.1 推荐:**方案 A (provider 工厂模式)**

**推荐理由**:
1. **架构扩展性最优**:未来加 provider(yahoo / fastmail / 自建 SMTP)成本最低
2. **沿用既有 D5 范本**:现有 `SMTPTransport` Protocol 已稳定,工厂产出物仍 duck type 兼容,**D5.6.5 真实 1 封验证不破坏**
3. **OAuth 2.0 框架清晰**:每个 provider 独立封装,msal/google-auth 不会污染基类
4. **测试隔离 + spike 复用**:每个 provider 独立单元测试 + D5.6.4 spike 100 范本复用
5. **B4 黑名单双层防御适配**:黑名单 hot-path 在 EmailSendAdapter 业务层,Provider 工厂改造不影响 B4.3 SMTP 二次防御

**实施规模预估**(v0.2.1+ 启动后):
- `connectors/smtp_provider_factory.py` 新建(~150 行:BaseSmtpTransport + Factory + 1 错误处理)
- `connectors/smtp_qq.py` 新建(~80 行:QqSmtpTransport 沿用现有授权码模式)
- `connectors/smtp_outlook.py` 新建(~180 行:OutlookSmtpTransport OAuth 2.0 + MSAL)
- `connectors/smtp_gmail.py` 新建(~180 行:GmailSmtpTransport OAuth 2.0 + google-auth)
- `connectors/smtp.py` 改:`SMTPConnector.__init__` 严判删除,委托给工厂(~30 行改)
- `pyproject.toml`:`msal>=1.24` + `google-auth>=2.23` + `google-auth-oauthlib>=1.1` 依赖加
- `tests/connectors/test_smtp_provider_factory.py` 新建(~200 行:5 cases:工厂分发 + 未知 provider 拒收 + duck type 验证)
- `tests/connectors/test_outlook_smtp.py` 新建(~150 行:5 cases:OAuth token 刷新 mock + B4 黑名单适配)
- `tests/connectors/test_gmail_smtp.py` 新建(~150 行:5 cases:OAuth token 刷新 mock + B4 黑名单适配)
- `scripts/spike_outlook_smtp.py` 新建(沿 D5.6.4 spike 100 范本)
- 预计 commits: 4-6 commits(2 feat 工厂 + QQ + 1 feat outlook + 1 feat gmail + 1 spike + 1 docs 收口)
- 预计测试数变化: +15-20 tests
- 预计依赖增量: ~8MB wheel

### 3.2 关键决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | **本轮 docs-only 不实施代码** | OAuth 2.0 凭据流复杂度高,docs-only 锁架构方向,具体实施留 v0.2.1+ 决策 |
| 2 | **QQ 现有 `SmtpLibTransport` 保留,工厂产出 `QqSmtpTransport` 包装** | 不推翻 D5.6.5 真实 1 封验证,1563 tests 全保留(沿 D5 范本) |
| 3 | **Outlook / Gmail OAuth 2.0 凭据存 Keychain 4 字段** | 与现有 `keychain.get_smtp_password()` 接口兼容(扩展为 `keychain.get_oauth_credentials(provider, email)` 返回 NamedTuple) |
| 4 | **B4 黑名单双层防御沿用** | B4.3 在 `EmailSendAdapter.send_and_emit` 业务层,Provider 工厂改造不影响 hot-path(沿 B4 范本) |
| 5 | **4 重防误发沿用** | outlook/gmail 必须 `SMTP_REAL_NETWORK=1` 门控 + dry-run + confirm + 真实 spike 才落(沿 D5.6.5 范本) |
| 6 | **D2 IMAP outlook/gmail 不在本轮范围** | D2.5 OAuth 推后是 B 类延后清单第 5 项,IMAP outlook/gmail 与 SMTP outlook/gmail **独立决策**,本轮仅 SMTP 评估 |

### 3.3 不实施代码(本轮 docs-only 锁定)

**本轮不做**:
- 不新建 `connectors/smtp_provider_factory.py`
- 不新建 `connectors/smtp_qq.py` / `smtp_outlook.py` / `smtp_gmail.py`
- 不改 `connectors/smtp.py` `SMTPConnector.__init__` 严判
- 不加 msal / google-auth 依赖
- 不改 Keychain 接口

**留给 v0.2.1+ 启动前用户决策**:
- 是否采纳方案 A(还是方案 C 仅 outlook)
- 何时启动 outlook/gmail 实施 commits(估 4-6 commits,2-3 工作日)
- 是否同步实施 D2.5 IMAP outlook/gmail(独立 B 类决策,本轮不触发)
- 真实 OAuth 凭据获取(Azure App Registration + Google Cloud Console)由用户手动完成

---

## 4. 复用要点速查表(outlook/gmail v0.2.1+ 启动后立即可用)

| 任务 | 复用模块 | 关键签名 | 文件 |
|------|----------|----------|------|
| `SMTPTransport` Protocol 基类 | Protocol + duck type | `connect/login/send_message/quit` | `src/my_ai_employee/connectors/smtp.py:91-112` |
| `_SMTP_PROVIDERS` 白名单 | `Final[tuple[str, ...]]` | `("qq", "outlook", "gmail")` | `src/my_ai_employee/connectors/smtp.py:375` |
| `SERVER_CONFIGS` 配置字典 | `dict[str, SMTPServerConfig]` | host / port / source_name_value / description | `src/my_ai_employee/connectors/smtp.py:388-407` |
| 4 状态返回结果契约 | `SMTPSendResult` | OK / PERMANENT_BOUNCE / TRANSPORT_ERROR / TIMEOUT | `src/my_ai_employee/connectors/smtp.py:55-86` |
| QQ 真实 1 封 spike 范本 | D5.6.5 范本 | `smtp.qq.com:465 SSL` 真实发送 | `reports/v0.1-real-spike-d-smtp-send.md`(D5.6.5 真实 1 封报告) |
| B4 黑名单 SMTP 二次防御 | `EmailSendAdapter.send_and_emit` | 入口前 `is_blocked()` | `src/my_ai_employee/policy/send_adapter.py`(B4.3 已落) |
| 4 重防误发范本 | `SMTP_REAL_NETWORK=1` 门控 + dry-run + confirm | 沿 D5.6.5 | `src/my_ai_employee/policy/send_adapter.py` |
| Keychain 接口扩展 | `keychain.get_smtp_password()` | 现有 1 字段(QQ 授权码) | `src/my_ai_employee/core/keychain.py` |
| OAuth token 刷新 mock | `msal.ConfidentialClientApplication` mock | `acquire_token_for_client` 返回 mock token | `msal>=1.24` + `unittest.mock.MagicMock` |
| Outlook MSAL | `msal.ConfidentialClientApplication` | `client_id` / `client_secret` / `tenant_id` | `msal` 文档 |
| Gmail google-auth | `google.oauth2.credentials.Credentials` | `refresh_token` / `token_uri` / `client_id` | `google-auth` 文档 |

---

## 5. 关键风险 + 缓解

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | **OAuth 2.0 凭据首次获取复杂**(用户需 Azure / Google Cloud 操作) | 🟡 中 | docs 写清操作步骤,沿 D2 IMAP 凭据流范本 |
| 2 | **Token 刷新逻辑在 OAuth provider 库内部**, 测试难 mock | 🟡 中 | 用 `unittest.mock.MagicMock` mock 整个 MSAL / google-auth 实例,沿 D5.6.4 spike 范本 |
| 3 | **msal / google-auth 依赖版本兼容性** | 🟢 低 | uv lock 同步,pyproject 锁 `>=` 范围 |
| 4 | **B4 黑名单 SMTP 二次防御不破坏** | 🟢 低 | Provider 工厂产出物仍过 `EmailSendAdapter.send_and_emit` 入口前 `is_blocked()`,业务层不动 |
| 5 | **真实 spike 测试需用户手动配 OAuth 凭据** | 🟡 中 | docs 写清"必须真实凭据才能跑 spike",沿 D5.6.5 范本 `SMTP_REAL_NETWORK=1` 门控 |
| 6 | **Outlook / Gmail 凭据泄露风险** | 🚨 严重 | OAuth refresh_token 仅存 Keychain,**禁止** print 日志,沿 D5 范本(logger 仅打印 service+account) |

---

## 6. 完成定义(outlook/gmail docs-only 评估 Done)

- [x] 3 候选方案对比(provider 工厂 / 多平行类 / 只支持 outlook)
- [x] 推荐方案 A(provider 工厂模式)
- [x] 关键决策 6 条(docs-only 不实施 / 沿用 SmtpLibTransport / Keychain 4 字段 / B4 沿用 / 4 重防误发 / D2.5 独立)
- [x] 复用要点速查表 11 行
- [x] 风险缓解 Checklist 6 项
- [ ] v0.2.1+ 启动前用户最终决策(留 B 类决策延后范围)

---

## 7. 关联

- **承接**:v0.2-launch-plan.md:73 outlook/gmail 段 + v0.2-substage-mapping.md:239-263 outlook/gmail 详细任务分解
- **沿用范本**:[[d5-6-5-real-send]] + [[d5-business-scheduler-launch]] + [[b4-3-smtp-send-blacklist]] + [[b-class-deferral-2026-06-09]]
- **B 类延后清单 5 项收口**:
  - B1 ✅ 6/16 落地(b97ae55 + 268e181 + 64a9adb 整条)
  - B2 ✅ 6/16 落地(31cbd05 + 80e087c + 3a26062 整条)
  - B4 ✅ 6/16 晚实化(0c6472f → 2bb77a0 → e54c697 共 11 commits 收口链)
  - **B-5 📝 docs-only(上轮)** — 推荐方案 B Quartz,见 [b-5-pynput-evaluation.md](b-5-pynput-evaluation.md)
  - **outlook/gmail 📝 docs-only(本轮)** — 推荐方案 A 工厂模式,v0.2.1+ 启动前用户决策
- **下一棒**:outlook/gmail v0.2.1+ 启动前用户决策(无 B 类触发,本轮 docs-only 锁评估)