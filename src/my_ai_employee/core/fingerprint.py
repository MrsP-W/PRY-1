"""D6.2 — normalized_fingerprint 指纹算法(纯函数层).

承接 docs/v0.1-launch-plan.md §D6 3 层去重模型 + §D6.2 详细 plan:

    - `normalize_fingerprint(date, amount, counterparty) -> str`
      SHA-256 截前 32 chars(16 字节 hex),date/amount/counterparty 归一化
    - `_canonical_payload(...)` 私有 helper,集中归一化逻辑
    - D7 兼容:无 source 维度,跨源共用同一指纹算法

设计参考(plan §4 8 范本):
    - compute_fingerprint 范本: events/contract.py:179-220
    - _envelope_to_dict 解析层独立: connectors/imap.py:211-242

3 步归一化(v0.1-launch-plan.md:255-270):
    1. date → ISO 8601 YYYY-MM-DD(取日期不取时间,跨日不命中)
    2. amount → abs(quantize 2 位小数 ROUND_HALF_UP)
    3. counterparty → strip + lower + 去模糊符"*" + 去所有空白

拼接: f"{date_norm}|{amount_norm}|{counterparty_norm}" → SHA-256 截 32 chars

**进程级确定性**: hashlib.sha256 是**标准库确定性哈希**,
    不会受 PYTHONHASHSEED 随机盐影响(教训 #42 的 hash() 陷阱不适用)。
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

# 32 chars = 128 bit(沿 v0.1-launch-plan.md:255 锁定的 16 字节 hex)
_FINGERPRINT_LENGTH = 32

# 金额归一化 2 位小数(沿 D6.1 wechat_csv._AMOUNT_QUANT 范本)
_AMOUNT_QUANT = Decimal("0.01")

# 商家名模糊符与空白
_FUZZY_PATTERN = re.compile(r"\*+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_date_value(value: date | str) -> str:
    """日期归一化 → ISO 8601 YYYY-MM-DD.

    支持入参:
        - date 对象:直接 .isoformat()
        - str "2026-06-14": 取前 10 字符
        - str "2026-06-14 12:30:00": 兼容完整 datetime
        - str "2026-06-14T12:30": 兼容 ISO T 分隔

    异常:
        - TypeError: 非 date/str
        - ValueError: 字符串无法解析为日期
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError(f"日期必填且必须非空字符串,实际 value={value!r}")
        # 兼容 "2026-06-14" / "2026-06-14 12:30:00" / "2026-06-14T12:30"
        date_part = s.split(" ")[0].split("T")[0]
        # 严判 ISO 格式 YYYY-MM-DD
        try:
            return datetime.strptime(date_part, "%Y-%m-%d").date().isoformat()
        except ValueError as e:
            raise ValueError(
                f"日期无法解析为 ISO YYYY-MM-DD: value={value!r}, date_part={date_part!r}"
            ) from e
    raise TypeError(f"date 必须是 date / str,实际 type={type(value).__name__}, value={value!r}")


def _normalize_amount_value(value: Decimal | int | float | str) -> str:
    """金额归一化 → abs + 2 位小数(13.14 == 13.140),返回 2 位小数字符串.

    沿 v0.1-launch-plan.md:262 锁定的 `abs(round(amount, 2))` 思路,
    用 Decimal 防 float 精度漂移(D3.2 8 雷区 + D6.1 范本)。

    返回字符串(非 Decimal)便于 SHA-256 拼接稳定。
    """
    if isinstance(value, bool):
        # 防 bool 是 int 子类陷阱(沿工厂层严判范本)
        raise TypeError(f"amount 不接受 bool,实际 {value!r}")
    if not isinstance(value, (Decimal, int, float, str)):
        raise TypeError(
            f"amount 必须是 Decimal / int / float / str,实际 type={type(value).__name__}, value={value!r}"
        )
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"amount 必填且必须非空字符串,实际 value={value!r}")
    # 严判走 str 入口(防 float 精度漂移: 0.1+0.2 != 0.3)
    amt = Decimal(str(value)).quantize(_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
    return f"{abs(amt):.2f}"


def _normalize_counterparty_value(value: str) -> str:
    r"""商家名归一化 → strip + lower + 去模糊符 \* + 去所有空白.

    沿 v0.1-launch-plan.md:266-268:
        re.sub(r"\*+", "", x).strip().lower() + re.sub(r"\s+", "", x)
    """
    if not isinstance(value, str):
        raise TypeError(
            f"counterparty 必须是 str,实际 type={type(value).__name__}, value={value!r}"
        )
    if not value.strip():
        raise ValueError(f"counterparty 必填且必须非空字符串,实际 value={value!r}")
    # 1. 去模糊符
    s = _FUZZY_PATTERN.sub("", value)
    # 2. strip + lower
    s = s.strip().lower()
    # 3. 去所有空白
    s = _WHITESPACE_PATTERN.sub("", s)
    if not s:
        raise ValueError(f"counterparty 归一化后为空(全模糊符/空白): value={value!r}")
    return s


def _canonical_payload(
    date_norm: str,
    amount_norm: str,
    counterparty_norm: str,
) -> str:
    """拼接 3 步归一化结果为稳定 canonical 字符串(沿 events/contract.py:219 范本).

    用 "|" 分隔(沿 v0.1-launch-plan.md:269),不参与 SHA-256 复杂
    (单一分隔符足够防 "2026-06-1" + "4" + "13.14" 拼接混淆,
    date / amount / counterparty 各自的归一化产物已固定长度格式)
    """
    return f"{date_norm}|{amount_norm}|{counterparty_norm}"


def normalize_fingerprint(
    date: date | str,
    amount: Decimal | int | float | str,
    counterparty: str,
) -> str:
    """规范化 3 字段并派生 SHA-256 fingerprint(32 chars hex).

    沿 v0.1-launch-plan.md:255-270 算法(无修改):
        1. date 归一化: YYYY-MM-DD
        2. amount 归一化: abs + 2 位小数(13.14 == 13.140)
        3. counterparty 归一化: strip + lower + 去模糊符 + 去空白
        4. 拼接 + SHA-256 截 32 chars

    Args:
        date: 交易日期(date 对象 / ISO 字符串 / 完整 datetime 字符串)
        amount: 交易金额(Decimal 优先,int/float/str 兼容)
        counterparty: 交易对方(支持模糊符"*" / 空白 / 大小写不敏感)

    Returns:
        SHA-256 hex 前 32 chars(16 字节,跨源统一指纹键)

    Raises:
        TypeError: 入参类型非法
        ValueError: 入参格式非法(空字符串 / 无法解析)

    Examples:
        >>> normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
        # 假设值 1: 同日同金额同商家
        >>> normalize_fingerprint("2026-06-14 12:30", Decimal("13.140"), "星巴克*")
        # 假设值 2: 时间不同 + 末尾 0 + 模糊符 — 应与 1 相同
        >>> normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克") == \\
        ... normalize_fingerprint("2026-06-14 12:30", Decimal("13.140"), "星巴克*")
        True
    """
    date_norm = _normalize_date_value(date)
    amount_norm = _normalize_amount_value(amount)
    counterparty_norm = _normalize_counterparty_value(counterparty)
    canonical = _canonical_payload(date_norm, amount_norm, counterparty_norm)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


__all__ = [
    "normalize_fingerprint",
]
