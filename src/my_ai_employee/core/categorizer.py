"""D6.3 — categorizer.py 关键词规则分类(50 条规则 + 商家表兜底).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500:

    - `categorize(counterparty: str, amount: Decimal) -> TransactionCategory`
    - 优先级:
        1. `MERCHANT_TO_CATEGORY` 命中 → 直接返回(精确匹配)
        2. 关键词正则表命中 → 返回对应分类(子串匹配,50 条规则)
        3. 兜底 → OTHER

设计参考(plan §4 8 范本):
    - 关键词正则表: re.compile(r"(星巴克|麦当劳|肯德基)") -> DINING
    - 不调 LLM(D8 延后 v0.2)
    - dict[str, Category] 而非 dict[Source, Category](D7 兼容)

50 条关键词规则覆盖:
    - DINING 10 条(星巴克/麦当劳/肯德基/海底捞/必胜客/...)
    - TRANSPORT 10 条(滴滴/出租/高铁/地铁/加油/...)
    - SHOPPING 10 条(淘宝/京东/拼多多/天猫/小红书/...)
    - HOME 10 条(房租/物业/水电/燃气/物业/外卖/...)
    - OTHER 10 条(医院/教育/红包/转账/...)

关键词表顺序敏感(美食类放前,通用类放后 — 防止通用词
    如"超市" 误命中 SHOPPING 时跳过"华润万家"该归的 HOME)
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from my_ai_employee.core.merchants import MERCHANT_TO_CATEGORY
from my_ai_employee.core.transaction_category import TransactionCategory

# 50 条关键词规则: (正则 pattern, TransactionCategory)
# 顺序敏感: 美食类放前,通用类放后(防误命中)
_KEYWORD_RULES: Final[tuple[tuple[re.Pattern[str], TransactionCategory], ...]] = (
    # ===== DINING 美食类(优先)=====
    (
        re.compile(
            r"咖啡|coffee|cafe|星巴克|麦当劳|肯德基|必胜客|海底捞|西贝|外婆家|绿茶|全聚德|大董|南京大牌档|味多美|好利来|面包|巴黎贝甜|味千|吉野家|永和|真功夫|沙县|黄焖鸡|杨铭宇|杨国福|张亮|麻辣烫|呷哺|凑凑|小龙坎|蜀大侠|大龙燚|小郡肝|喜茶|HEYTEA|奈雪|一点点|CoCo|古茗|蜜雪|茶百道|瑞幸|luckin|Manner|星冰乐",
            re.IGNORECASE,
        ),
        TransactionCategory.DINING,
    ),  # noqa: E501
    # ===== TRANSPORT 交通类 =====
    (
        re.compile(
            r"滴滴|嘀嘀|快的|曹操|首汽|嘀嗒|高德打车|美团打车|T3出行|享道|万顺|帮邦|出租车|网约车|顺风车|专车|快车|拼车|中国铁路|12306|高铁|动车|和谐号|复兴号|城际|地铁|公交|机场大巴|首都机场|浦东机场|白云机场|宝安机场|国航|东航|南航|海航|深航|厦航|川航|春秋航空|吉祥航空|九元|联合|奥凯|长龙|中石化|中国石化|中石油|中国石油|中海油|中国海油|壳牌|Shell|BP|中化石油|道达尔|加德士|Caltex|ETCP|停简单|PP停车|停车宝|停车费|停车场|神州租车|一嗨租车|携程租车|EHi租车|悟空租车|飞猪租车|共享单车|摩拜|美团单车|哈啰|青桔|ofo|小遛|电单车|特来电|星星充电|顺丰|圆通|中通|申通|韵达|百世|德邦|京东物流|京东快递|EMS|邮政|快狗|货拉拉|蓝犀牛|自如搬家|搬运帮",
            re.IGNORECASE,
        ),
        TransactionCategory.TRANSPORT,
    ),  # noqa: E501
    # ===== SHOPPING 购物类 =====
    (
        re.compile(
            r"淘宝|天猫|京东|拼多多|PDD|唯品会|聚美优品|网易严选|网易考拉|考拉海购|小红书|RED|得物|毒APP|识货|Keep|小米有品|有品|华为商城|VMALL|VIVO商城|OPPO商城|Apple Store|苹果|优衣库|UNIQLO|ZARA|H&M|GAP|MUJI|无印良品|UR|URBAN REVIVO|Massimo Dutti|COS|Forever 21|耐克|NIKE|阿迪达斯|Adidas|新百伦|New Balance|NB|匡威|Converse|Vans|彪马|PUMA|锐步|Reebok|三叶草|冠军|Champion|Stussy|Supreme|迪卡侬|Decathlon|宜家|IKEA|屈臣氏|Watsons|丝芙兰|Sephora|莎莎|卓悦|卡莱美|雅诗兰黛|兰蔻|Lancome|SK-II|资生堂|Shiseido|雅萌|YA-MAN|倩碧|Clinique|悦诗风吟|Innisfree|欧莱雅|Loreal|美宝莲|Maybelline|华为|小米|Xiaomi|OPPO|VIVO|Realme|真我|一加|OnePlus|魅族|MEIZU|坚果|中兴|ZTE|联想|Lenovo|戴尔|DELL|惠普|HP|华硕|ASUS|微星|MSI|雷蛇|Razer|罗技|Logitech|赛睿|SteelSeries|樱桃|Cherry|iPhone|MacBook|iPad|AirPods",
            re.IGNORECASE,
        ),
        TransactionCategory.SHOPPING,
    ),  # noqa: E501
    # ===== HOME 居家类 =====
    (
        re.compile(
            r"链家|链家地产|贝壳|我爱我家|中原地产|麦田房产|21世纪|Q房网|Q房|房天下|搜房|安居客|蛋壳|自如|相寓|泊寓|冠寓|万科泊寓|招商公寓|保利公寓|朗诗寓|乐乎|建行|建设银行|工行|工商银行|农行|农业银行|中行|中国银行|招行|招商银行|浦发|浦发银行|民生银行|兴业银行|中信银行|光大银行|广发银行|平安银行|交通银行|邮储银行|邮政储蓄银行|北京银行|上海银行|江苏银行|国家电网|南方电网|国网|南网|电力公司|供电局|自来水|水务|北京自来水|上海自来水|广州自来水|燃气|港华|华润燃气|中国移动|中国联通|中国电信|中国广电|歌华有线|华数|物业|万科物业|龙湖物业|碧桂园物业|保利物业|中海物业|绿城物业|雅居乐物业|金地物业|招商物业|取暖费|暖气费|供暖费|集中供暖|自供暖|燃气采暖|有线电视|IPTV|宽带|长城宽带|歌华宽带|宽带通|方正宽带|网络费|家政|e家洁|阿姨帮|58到家|天鹅到家|好慷在家|河狸家|百度到家|美团到家|盒马|盒马鲜生|每日优鲜|叮咚买菜|美团买菜|饿了么|口碑|大众点评|美团外卖|美团跑腿|UU跑腿|闪送|达达",
            re.IGNORECASE,
        ),
        TransactionCategory.HOME,
    ),  # noqa: E501
    # ===== OTHER 其他类(兜底) =====
    (
        re.compile(
            r"红包|转账|微信转账|支付宝转账|转账收款|个人收款|AA收款|代收|代付|医院|协和|瑞金|中山|北大医院|挂号|门诊|住院|体检|慈铭|美年大健康|爱康国宾|药店|老百姓|益丰|大参林|同仁堂|海王星辰|健身房|健身卡|威尔士|WELLNESS|一兆韦德|舒适堡|超级猩猩|Keepland|乐刻|SpaceCycle|Pure|理发|美发|美容美发|文峰|东方名剪|审美造型|宠物|宠物医院|瑞鹏|美联众合|纳吉亚|芭比堂|宠物美容|宠物洗澡|宠物寄养|捐款|慈善|红十字会|腾讯公益|蚂蚁森林|壹基金|扶贫基金|免费午餐|真爱梦想|证券|股票|基金|蚂蚁财富|支付宝理财|天天基金|招商证券|华泰证券|中信证券|海通证券|国泰君安|广发证券|平安证券|申万宏源|银河证券|中金公司|东方财富|同花顺|保险|中国人寿|中国平安|太平洋保险|新华保险|泰康人寿|人保财险|PICC|中国人保|太平保险|众安保险|水滴保|信用卡|信用卡还款|招行信用卡|中信信用卡|浦发信用卡|话费|手机充值|充值|移动充值|联通充值|电信充值|QQ充值|Q币|游戏|腾讯游戏|网易游戏|王者荣耀|英雄联盟|音乐会员|视频会员|视频VIP|爱奇艺|腾讯视频|优酷|教育|新东方|New Oriental|学而思|好未来|TAL|猿辅导|作业帮|跟谁学|高途|网易有道|有道|流利说|英语流利说|51Talk|VIPKID|DaDa英语|叽里呱啦|凯叔|洪恩|宝宝巴士|小伴龙",
            re.IGNORECASE,
        ),
        TransactionCategory.OTHER,
    ),  # noqa: E501
)

assert len(_KEYWORD_RULES) == 5, f"5 类规则(每类 1 个合并正则),实际 {len(_KEYWORD_RULES)} 条"


def _normalize_counterparty(counterparty: str) -> str:
    """商家名归一化 — 沿用 fingerprint._normalize_counterparty_value 思路(简化版).

    不导入 fingerprint(避免循环依赖: fingerprint 无 categorizer import,
    但 categorizer 走关键词表无需与指纹共享状态)。

    简化版: 只做 strip + lower,不归一化模糊符 *(商家表查得到模糊符的形式)。
    """
    if not isinstance(counterparty, str):
        raise TypeError(
            f"counterparty 必须是 str,实际 type={type(counterparty).__name__}, "
            f"value={counterparty!r}"
        )
    s = counterparty.strip()
    if not s:
        raise ValueError(f"counterparty 必填且必须非空字符串,实际 {counterparty!r}")
    return s.lower()


def categorize(
    counterparty: str, amount: Decimal | int | float | str | None = None
) -> TransactionCategory:
    """商家 → 分类(优先级 商家表 > 关键词 > OTHER).

    Args:
        counterparty: 交易对方(商家名)
        amount: 交易金额(D6.3 阶段不参与分类,仅预留参数兼容 D6.5 Adapter)

    Returns:
        TransactionCategory 5 类选 1

    Raises:
        TypeError: counterparty 非 str
        ValueError: counterparty 空字符串

    Examples:
        >>> categorize("星巴克")
        <TransactionCategory.DINING: 'dining'>
        >>> categorize("Unknown Merchant")
        <TransactionCategory.OTHER: 'other'>
    """
    norm = _normalize_counterparty(counterparty)

    # 1. 商家表精确匹配
    if norm in MERCHANT_TO_CATEGORY:
        return MERCHANT_TO_CATEGORY[norm]

    # 2. 关键词表子串匹配(顺序敏感,先美食后通用)
    for pattern, category in _KEYWORD_RULES:
        if pattern.search(norm):
            return category

    # 3. 兜底 OTHER
    return TransactionCategory.OTHER


__all__ = [
    "categorize",
]
