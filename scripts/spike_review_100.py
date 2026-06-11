"""D4.7.4.10 spike — 100 封合成邮件审阅 + 阻断率/原因分布/延迟统计.

设计原则:
  - 5 类邮件(URGENT/TODO/FYI/SPAM/PERSONAL)× 20 封 = 100 封
  - 32 封触发本地硬规则(预期 business_blocked):SENSITIVE_WORD_HIT / TONE_MISMATCH /
    TEMPLATE_VIOLATION / FACTUAL_CONFLICT
  - 68 封走 LLM(预期 review_passed=True 或 review_rejected with flagged_issues)
  - 输出:JSON 全量结果 + Markdown spike 报告

用法:
    uv run python scripts/spike_review_100.py
    uv run python scripts/spike_review_100.py --output-dir output/spike
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# 让脚本可独立运行(无需安装包)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from my_ai_employee.ai.reviewer import (  # noqa: E402
    EmailReviewer,
    ReviewBlockedResult,
    ReviewFailureResult,
    ReviewResult,
)

# ==================== 100 封邮件数据 ====================
# 每条格式:(subject, body, tone, email_category, original_body_excerpt, expected_block)
# expected_block: None=预期 LLM 判定, "sensitive"/"tone"/"template"/"factual"=预期本地阻断
URGENT_EMAILS: list[dict] = [
    # --- 3 封 SENSITIVE_WORD_HIT ---
    {
        "subject": "服务器紧急故障处理",
        "body": "您好,请立即处理服务器宕机问题。您的身份证号 110101199001011234 已登记在案,请尽快配合调查。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "系统监控到核心服务异常,请立即处理。",
        "expected_block": "sensitive",
    },
    {
        "subject": "客户密码泄露紧急通知",
        "body": "请收到邮件后立即重置银行密码并通知客户,涉及账号安全。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "安全团队发现客户密码可能泄露。",
        "expected_block": "sensitive",
    },
    {
        "subject": "内部代号项目进展",
        "body": "内部代号「ProjectX」进展汇报:绝密级别,已转发核心成员。",
        "tone": "CONCISE",
        "email_category": "URGENT",
        "original_body_excerpt": "ProjectX 项目需要紧急汇报。",
        "expected_block": "sensitive",
    },
    # --- 2 封 TONE_MISMATCH (URGENT + FRIENDLY) ---
    {
        "subject": "服务器宕机啦!",
        "body": "嘿嘿~服务器挂啦~麻烦亲快点看一下哦,爱你~",
        "tone": "FRIENDLY",
        "email_category": "URGENT",
        "original_body_excerpt": "服务器宕机,需要紧急处理。",
        "expected_block": "tone",
    },
    {
        "subject": "急!!",
        "body": "嗨哥们儿,数据库崩啦,赶紧瞅瞅!",
        "tone": "FRIENDLY",
        "email_category": "URGENT",
        "original_body_excerpt": "数据库异常需要立即处理。",
        "expected_block": "tone",
    },
    # --- 1 封 TEMPLATE_VIOLATION ---
    {
        "subject": "[DRAFT-TEST] 数据库恢复通知",
        "body": "数据库已恢复,请相关同事继续推进工作。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "数据库已恢复。",
        "expected_block": "template",
    },
    # --- 2 封 FACTUAL_CONFLICT ---
    {
        "subject": "客户投诉全额退款处理",
        "body": "针对您的投诉,我们承诺全额退款 5000 元,3 个工作日内到账。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "客户对服务不满,要求公司处理。",
        "expected_block": "factual",
    },
    {
        "subject": "事故赔偿方案",
        "body": "事故原因已查明,公司将赔偿 8000 元并改进流程。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "客户询问事故处理进展。",
        "expected_block": "factual",
    },
    # --- 12 封 Normal(预期 LLM 判定)---
    {
        "subject": "服务降级通知",
        "body": "由于上游服务异常,我们将启动降级方案。预计影响:非核心功能 30 分钟不可用。请相关团队做好用户沟通。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "上游服务异常通知。",
        "expected_block": None,
    },
    {
        "subject": "线上故障处理进展",
        "body": "故障定位完成,根因为数据库连接池耗尽。已重启服务,监控观察 30 分钟。预计 1 小时内完全恢复。",
        "tone": "CONCISE",
        "email_category": "URGENT",
        "original_body_excerpt": "线上服务出现故障。",
        "expected_block": None,
    },
    {
        "subject": "合规审计截止提醒",
        "body": "年度合规审计材料截止 6 月 15 日 18:00。请各部门负责人在截止前提交完整材料,逾期影响公司合规评级。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "合规审计截止时间临近。",
        "expected_block": None,
    },
    {
        "subject": "客户合同续签提醒",
        "body": "客户 A 公司合同将于 6 月 20 日到期。请销售负责人张总在 6 月 18 日前完成续签,法务配合审核。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "客户合同即将到期,需续签。",
        "expected_block": None,
    },
    {
        "subject": "紧急招聘需求",
        "body": "研发团队急需 2 名高级工程师,要求 5 年以上经验。请 HR 部门本周内启动招聘,目标 6 月底前到岗。",
        "tone": "CONCISE",
        "email_category": "URGENT",
        "original_body_excerpt": "研发部门急需招聘工程师。",
        "expected_block": None,
    },
    {
        "subject": "财务月结提前",
        "body": "因季度审计安排,本月财务结账提前至 6 月 12 日。请各业务部门 6 月 10 日前提交单据。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "财务月结时间需要调整。",
        "expected_block": None,
    },
    {
        "subject": "生产环境告警",
        "body": "生产环境 CPU 使用率持续 95% 以上,已触发自动扩容。如 10 分钟内未恢复,请值班工程师立即介入。",
        "tone": "CONCISE",
        "email_category": "URGENT",
        "original_body_excerpt": "生产环境出现性能告警。",
        "expected_block": None,
    },
    {
        "subject": "客户系统升级通知",
        "body": "为提升服务稳定性,我们将于 6 月 18 日凌晨 2:00-4:00 进行系统升级,期间服务短暂不可用,请提前知会客户。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "系统升级时间安排。",
        "expected_block": None,
    },
    {
        "subject": "安全漏洞修复",
        "body": "安全团队发现高危漏洞(CVE-2026-1234),需立即修复。预计 4 小时内完成补丁,期间可能影响登录功能。",
        "tone": "CONCISE",
        "email_category": "URGENT",
        "original_body_excerpt": "发现高危安全漏洞。",
        "expected_block": None,
    },
    {
        "subject": "供应商资质过期",
        "body": "3 家供应商资质证书将于本月底过期,请采购部门立即跟进续期,避免影响后续合作。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "部分供应商资质即将过期。",
        "expected_block": None,
    },
    {
        "subject": "董事会会议安排",
        "body": "临时董事会会议定于 6 月 13 日 10:00 召开,议题:季度业务回顾。请董事们准时出席,材料会前 1 天发送。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "需要召开临时董事会。",
        "expected_block": None,
    },
    {
        "subject": "客户投诉升级",
        "body": "客户 B 投诉持续升级,已联系三次未获满意答复。请客户成功团队 24 小时内主动联系,提供解决方案。",
        "tone": "FORMAL",
        "email_category": "URGENT",
        "original_body_excerpt": "客户对当前处理结果不满。",
        "expected_block": None,
    },
]

TODO_EMAILS: list[dict] = [
    # --- 3 封 SENSITIVE_WORD_HIT ---
    {
        "subject": "客户名单整理",
        "body": "请根据附件中的客户名单,按行业分类整理下周一提交。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要整理客户分类数据。",
        "expected_block": "sensitive",
    },
    {
        "subject": "薪资明细核对",
        "body": "请人力资源部核对本月薪资明细,涉及全员信息,需在 6 月 15 日前完成。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要进行薪资核对。",
        "expected_block": "sensitive",
    },
    {
        "subject": "访问令牌轮换",
        "body": "所有 API 访问令牌需要在月底前完成轮换,请相关同事配合。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "需要更新 API 凭证。",
        "expected_block": "sensitive",
    },
    # --- 1 封 TEMPLATE_VIOLATION ---
    {
        "subject": "[TEMP-DRAFT] 项目周报",
        "body": "本周完成 API 设计文档,下周开始编码实现。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "请提交本周工作周报。",
        "expected_block": "template",
    },
    # --- 2 封 FACTUAL_CONFLICT ---
    {
        "subject": "供应商退款确认",
        "body": "根据协商结果,供应商将退款 3000 元,请财务部门核实。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "供应商同意协商方案。",
        "expected_block": "factual",
    },
    {
        "subject": "会议差旅补偿",
        "body": "参会同事差旅费补偿 1500 元,请财务在月结时处理。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "需要处理会议差旅费。",
        "expected_block": "factual",
    },
    # --- 14 封 Normal ---
    {
        "subject": "需求评审会议",
        "body": "请产品、研发、测试负责人本周三 14:00 参加需求评审会议,议题:用户权限模块重构方案。会议室已预定 A302。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要安排需求评审。",
        "expected_block": None,
    },
    {
        "subject": "文档审阅请求",
        "body": "API 设计文档已完成初稿,请各位在 6 月 13 日下班前完成审阅并在文档中标注意见。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "请审阅 API 设计文档。",
        "expected_block": None,
    },
    {
        "subject": "代码评审安排",
        "body": "本周代码评审安排:周一 PR#234(张工)、周三 PR#245(李工)、周五 PR#256(王工)。请大家预留时间参与。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "本周需要安排代码评审。",
        "expected_block": None,
    },
    {
        "subject": "测试用例补充",
        "body": "用户反馈部分边界场景未覆盖,请测试组本周内补充 10 个边界用例,重点关注并发场景。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "测试覆盖需要补充。",
        "expected_block": None,
    },
    {
        "subject": "周会准备",
        "body": "请各团队负责人在周会前提交本周工作完成情况和下周计划,材料统一发到项目经理邮箱。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要准备周会材料。",
        "expected_block": None,
    },
    {
        "subject": "部署窗口预约",
        "body": "本周部署窗口已开放预约,每次 30 分钟。请研发团队在日历系统中预约,并提前 1 天提交部署清单。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "本周需要安排生产部署。",
        "expected_block": None,
    },
    {
        "subject": "培训安排",
        "body": "新员工入职培训安排在 6 月 17 日 9:00,内容包含公司介绍、系统操作、安全规范。请相关部门通知新同事。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要安排新员工培训。",
        "expected_block": None,
    },
    {
        "subject": "会议室预订",
        "body": "周三 14:00-16:00 预订大会议室用于跨部门协作会议,如需调整请提前联系行政。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "需要预订会议室。",
        "expected_block": None,
    },
    {
        "subject": "设备申请",
        "body": "新入职 3 名研发工程师需要配备开发设备,请 IT 部门准备 3 台笔记本和外设,目标 6 月 16 日前到位。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "新员工需要开发设备。",
        "expected_block": None,
    },
    {
        "subject": "系统账号开通",
        "body": "新员工 5 名需要开通业务系统账号,涉及 CRM、ERP、代码仓库。请 IT 部门在入职前完成开通并交付凭证。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要为新员工开通系统账号。",
        "expected_block": None,
    },
    {
        "subject": "客户拜访准备",
        "body": "下周二拜访 A 客户,议程已发送。请销售准备产品演示,技术准备架构图,目标签订年度合作。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "需要拜访重要客户。",
        "expected_block": None,
    },
    {
        "subject": "季度汇报准备",
        "body": "Q2 季度汇报材料请各部门在本月 25 日前提交,内容包含 KPI 完成情况、问题反思、下季度计划。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "需要准备季度汇报。",
        "expected_block": None,
    },
    {
        "subject": "合同审核",
        "body": "B 供应商合同待审核,请法务部门在 6 月 14 日前完成审核,涉及商务条款和合规要求。",
        "tone": "FORMAL",
        "email_category": "TODO",
        "original_body_excerpt": "有合同需要审核。",
        "expected_block": None,
    },
    {
        "subject": "数据备份检查",
        "body": "请运维团队本周完成全量数据备份检查,验证备份文件可恢复性,结果周一提交。",
        "tone": "CONCISE",
        "email_category": "TODO",
        "original_body_excerpt": "需要检查数据备份。",
        "expected_block": None,
    },
]

FYI_EMAILS: list[dict] = [
    # --- 2 封 SENSITIVE_WORD_HIT ---
    {
        "subject": "API 密钥轮换通知",
        "body": "本期系统升级涉及 API 密钥轮换,具体凭证将通过安全渠道单独发送,请知悉。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "系统升级通知。",
        "expected_block": "sensitive",
    },
    {
        "subject": "私钥归档说明",
        "body": "历史项目私钥已统一归档至安全存储,如有查询需求请联系安全团队。",
        "tone": "CONCISE",
        "email_category": "FYI",
        "original_body_excerpt": "历史凭证归档通知。",
        "expected_block": "sensitive",
    },
    # --- 1 封 TEMPLATE_VIOLATION ---
    {
        "subject": "测试草稿:周报模板更新",
        "body": "本周起周报模板已更新,请下载最新版本。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "周报模板更新通知。",
        "expected_block": "template",
    },
    # --- 2 封 FACTUAL_CONFLICT ---
    {
        "subject": "服务中断赔偿",
        "body": "针对上个月服务中断,我们将向所有受影响的客户赔偿 200 元代金券。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "服务中断说明。",
        "expected_block": "factual",
    },
    {
        "subject": "退款政策更新",
        "body": "新政策下,所有退款申请 7 个工作日内处理完成,逾期将赔付 50 元。",
        "tone": "CONCISE",
        "email_category": "FYI",
        "original_body_excerpt": "退款流程更新通知。",
        "expected_block": "factual",
    },
    # --- 15 封 Normal ---
    {
        "subject": "办公室调整通知",
        "body": "因部门扩张,研发部将从 3 楼搬到 5 楼,搬迁时间定在 6 月 20 日(周六),请提前整理个人物品。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "办公室搬迁通知。",
        "expected_block": None,
    },
    {
        "subject": "公司年会通知",
        "body": "2026 年度公司年会将于 7 月 15 日举行,地点待定。请各部门统计参加人数,6 月 20 日前反馈至行政部。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "年会安排通知。",
        "expected_block": None,
    },
    {
        "subject": "系统维护完成",
        "body": "邮件系统例行维护已于今晨 6:00 完成,期间无邮件丢失,服务恢复正常。",
        "tone": "CONCISE",
        "email_category": "FYI",
        "original_body_excerpt": "系统维护完成。",
        "expected_block": None,
    },
    {
        "subject": "新员工入职介绍",
        "body": "研发部本周迎来 3 位新同事,分别是前端工程师张工、后端工程师李工、测试工程师王工,欢迎大家认识。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "新员工入职。",
        "expected_block": None,
    },
    {
        "subject": "本月团队活动",
        "body": "本月团建活动安排在 6 月 22 日,主题:户外徒步+聚餐,详情见活动群,报名截止 6 月 18 日。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "团建活动通知。",
        "expected_block": None,
    },
    {
        "subject": "技术分享预告",
        "body": "下周四 16:00 技术分享:大模型应用实践,主讲人:张总。地点大会议室,欢迎大家参加。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "技术分享安排。",
        "expected_block": None,
    },
    {
        "subject": "Q2 业绩公告",
        "body": "公司 Q2 营收同比增长 18%,环比增长 5%,核心业务表现稳健。详细数据见内部公告。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "季度业绩公告。",
        "expected_block": None,
    },
    {
        "subject": "客户满意度调查结果",
        "body": "Q1 客户满意度调查回收率 78%,综合评分 4.3/5。完整报告已上传至共享盘,请查阅。",
        "tone": "CONCISE",
        "email_category": "FYI",
        "original_body_excerpt": "客户调查结果。",
        "expected_block": None,
    },
    {
        "subject": "产品发布预告",
        "body": "V3.0 产品将于 7 月 1 日正式发布,核心更新包括:性能提升 30%、新用户权限模块、改进的搜索体验。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "产品发布预告。",
        "expected_block": None,
    },
    {
        "subject": "公司福利调整",
        "body": "自 7 月起,公司将增加补充医疗保险和年度体检福利,具体方案见 HR 系统通知。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "福利政策调整。",
        "expected_block": None,
    },
    {
        "subject": "办公用品补充",
        "body": "公共区域办公用品已补充,包括 A4 纸、签字笔、便利贴等。如发现短缺请联系行政。",
        "tone": "CONCISE",
        "email_category": "FYI",
        "original_body_excerpt": "办公用品补充。",
        "expected_block": None,
    },
    {
        "subject": "行业展会信息",
        "body": "2026 中国互联网大会将于 8 月在北京举行,公司可申请参展名额。有兴趣的同事请联系市场部。",
        "tone": "FORMAL",
        "email_category": "FYI",
        "original_body_excerpt": "行业展会信息。",
        "expected_block": None,
    },
    {
        "subject": "公司食堂菜单更新",
        "body": "本周起食堂新增 3 道夏季菜品:凉拌黄瓜、绿豆汤、酸梅汤。欢迎大家品尝并反馈意见。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "食堂菜单更新。",
        "expected_block": None,
    },
    {
        "subject": "员工生日祝福",
        "body": "本月共有 8 位同事生日,公司准备了定制蛋糕和贺卡,具体名单见公告栏。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "员工生日。",
        "expected_block": None,
    },
    {
        "subject": "公司年会摄影征集",
        "body": "年会摄影作品征集开始,主题:「我的 2026」。提交截止 7 月 10 日,优秀作品将展示在公司画廊。",
        "tone": "FRIENDLY",
        "email_category": "FYI",
        "original_body_excerpt": "年会摄影征集。",
        "expected_block": None,
    },
]

SPAM_EMAILS: list[dict] = [
    # --- 2 封 SENSITIVE_WORD_HIT ---
    {
        "subject": "信用卡额度提升",
        "body": "尊敬的客户,您的信用卡号 6222 0219 9900 1234 567 额度可提升至 50 万,点击链接办理。",
        "tone": "CONCISE",
        "email_category": "SPAM",
        "original_body_excerpt": "信用卡推广。",
        "expected_block": "sensitive",
    },
    {
        "subject": "账户验证",
        "body": "您的账户需要验证,请提供短信验证码以确认身份。",
        "tone": "CONCISE",
        "email_category": "SPAM",
        "original_body_excerpt": "账户验证请求。",
        "expected_block": "sensitive",
    },
    # --- 1 封 TEMPLATE_VIOLATION ---
    {
        "subject": "[DRAFT-TEST] 限时优惠",
        "body": "全场满 200 减 50,数量有限,先到先得!",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "限时优惠推广。",
        "expected_block": "template",
    },
    # --- 2 封 FACTUAL_CONFLICT ---
    {
        "subject": "投资理财百分百保证",
        "body": "我们的理财产品百分百保证年化收益 12%,稳赚不赔!",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "理财产品推广。",
        "expected_block": "factual",
    },
    {
        "subject": "特惠活动承诺",
        "body": "凡购买即送 500 元代金券,无条件赔付 1000 元。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "特惠活动。",
        "expected_block": "factual",
    },
    # --- 15 封 Normal(预期 LLM 拒回或建议不回)---
    {
        "subject": "限时秒杀 5 折起",
        "body": "本周限时秒杀,全场 5 折起,数量有限,先到先得。点击查看详情:example.com/sale",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "电商促销。",
        "expected_block": None,
    },
    {
        "subject": "新品上市通知",
        "body": "XYZ 品牌新品上市,前 100 名下单享 8 折优惠,赠精美礼品。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "新品上市。",
        "expected_block": None,
    },
    {
        "subject": "会员积分到期提醒",
        "body": "您的会员积分将于月底到期,5000 积分可兑换 50 元代金券,请尽快使用。",
        "tone": "FORMAL",
        "email_category": "SPAM",
        "original_body_excerpt": "积分到期提醒。",
        "expected_block": None,
    },
    {
        "subject": "节日祝福",
        "body": "端午节将至,XX 电商祝您和家人节日快乐,附赠 100 元购物券。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "节日祝福。",
        "expected_block": None,
    },
    {
        "subject": "退订方式",
        "body": "如不需要此类邮件,请点击退订:example.com/unsubscribe",
        "tone": "CONCISE",
        "email_category": "SPAM",
        "original_body_excerpt": "退订链接。",
        "expected_block": None,
    },
    {
        "subject": "购物车提醒",
        "body": "您购物车中的商品已保留 7 天,部分商品即将售罄,建议尽快结算。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "购物车提醒。",
        "expected_block": None,
    },
    {
        "subject": "调研问卷",
        "body": "为提升服务质量,邀请您参与 5 分钟调研,完成可获 20 元代金券。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "调研问卷。",
        "expected_block": None,
    },
    {
        "subject": "VIP 专享",
        "body": "尊敬的 VIP 客户,您本月专享权益已到账,可在会员中心查看。",
        "tone": "FORMAL",
        "email_category": "SPAM",
        "original_body_excerpt": "VIP 专享权益。",
        "expected_block": None,
    },
    {
        "subject": "新品试用",
        "body": "诚邀您免费试用新品,价值 299 元,数量有限,扫码申请。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "新品试用。",
        "expected_block": None,
    },
    {
        "subject": "课程促销",
        "body": "在线课程 5 折促销,前 200 名报名赠送学习资料包,点击了解详情。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "课程促销。",
        "expected_block": None,
    },
    {
        "subject": "旅游套餐",
        "body": "三亚 5 日游仅需 1999 元,含机票酒店,名额有限,火热报名中。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "旅游套餐。",
        "expected_block": None,
    },
    {
        "subject": "系统通知",
        "body": "您的账户存在异常登录,请尽快点击链接验证身份。",
        "tone": "FORMAL",
        "email_category": "SPAM",
        "original_body_excerpt": "账户异常。",
        "expected_block": None,
    },
    {
        "subject": "中奖通知",
        "body": "恭喜您被抽中为幸运用户,奖金 10000 元,请点击领取。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "中奖通知。",
        "expected_block": None,
    },
    {
        "subject": "品牌故事",
        "body": "XX 品牌 10 周年庆,分享品牌故事,新老客户同享 7 折。",
        "tone": "FRIENDLY",
        "email_category": "SPAM",
        "original_body_excerpt": "品牌周年庆。",
        "expected_block": None,
    },
    {
        "subject": "评论邀请",
        "body": "您购买的商品已签收,邀请您分享使用体验,撰写 50 字以上评论可获 5 元红包。",
        "tone": "FORMAL",
        "email_category": "SPAM",
        "original_body_excerpt": "评论邀请。",
        "expected_block": None,
    },
]

PERSONAL_EMAILS: list[dict] = [
    # --- 3 封 TONE_MISMATCH (PERSONAL + FORMAL/CONCISE) ---
    {
        "subject": "周末见面?",
        "body": "关于周末见面事宜,经审慎考虑,建议于 6 月 15 日(周六)下午 2:00 实施,地点待定。",
        "tone": "FORMAL",
        "email_category": "PERSONAL",
        "original_body_excerpt": "老朋友想周末见面聚聚。",
        "expected_block": "tone",
    },
    {
        "subject": "近期联络",
        "body": "因近期工作繁忙,拟于 6 月 18 日(周三)晚间 7:00 与您会面,届时详谈。",
        "tone": "FORMAL",
        "email_category": "PERSONAL",
        "original_body_excerpt": "好久没见的朋友想见面。",
        "expected_block": "tone",
    },
    {
        "subject": "周末安排",
        "body": "周末已预约活动,改期至下周三晚上,届时再约。",
        "tone": "CONCISE",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友想约周末吃饭。",
        "expected_block": "tone",
    },
    # --- 2 封 SENSITIVE_WORD_HIT ---
    {
        "subject": "身份信息确认",
        "body": "我妈让我问问,办医保需要你的身份证号,你看方便发我下不?",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友家人需要帮忙。",
        "expected_block": "sensitive",
    },
    {
        "subject": "密码提醒",
        "body": "你账号的银行密码快到期了,记得去改下,免得影响使用~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友善意提醒。",
        "expected_block": "sensitive",
    },
    # --- 1 封 TEMPLATE_VIOLATION ---
    {
        "subject": "测试草稿:明晚聚会",
        "body": "明晚老地方见,记得带身份证哦~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友聚会邀请。",
        "expected_block": "template",
    },
    # --- 2 封 FACTUAL_CONFLICT ---
    {
        "subject": "聚会 AA 退款",
        "body": "上次聚会我多付了 200,大家 AA 一下,我退给你 50 哈~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友想约聚会,谈 AA 事宜。",
        "expected_block": "factual",
    },
    {
        "subject": "旅行纪念品",
        "body": "我从云南带回来一些纪念品,价值 500 块,免费送你哦~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友旅行回来想送礼物。",
        "expected_block": "factual",
    },
    # --- 12 封 Normal ---
    {
        "subject": "好久不见~",
        "body": "最近怎么样?好久没联系了,想约你周末出来聚聚,我发现一家新餐厅很不错,你有空吗?",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "老朋友想聚聚。",
        "expected_block": None,
    },
    {
        "subject": "生日快乐!",
        "body": "今天是你 30 岁生日,虽然不能当面庆祝,但这份祝福一定要送到~祝你新的一岁心想事成!",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友过生日。",
        "expected_block": None,
    },
    {
        "subject": "推荐一本书",
        "body": "最近读了《人类简史》,感觉很有启发,推荐给你。如果你喜欢这类书,我们可以交流下心得~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友想推荐书。",
        "expected_block": None,
    },
    {
        "subject": "孩子升学宴邀请",
        "body": "我家孩子考上大学了,下个月办升学宴,想请你来家里坐坐,具体时间我再发你~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友邀请参加升学宴。",
        "expected_block": None,
    },
    {
        "subject": "周末爬山约吗?",
        "body": "周末天气不错,想约你去爬山,顺便野餐。带些水和零食,记得穿运动鞋哈~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友约周末活动。",
        "expected_block": None,
    },
    {
        "subject": "感谢照顾",
        "body": "上次你帮我搬家真的太感谢了!等你方便的时候来家里吃顿便饭,让我和家人当面谢谢你~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "感谢朋友帮忙。",
        "expected_block": None,
    },
    {
        "subject": "推荐咖啡店",
        "body": "公司附近新开了一家咖啡店,环境很棒,咖啡也不错,推荐你下次来尝尝~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友推荐地方。",
        "expected_block": None,
    },
    {
        "subject": "乔迁新居",
        "body": "下周末我家办乔迁 party,记得来玩!准备了甜点和饮料,带家人一起哈~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友搬新家邀请。",
        "expected_block": None,
    },
    {
        "subject": "近期心情",
        "body": "最近工作有点累,想找个人聊聊。你这周末方便吗?一起喝杯咖啡吧~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友想倾诉。",
        "expected_block": None,
    },
    {
        "subject": "推荐电影",
        "body": "最近看了《XXX》这部电影,拍得不错,推荐你去看!我们可以约个时间一起~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友推荐电影。",
        "expected_block": None,
    },
    {
        "subject": "借书",
        "body": "你之前说的那本《XXX》能借我看看吗?我下周还你~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "朋友想借书。",
        "expected_block": None,
    },
    {
        "subject": "感谢推荐",
        "body": "上次你推荐的那个餐厅真的不错,我和家人都很喜欢,谢谢你的推荐!下次一起再约~",
        "tone": "FRIENDLY",
        "email_category": "PERSONAL",
        "original_body_excerpt": "感谢朋友推荐。",
        "expected_block": None,
    },
]

ALL_EMAILS: list[dict] = []
for source in (URGENT_EMAILS, TODO_EMAILS, FYI_EMAILS, SPAM_EMAILS, PERSONAL_EMAILS):
    for index, email in enumerate(source, start=1):
        email_with_id = dict(email)
        category = email_with_id["email_category"]
        email_with_id["email_id"] = f"{category.lower()}_{index:02d}"
        ALL_EMAILS.append(email_with_id)

assert len(ALL_EMAILS) == 100, f"应正好 100 封, 实际 {len(ALL_EMAILS)}"


# ==================== Spike Runner ====================
def run_spike(output_dir: Path) -> None:
    """跑 spike + 收集指标 + 写报告."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"spike_review_100_{timestamp}.json"
    report_path = output_dir / f"spike_review_100_{timestamp}.md"

    print("🚀 D4.7.4.10 spike — 100 封合成邮件审阅")
    print(f"   输出目录: {output_dir}")
    print(f"   时间戳:   {timestamp}")
    print("   EmailReviewer 初始化...")

    reviewer = EmailReviewer()
    drafts = [
        {
            "subject": e["subject"],
            "body": e["body"],
            "tone": e["tone"],
            "email_category": e["email_category"],
            "original_body_excerpt": e["original_body_excerpt"],
            "email_id": e["email_id"],
        }
        for e in ALL_EMAILS
    ]

    print("   100 封邮件开始审阅(LLM 调用 < 5s/封,总时长 ~ 5-8 分钟)...")
    start = time.time()
    results = reviewer.review_batch(drafts)
    total_elapsed = time.time() - start
    print(f"   ✓ 跑完,总耗时 {total_elapsed:.1f}s")
    print()

    # ===== 统计 =====
    counters: Counter[str] = Counter()
    latencies: list[int] = []
    raw_results: list[dict] = []
    matches_expected = {"total": 0, "mismatch": []}

    for email, result in zip(ALL_EMAILS, results, strict=False):
        if isinstance(result, ReviewBlockedResult):
            counters["business_blocked"] += 1
            counters[f"block:{result.reason.value}"] += 1
            actual_block = result.reason.value
            entry = {
                "email_id": email["email_id"],
                "category": email["email_category"],
                "tone": email["tone"],
                "expected_block": email["expected_block"],
                "actual_block": actual_block,
                "reason": result.reason.value,
                "blocked_word": result.blocked_word,
                "flagged_issues": list(result.flagged_issues),
                "review_summary": result.review_summary,
                "latency_ms": 0,  # 本地阻断无 LLM 调用
            }
        elif isinstance(result, ReviewResult):
            counters["passed" if result.review_passed else "review_rejected"] += 1
            actual_block = "passed" if result.review_passed else "review_rejected"
            latencies.append(result.latency_ms)
            entry = {
                "email_id": email["email_id"],
                "category": email["email_category"],
                "tone": email["tone"],
                "expected_block": email["expected_block"],
                "actual_block": actual_block,
                "review_passed": result.review_passed,
                "flagged_issues": list(result.flagged_issues),
                "review_summary": result.review_summary,
                "model_full_id": result.model_full_id,
                "latency_ms": result.latency_ms,
            }
        elif isinstance(result, ReviewFailureResult):
            counters["failure"] += 1
            actual_block = "failure"
            entry = {
                "email_id": email["email_id"],
                "category": email["email_category"],
                "tone": email["tone"],
                "expected_block": email["expected_block"],
                "actual_block": "failure",
                "last_error": result.last_error,
                "consecutive_review_failures": result.consecutive_review_failures,
            }
        else:  # ValueError / KeyError
            counters["error"] += 1
            actual_block = "error"
            entry = {
                "email_id": email["email_id"],
                "category": email["email_category"],
                "tone": email["tone"],
                "expected_block": email["expected_block"],
                "actual_block": "error",
                "exception": str(result),
            }
        raw_results.append(entry)

        # 期望 vs 实际
        expected = email["expected_block"]
        if expected is None:
            # 期望 LLM 判定
            if actual_block in ("passed", "review_rejected", "failure", "error"):
                matches_expected["total"] += 1
        elif (
            expected == "sensitive"
            and actual_block == "sensitive_word_hit"
            or expected == "tone"
            and actual_block == "tone_mismatch"
            or expected == "template"
            and actual_block == "template_violation"
            or expected == "factual"
            and actual_block == "factual_conflict"
        ):
            matches_expected["total"] += 1
        else:
            matches_expected["mismatch"].append(
                {
                    "email_id": email["email_id"],
                    "category": email["email_category"],
                    "expected": expected,
                    "actual": actual_block,
                }
            )

    # ===== 写 JSON =====
    raw_path.write_text(
        json.dumps(
            {
                "timestamp": timestamp,
                "total_elapsed_sec": round(total_elapsed, 2),
                "counters": dict(counters),
                "latency_stats": {
                    "count": len(latencies),
                    "min_ms": min(latencies) if latencies else 0,
                    "max_ms": max(latencies) if latencies else 0,
                    "avg_ms": int(statistics.mean(latencies)) if latencies else 0,
                    "p50_ms": int(statistics.median(latencies)) if latencies else 0,
                    "p95_ms": int(statistics.quantiles(latencies, n=20)[18])
                    if len(latencies) >= 20
                    else 0,
                },
                "expected_match": {
                    "matched": matches_expected["total"],
                    "mismatch_count": len(matches_expected["mismatch"]),
                    "mismatches": matches_expected["mismatch"],
                },
                "results": raw_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"   📦 原始结果: {raw_path}")

    # ===== 写 Markdown 报告 =====
    report_lines = [
        "# D4.7.4.10 Spike 报告 — 100 封合成邮件审阅",
        "",
        f"> **时间**: {timestamp}  ",
        f"> **总耗时**: {total_elapsed:.1f}s  ",
        "> **总封数**: 100 封(URGENT/TODO/FYI/SPAM/PERSONAL 各 20 封)",
        f"> **LLM 调用**: {len(latencies)} 次(本地阻断不调用 LLM)",
        "",
        "---",
        "",
        "## 1. 总体结果",
        "",
        "| 类型 | 数量 | 占比 |",
        "|------|------|------|",
        f"| ✅ review_passed | {counters.get('passed', 0)} | {counters.get('passed', 0)}% |",
        f"| ❌ review_rejected(LLM 拒) | {counters.get('review_rejected', 0)} | {counters.get('review_rejected', 0)}% |",
        f"| 🛑 business_blocked(本地阻断) | {counters.get('business_blocked', 0)} | {counters.get('business_blocked', 0)}% |",
        f"| ⚠️ failure(LLM 全链失败) | {counters.get('failure', 0)} | {counters.get('failure', 0)}% |",
        f"| 💥 error(入参错误) | {counters.get('error', 0)} | {counters.get('error', 0)}% |",
        "",
    ]

    # 阻断原因分布
    report_lines.extend(
        [
            "## 2. 业务阻断原因分布",
            "",
            "| 阻断原因 | 数量 | 预期 | 一致性 |",
            "|----------|------|------|--------|",
            f"| sensitive_word_hit | {counters.get('block:sensitive_word_hit', 0)} | 12 | {'✅' if counters.get('block:sensitive_word_hit', 0) == 12 else '⚠️'} |",
            f"| tone_mismatch | {counters.get('block:tone_mismatch', 0)} | 5 | {'✅' if counters.get('block:tone_mismatch', 0) == 5 else '⚠️'} |",
            f"| template_violation | {counters.get('block:template_violation', 0)} | 5 | {'✅' if counters.get('block:template_violation', 0) == 5 else '⚠️'} |",
            f"| factual_conflict | {counters.get('block:factual_conflict', 0)} | 10 | {'✅' if counters.get('block:factual_conflict', 0) == 10 else '⚠️'} |",
            f"| **合计** | **{counters.get('business_blocked', 0)}** | **32** | {'✅' if counters.get('business_blocked', 0) == 32 else '⚠️'} |",
            "",
        ]
    )

    # 延迟统计
    if latencies:
        report_lines.extend(
            [
                "## 3. LLM 延迟统计",
                "",
                "| 指标 | 数值 |",
                "|------|------|",
                f"| 调用次数 | {len(latencies)} |",
                f"| 最小 | {min(latencies)} ms |",
                f"| 最大 | {max(latencies)} ms |",
                f"| 平均 | {int(statistics.mean(latencies))} ms |",
                f"| 中位 (P50) | {int(statistics.median(latencies))} ms |",
                f"| P95 | {int(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else 'N/A'} ms |",
                f"| 目标 (< 5000ms) | {'✅ 达标' if max(latencies) < 5000 else '❌ 超标'} |",
                "",
            ]
        )

    # 期望匹配
    report_lines.extend(
        [
            "## 4. 期望 vs 实际匹配",
            "",
            f"- **匹配数**: {matches_expected['total']} / 100",
            f"- **失配数**: {len(matches_expected['mismatch'])}",
            "",
        ]
    )
    if matches_expected["mismatch"]:
        report_lines.extend(
            [
                "### 失配详情",
                "",
                "| email_id | category | expected | actual |",
                "|----------|----------|----------|--------|",
            ]
        )
        for mm in matches_expected["mismatch"]:
            report_lines.append(
                f"| {mm['email_id']} | {mm['category']} | {mm['expected']} | {mm['actual']} |"
            )
        report_lines.append("")

    # 按 category 分组统计
    report_lines.extend(
        [
            "## 5. 按邮件分类分组",
            "",
            "| Category | Total | business_blocked | passed | review_rejected | failure |",
            "|----------|-------|------------------|--------|-----------------|---------|",
        ]
    )
    for category in ("URGENT", "TODO", "FYI", "SPAM", "PERSONAL"):
        cat_results = [r for r in raw_results if r["category"] == category]
        if not cat_results:
            continue
        blocked = sum(
            1
            for r in cat_results
            if r["actual_block"].startswith("sensitive")
            or r["actual_block"] in ("tone_mismatch", "template_violation", "factual_conflict")
        )
        passed = sum(1 for r in cat_results if r["actual_block"] == "passed")
        rejected = sum(1 for r in cat_results if r["actual_block"] == "review_rejected")
        failure = sum(1 for r in cat_results if r["actual_block"] == "failure")
        report_lines.append(
            f"| {category} | {len(cat_results)} | {blocked} | {passed} | {rejected} | {failure} |"
        )
    report_lines.append("")

    # 阻断示例
    report_lines.extend(
        [
            "## 6. 阻断示例(各 1 例)",
            "",
            "### 6.1 sensitive_word_hit",
        ]
    )
    for r in raw_results:
        if r["actual_block"] == "sensitive_word_hit":
            report_lines.extend(
                [
                    f"- **email_id**: {r['email_id']}",
                    f"  - category: {r['category']}, tone: {r['tone']}",
                    f"  - blocked_word: `{r.get('blocked_word', '')}`",
                    f"  - flagged_issues: {r['flagged_issues']}",
                    "",
                ]
            )
            break

    for block_reason in ("tone_mismatch", "template_violation", "factual_conflict"):
        report_lines.append(
            f"### 6.{['tone_mismatch', 'template_violation', 'factual_conflict'].index(block_reason) + 2} {block_reason}"
        )
        for r in raw_results:
            if r["actual_block"] == block_reason:
                report_lines.extend(
                    [
                        f"- **email_id**: {r['email_id']}",
                        f"  - category: {r['category']}, tone: {r['tone']}",
                        f"  - flagged_issues: {r['flagged_issues']}",
                        f"  - review_summary: {r['review_summary'][:100]}",
                        "",
                    ]
                )
                break

    # 异常 case
    anomalies = [
        r for r in raw_results if r["actual_block"] in ("failure", "error", "review_rejected")
    ]
    if anomalies:
        report_lines.extend(
            [
                "## 7. 异常 Case(review_rejected / failure / error)",
                "",
                f"共 {len(anomalies)} 例:",
                "",
            ]
        )
        for r in anomalies[:5]:  # 仅展示前 5 例
            report_lines.append(
                f"- **{r['email_id']}** ({r['category']}/{r['tone']}): {r['actual_block']}"
            )
        report_lines.append("")

    # 结论
    report_lines.extend(
        [
            "## 8. 结论与建议",
            "",
            f"- **业务阻断**: {counters.get('business_blocked', 0)}/{counters.get('business_blocked', 0) + counters.get('passed', 0) + counters.get('review_rejected', 0) + counters.get('failure', 0) + counters.get('error', 0)} 命中本地硬规则",
            f"- **LLM 调用延迟**: 平均 {int(statistics.mean(latencies)) if latencies else 0}ms, P95 {(int(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else 0)}ms",
            f"- **匹配度**: {matches_expected['total']}/100",
            "",
        ]
    )

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"   📝 报告:     {report_path}")
    print()
    print("=== Spike 跑完 ===")
    print(
        f"  passed={counters.get('passed', 0)}, "
        f"rejected={counters.get('review_rejected', 0)}, "
        f"blocked={counters.get('business_blocked', 0)}, "
        f"failure={counters.get('failure', 0)}, "
        f"error={counters.get('error', 0)}"
    )
    if latencies:
        print(
            f"  LLM latency: min={min(latencies)}ms / "
            f"avg={int(statistics.mean(latencies))}ms / "
            f"p95={int(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else 0}ms / "
            f"max={max(latencies)}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="D4.7.4.10 spike — 100 封合成邮件审阅")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "spike",
        help="报告输出目录(默认 output/spike/)",
    )
    args = parser.parse_args()
    run_spike(args.output_dir)


if __name__ == "__main__":
    main()
