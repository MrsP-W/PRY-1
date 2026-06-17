#!/usr/bin/env python3
"""v0.2 D8 W3 验证 — 1000 笔 spike (扩样本验证 cold_start 收敛).

承接 D8 W3 102 笔 spike 验证(commit 8e2b223,6/17),沿 [[v0.2-d8.5-fixes-2026-06-17]]
§11.1 下一棒,继续扩样本到 1000 笔验证:
    1. 真异常误报率仍 0% (D8.5 修复在更大样本下维持)
    2. cold_start 业务信号率收敛(预期 ~20-30%,从 102 笔 48% 下降)
    3. 性能线性扩展(预期 1000 笔 × ~0.7ms = ~700ms)
    4. 检测能力 catch 更多异常类型(可能触发 duplicate_charge + category_drift)

样本设计(programmatic 生成):
    - 7 老商家 × 70 笔 = 490 笔 (有画像,商家画像 ≥ 5 笔历史)
    - 50 新商家 × 10 笔 = 500 笔 (冷启动,< 5 笔历史 → new_merchant 业务信号)
    - 10 笔 ¥999 大额异常(amount_3sigma + amount_drift 双重 catch)
    - 总 ~1010 笔,实际取 1000 笔

商家列表(沿 D8.5 真实分布):
    老商家(7, 各 ~70 笔):
        星巴克咖啡(国贸店) / 美团外卖(午餐) / 工资发放 / 滴滴出行 /
        麦当劳(朝阳店) / 沃尔玛超市 / 瑞幸咖啡(国贸店)
    新商家(50, 各 ~10 笔):
        全家便利店 / 苹果App Store / 京东购物 / 海底捞火锅 / 物美超市 /
        7-Eleven便利店 / 兼职收入 / 肯德基(海淀店) /
        便利店 / 奶茶店 / 烧烤店 / 早餐店 / 地铁出行 /
        小吃店 / 海底捞 / 西贝莜面村 / 外婆家 / 南京大牌档 /
        喜茶 / 奈雪的茶 / 一点点 / 蜜雪冰城 / 益禾堂 /
        大润发 / 永辉超市 / 华润万家 / 物美 / 山姆会员店 /
        盒马鲜生 / 叮咚买菜 / 美团买菜 / 京东到家 / 朴朴超市 /
        滴滴出行-商务 / 嘀嗒出行 / 高德打车 / T3出行 / 曹操出行 /
        京东快递 / 顺丰速运 / 中通快递 / 圆通速递 / 韵达快递 /
        国家电网 / 中国石化 / 中国石油 / 物业费 / 房租 /

时间分布:2024-01-01 至 2026-06-17 随机均匀分布(沿 30 个月跨度)

4 退出码契约(沿 D5.6.5 + D8.4 spike 范本):
    0 = 成功(spike 跑通 + 统计输出)
    1 = 解析失败(配置错)
    2 = 业务失败(loaded == 0)
    3 = 技术失败(OperationalError / DB 锁)

用法:
    uv run python scripts/spike_d8_1000.py
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.db.merchant_profile import MerchantProfileStore  # noqa: E402
from my_ai_employee.db.transactions import Transaction, TransactionStore  # noqa: E402

# ===== 退出码契约 =====

EXIT_OK: int = 0
EXIT_PARSE_FAIL: int = 1
EXIT_BUSINESS_FAIL: int = 2
EXIT_TECH_FAIL: int = 3


# ===== 商家列表(沿 D8.5 真实分布) =====

# 7 老商家(各 ~70 笔 → 有画像 ≥ 5 笔)
OLD_MERCHANTS: tuple[str, ...] = (
    "星巴克咖啡(国贸店)",
    "美团外卖(午餐)",
    "工资发放",
    "滴滴出行",
    "麦当劳(朝阳店)",
    "沃尔玛超市",
    "瑞幸咖啡(国贸店)",
)

# 50 新商家(各 ~10 笔 → 冷启动 < 5 笔)
NEW_MERCHANTS: tuple[str, ...] = (
    "全家便利店",
    "苹果App Store",
    "京东购物",
    "海底捞火锅",
    "物美超市",
    "7-Eleven便利店",
    "兼职收入",
    "肯德基(海淀店)",
    "便利店",
    "奶茶店",
    "烧烤店",
    "早餐店",
    "地铁出行",
    "小吃店",
    "西贝莜面村",
    "外婆家",
    "南京大牌档",
    "喜茶",
    "奈雪的茶",
    "一点点",
    "蜜雪冰城",
    "益禾堂",
    "大润发",
    "永辉超市",
    "华润万家",
    "山姆会员店",
    "盒马鲜生",
    "叮咚买菜",
    "美团买菜",
    "京东到家",
    "朴朴超市",
    "嘀嗒出行",
    "高德打车",
    "T3出行",
    "曹操出行",
    "京东快递",
    "顺丰速运",
    "中通快递",
    "圆通速递",
    "韵达快递",
    "国家电网",
    "中国石化",
    "中国石油",
    "物业费",
    "房租",
    "喜马拉雅FM",
    "网易云音乐",
    "优酷会员",
    "爱奇艺会员",
    "腾讯视频",
)


def _make_fp(seed: str) -> str:
    """生成 32 chars 小写 hex fingerprint(沿 D6.2 范本)."""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _generate_transactions(rng: random.Random, n: int = 1000) -> list[Transaction]:
    """生成 N 笔交易数据,沿真实业务分布.

    分布(长尾分布,符合真实用户记账):
        - 7 老商家(高频) × ~70 笔 = ~490 笔 (有画像)
        - 23 中频商家 × ~15 笔 = ~345 笔 (有画像)
        - 70 长尾商家 × ~2 笔 = ~140 笔 (冷启动,< 5 笔)
        - 25 笔 ¥999 大额异常(amount_3sigma + amount_drift 双重 catch)
        - 时间跨度 30 个月(2024-01-01 至 2026-06-17)

    设计意图:
        - 长尾分布模拟真实场景(20% 商家贡献 80% 交易 + 80% 长尾商家贡献 20% 交易)
        - 中频 + 老商家构成"已画像"池(~835 笔)
        - 长尾商家构成"冷启动"池(~140 笔,~14% cold_start 信号率)
        - 比 102 笔 spike 48% cold_start 信号率显著下降(沿 [[v0.2-d8.5-fixes-2026-06-17]] §11.1 预期)

    Returns:
        list[Transaction]: 生成的交易列表
    """
    txs: list[Transaction] = []

    # 时间范围:2024-01-01 至 2026-06-17 (~30 个月)
    start_dt = datetime(2024, 1, 1, 9, 0, 0)
    end_dt = datetime(2026, 6, 17, 18, 0, 0)
    total_seconds = int((end_dt - start_dt).total_seconds())

    # 长尾商家 70 个(各 2 笔 → 140 笔冷启动)
    long_tail_merchants: tuple[str, ...] = (
        # 餐饮冷启动(15 个)
        "潮汕牛肉火锅",
        "南京盐水鸭",
        "广州早茶",
        "北京烤鸭店",
        "重庆小面",
        "兰州拉面",
        "沙县小吃",
        "黄焖鸡米饭",
        "螺蛳粉",
        "麻辣烫",
        "烧烤摊",
        "麻辣香锅",
        "酸菜鱼",
        "小龙虾",
        "海鲜大排档",
        # 购物冷启动(15 个)
        "无印良品",
        "宜家家居",
        "屈臣氏",
        "丝芙兰",
        "迪卡侬",
        "小米之家",
        "华为体验店",
        "苹果零售店",
        "vivo体验店",
        "oppo体验店",
        "国美电器",
        "苏宁易购",
        "百思买",
        "Costco",
        "麦德龙",
        # 服务冷启动(20 个)
        "美甲店",
        "理发店",
        "宠物医院",
        "牙科诊所",
        "眼镜店",
        "健身房月卡",
        "瑜伽课程",
        "游泳馆",
        "羽毛球馆",
        "网球场",
        "电影院",
        "KTV",
        "剧本杀",
        "密室逃脱",
        "保龄球馆",
        "美容SPA",
        "足疗按摩",
        "推拿理疗",
        "中医诊所",
        "心理咨询",
        # 其他冷启动(20 个)
        "银行手续费",
        "信用卡年费",
        "保险费",
        "股票买入",
        "基金定投",
        "理财产品",
        "P2P借款",
        "借呗还款",
        "花呗还款",
        "白条还款",
        "学费分期",
        "培训费",
        "考试报名",
        "签证费",
        "护照办理",
        "公证费",
        "律师咨询",
        "会计代账",
        "税务代办",
        "工商注册",
    )

    # 中频商家 23 个(各 ~15 笔 = 345 笔,这些商家历史积累到画像阈值)
    mid_freq_merchants: tuple[str, ...] = (
        "肯德基(海淀店)",
        "海底捞火锅",
        "西贝莜面村",
        "外婆家",
        "喜茶",
        "奈雪的茶",
        "一点点",
        "蜜雪冰城",
        "益禾堂",
        "大润发",
        "永辉超市",
        "华润万家",
        "山姆会员店",
        "盒马鲜生",
        "美团买菜",
        "京东到家",
        "朴朴超市",
        "嘀嗒出行",
        "高德打车",
        "T3出行",
        "曹操出行",
        "国家电网",
        "中国石化",
    )

    # 老商家 7 个 × ~70 笔 = 490 笔(高频)
    # 已画像商家 = 7 老 + 23 中频 = 30 个,共 ~835 笔
    # 长尾商家 70 个 × 2 笔 = 140 笔(冷启动)
    # 总:835 + 140 = 975 笔 + 25 笔 ¥999 异常 = 1000 笔

    for i in range(n):
        # 商家选择:长尾分布
        roll = rng.random()
        if roll < 0.49:  # 49% 老商家 (高频)
            counterparty = rng.choice(OLD_MERCHANTS)
        elif roll < 0.835:  # 34.5% 中频商家
            counterparty = rng.choice(mid_freq_merchants)
        else:  # 16.5% 长尾商家 (冷启动)
            counterparty = rng.choice(long_tail_merchants)

        # 金额:10% 概率为收入(3500-8000),其余为支出(8-200)
        if rng.random() < 0.10:
            amount = Decimal(rng.choice([3500.00, 4500.00, 5000.00, 6500.00, 8000.00]))
            source = rng.choice(["wechat", "alipay"])
        else:
            # 支出金额(根据商家类型调整)
            if "星巴克" in counterparty or "瑞幸" in counterparty or "喜茶" in counterparty:
                amount = Decimal(rng.choice([12.00, 25.00, 28.00, 35.00, 38.50, 42.00, 55.00]))
            elif "沃尔玛" in counterparty or "山姆" in counterparty or "大润发" in counterparty:
                amount = Decimal(rng.choice([45.00, 88.00, 128.00, 188.00, 248.00]))
            elif "麦当劳" in counterparty or "肯德基" in counterparty:
                amount = Decimal(rng.choice([15.50, 32.00, 42.00, 55.00, 68.00]))
            elif "美团" in counterparty or "饿了么" in counterparty or "外卖" in counterparty:
                amount = Decimal(rng.choice([12.00, 18.00, 25.00, 32.00, 45.00]))
            elif "打车" in counterparty or "滴滴" in counterparty:
                amount = Decimal(rng.choice([18.00, 28.00, 38.00, 55.00, 88.00]))
            else:
                amount = Decimal(rng.choice([8.00, 15.00, 25.00, 35.00, 50.00, 88.00, 128.00]))
            source = rng.choice(["wechat", "alipay"])

        # 25 笔 ¥999 大额异常(散布,模拟 amount_3sigma)
        if i < 25:
            amount = Decimal("999.00")

        # 时间随机均匀分布
        random_seconds = rng.randint(0, total_seconds)
        tx_dt = start_dt + timedelta(seconds=random_seconds)
        tx_date = tx_dt.date()
        imported_at_ms = int(tx_dt.timestamp() * 1000)

        ext_id = f"gen-{source}-{i:04d}"

        txs.append(
            Transaction(
                source=source,
                external_transaction_id=ext_id,
                transaction_date=tx_date,
                amount=amount,
                counterparty=counterparty,
                category=None,  # 不预设分类,沿 D8.5 spike 范本
                normalized_fingerprint=_make_fp(f"{tx_date.isoformat()}-{ext_id}"),
                status="categorized",
                imported_at_ms=imported_at_ms,
                raw_row_json="{}",
            )
        )

    return txs


def run_spike(seed: int = 42) -> int:
    """跑 D8 1000 笔 spike 主流程.

    Args:
        seed: 随机种子(默认 42,可复现)

    Returns:
        退出码(0/1/2/3)
    """
    rng = random.Random(seed)

    # 1. 生成 1000 笔
    txs = _generate_transactions(rng, n=1000)
    if not txs:
        print("BUSINESS FAIL: 生成 0 笔", file=sys.stderr)
        return EXIT_BUSINESS_FAIL

    # 2. 临时 SQLite DB + create_all
    db_path = Path("/tmp/spike_d8_1000.db")
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    tx_store = TransactionStore(sf)
    profile_store = MerchantProfileStore(sf, transaction_store=tx_store)
    detector = RuleBasedAnomalyDetector(
        transaction_store=tx_store,
        merchant_profile_store=profile_store,
    )

    # 3. 入库 1000 笔(按 imported_at_ms 升序,模拟真实时序)
    txs_sorted = sorted(txs, key=lambda t: t.imported_at_ms)
    with sf() as session:
        for tx in txs_sorted:
            session.add(tx)
        session.commit()

    # 4. 跑异常检测(逐笔 + 统计 6 类触发率 + 平均延迟)
    kind_counts: dict[str, int] = {
        "amount_3sigma": 0,
        "frequency_5tx_per_hour": 0,
        "duplicate_charge": 0,
        "new_merchant": 0,
        "amount_drift": 0,
        "category_drift": 0,
    }
    total_anomalies = 0
    true_anomalies = 0  # is_signal=False
    signals = 0  # is_signal=True
    total_latency_ms: float = 0.0
    tx_count_with_results = 0

    with sf() as session:
        for tx_id in [tx.id for tx in txs_sorted]:
            tx_row = session.get(Transaction, tx_id)
            if tx_row is None:
                continue
            start = time.perf_counter()
            results = detector.detect_all(tx_row)
            latency_ms: float = (time.perf_counter() - start) * 1000
            total_latency_ms += latency_ms
            tx_count_with_results += 1
            if results:
                total_anomalies += 1
                for r in results:
                    kind_counts[r.kind] = kind_counts.get(r.kind, 0) + 1
                    if r.is_signal:
                        signals += 1
                    else:
                        true_anomalies += 1

    # 5. 输出统计
    avg_latency_ms: float = (
        total_latency_ms / tx_count_with_results if tx_count_with_results else 0.0
    )
    kinds_summary = ",".join(f"{k}={v}" for k, v in kind_counts.items() if v > 0)
    if not kinds_summary:
        kinds_summary = "(none)"

    # 单行输出(沿 D5.6.5 + D8.4 spike 范本)
    # + true_anomalies / signals 拆分(沿 D8.5.2 is_signal 字段)
    print(
        f"d8 1000-faker spike: loaded={len(txs_sorted)} "
        f"detected={total_anomalies} "
        f"true_anomalies={true_anomalies} "
        f"signals={signals} "
        f"avg_latency_ms={avg_latency_ms:.2f} "
        f"kinds={kinds_summary}"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.2 D8 W3 验证 — 1000 笔 spike")
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子(默认 42,可复现)",
    )
    args = parser.parse_args(argv)

    try:
        return run_spike(seed=args.seed)
    except Exception as e:  # noqa: BLE001
        print(f"TECH FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
