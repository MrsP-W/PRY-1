# Eval fixture schema（v1.1）

离线评测样本契约。真实数据必须脱敏后再入库；默认合成样例仅用于契约校验。

## 文件约定

- 路径：`tests/eval/fixtures/<suite>/*.json`
- 编码：UTF-8 JSON object（单样本一文件）或 JSONL（多样本，后续 runner 支持）
- 禁止字段：真实邮箱本地部分以外的可识别身份、卡号、手机号、内部主机名

## 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 样本稳定 ID |
| `suite` | string | 如 `email_classify` / `email_draft` / `sap_troubleshoot` |
| `capability_id` | string | 对齐能力注册表 id |
| `input` | object | 脱敏输入 |
| `expected` | object | 期望输出（分类标签 / 关键断言 / 禁止项） |
| `feedback_label` | string | `adopt` / `modify` / `reject` / `unknown`（历史标注） |
| `desensitized` | bool | 必须为 `true` |
| `source` | string | `synthetic` / `user_redacted` |

## expected 常用键

- `category`：邮件五类之一  
- `must_include` / `must_not_include`：草稿正文约束  
- `blocked`：是否应阻断草稿  
- `citations_required`：知识包场景是否要求来源（P2）

## 规模目标

- v1.1-A 启动前：≥ 30 条跨 suite 脱敏样本  
- 当前：契约 + 少量 synthetic，用于防止目录空洞
