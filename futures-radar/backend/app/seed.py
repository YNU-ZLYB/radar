"""初始化数据：品种、因子、品种-因子权重、数据源、示例资讯。"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import Analysis, Factor, RawDoc, Score, Source, Variety, VarietyFactor
from .services.scoring import compute_score

FACTORS = [
    ("供给", "供给", "产量、开工、检修、进口等供应端变化", "#2563eb"),
    ("需求", "需求", "下游开工、消费、订单、出口需求", "#059669"),
    ("库存", "库存", "港口/厂库/社会库存与仓单", "#d97706"),
    ("成本", "成本", "原油、煤炭、天然气、电力等成本项", "#7c3aed"),
    ("政策", "政策", "配额、关税、收储抛储、环保与产业政策", "#dc2626"),
    ("天气", "天气", "产区天气与灾害对产量/运输的影响", "#0891b2"),
    ("宏观", "宏观", "利率、汇率、通胀与风险偏好", "#475569"),
    ("资金/结构", "资金", "持仓、基差、跨期与资金流向", "#db2777"),
]

ACTIVE_VARIETIES = [
    {
        "code": "SR", "name": "白糖", "sector": "软商品/农产品", "sort_order": 1,
        "aliases": ["白糖", "郑糖", "食糖"],
        "keywords": ["白糖", "食糖", "原糖", "甘蔗", "甜菜", "糖厂", "广西糖", "云南糖", "内蒙糖",
                     "配额", "抛储", "收储", "淀粉糖", "含糖", "巴西糖", "印度糖", "泰国糖"],
        "description": "郑商所白糖期货，核心看广西/云南/内蒙产量、巴西印度泰国出口、进口政策与消费。",
        "factors": {"天气": 0.9, "供给": 0.9, "成本": 0.7, "政策": 0.7, "需求": 0.6, "库存": 0.5, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["广西", "云南", "开榨", "收榨", "甘蔗", "甜菜", "糖厂", "原糖", "巴西", "印度", "泰国"],
            "需求": ["含糖", "饮料", "食品", "消费", "淀粉糖"],
            "库存": ["仓单", "食糖库存"],
            "成本": ["原糖价格", "运费"],
            "政策": ["配额", "关税", "抛储", "收储", "打击走私"],
        },
    },
    {
        "code": "CF", "name": "棉花", "sector": "软商品/农产品", "sort_order": 2,
        "aliases": ["棉花", "郑棉", "皮棉"],
        "keywords": ["棉花", "籽棉", "皮棉", "新疆棉", "植棉", "棉花种植", "USDA", "滑准税", "配额",
                     "纺企", "棉纱", "服装出口", "轮换", "仓单", "轧花厂"],
        "description": "郑商所棉花期货，核心看新疆产量与收购价、USDA 报告、进口配额、纺织需求。",
        "factors": {"供给": 0.9, "需求": 0.8, "政策": 0.8, "天气": 0.7, "库存": 0.5, "成本": 0.4, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["新疆", "籽棉", "皮棉", "植棉面积", "轧花厂", "USDA"],
            "需求": ["纺企", "棉纱", "服装出口", "开机率", "订单"],
            "库存": ["仓单", "棉花库存"],
            "政策": ["滑准税", "配额", "轮换", "收储"],
        },
    },
    {
        "code": "MA", "name": "甲醇", "sector": "能源化工", "sort_order": 3,
        "aliases": ["甲醇", "郑醇", "MTO"],
        "keywords": ["甲醇", "MTO", "煤制甲醇", "天然气制甲醇", "伊朗", "甲醇进口", "港口库存",
                     "烯烃", "甲醛", "二甲醚", "醋酸", "限气"],
        "description": "郑商所甲醇期货，核心看煤炭/天然气成本、伊朗进口、MTO 开工、港口库存。",
        "factors": {"供给": 0.9, "成本": 0.85, "库存": 0.8, "需求": 0.7, "政策": 0.5, "天气": 0.5, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["装置", "伊朗", "进口", "开工", "检修", "限气", "天然气"],
            "需求": ["MTO", "烯烃", "甲醛", "二甲醚", "醋酸"],
            "库存": ["港口库存", "甲醇库存"],
            "成本": ["煤炭", "煤价", "天然气"],
        },
    },
    {
        "code": "SA", "name": "纯碱", "sector": "能源化工", "sort_order": 4,
        "aliases": ["纯碱", "苏打"],
        "keywords": ["纯碱", "天然碱", "联碱", "氨碱", "光伏玻璃", "浮法玻璃", "重碱", "轻碱",
                     "纯碱库存", "碱厂"],
        "description": "郑商所纯碱期货，核心看开工与检修、光伏/浮法玻璃需求、库存与环保限产。",
        "factors": {"供给": 0.9, "库存": 0.85, "需求": 0.8, "成本": 0.6, "政策": 0.5, "天气": 0.2, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["碱厂", "开工率", "天然碱", "联碱", "氨碱", "检修", "装置"],
            "需求": ["光伏玻璃", "浮法玻璃", "重碱", "轻碱", "日熔量"],
            "库存": ["纯碱库存", "碱厂库存", "社会库存"],
            "政策": ["环保", "限产"],
        },
    },
    {
        "code": "FG", "name": "玻璃", "sector": "能源化工", "sort_order": 5,
        "aliases": ["玻璃", "浮法玻璃", "浮法"],
        "keywords": ["浮法玻璃", "玻璃", "冷修", "复产", "地产竣工", "深加工", "保交楼",
                     "玻璃库存", "窑炉", "产销率", "日熔量"],
        "description": "郑商所玻璃期货，核心看地产竣工、深加工订单、冷修复产、库存与成本。",
        "factors": {"需求": 0.9, "供给": 0.85, "库存": 0.8, "成本": 0.7, "政策": 0.6, "天气": 0.2, "宏观": 0.35},
        "factor_keywords": {
            "供给": ["冷修", "复产", "窑炉", "日熔量", "点火"],
            "需求": ["地产竣工", "深加工", "产销率", "保交楼", "订单"],
            "库存": ["玻璃库存", "沙河库存"],
            "成本": ["纯碱", "燃料", "天然气"],
            "政策": ["保交楼", "地产政策"],
        },
    },
]

PLACEHOLDER_VARIETIES = []  # 已升级为 FULL_VARIETIES

FULL_VARIETIES = [
    {
        "code": "CY", "name": "棉纱", "sector": "软商品/农产品", "sort_order": 6,
        "aliases": ["棉纱", "进口纱", "纯棉纱"],
        "keywords": ["棉纱", "纯棉纱", "精梳", "普梳", "进口纱", "纺企", "纱线"],
        "description": "郑商所棉纱期货，核心看纺企开机、纯棉纱产销、进口纱补充。",
        "factors": {"供给": 0.8, "需求": 0.8, "库存": 0.6, "政策": 0.5, "天气": 0.4, "成本": 0.5, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["进口纱", "精梳", "普梳", "纺企"],
            "需求": ["棉纱", "纱线", "服装"],
            "库存": ["棉纱库存", "厂库"],
            "成本": ["皮棉", "棉价"],
        },
    },
    {
        "code": "AP", "name": "苹果", "sector": "软商品/农产品", "sort_order": 7,
        "aliases": ["苹果", "苹果期货"],
        "keywords": ["苹果", "山东苹果", "陕西苹果", "霜冻", "冷库", "套袋"],
        "description": "郑商所苹果期货，核心看陕西/山东产量、霜冻灾害、冷库入库与出库节奏。",
        "factors": {"天气": 0.9, "供给": 0.8, "库存": 0.7, "需求": 0.4, "政策": 0.4, "成本": 0.2, "宏观": 0.2},
        "factor_keywords": {
            "供给": ["套袋", "采收", "山东苹果", "陕西苹果"],
            "需求": ["消费", "出口"],
            "库存": ["冷库", "入库", "出库"],
            "天气": ["霜冻", "倒春寒"],
        },
    },
    {
        "code": "CJ", "name": "红枣", "sector": "软商品/农产品", "sort_order": 8,
        "aliases": ["红枣", "郑枣", "新疆枣"],
        "keywords": ["红枣", "新疆枣", "阿克苏", "沧州", "红枣期货"],
        "description": "郑商所红枣期货，核心看新疆产量、沧州分级加工、出口需求。",
        "factors": {"供给": 0.8, "库存": 0.7, "天气": 0.7, "需求": 0.5, "政策": 0.3, "成本": 0.3, "宏观": 0.2},
        "factor_keywords": {
            "供给": ["新疆枣", "阿克苏", "沧州", "采收"],
            "需求": ["消费", "出口"],
            "库存": ["冷库", "囤货"],
            "天气": ["霜冻", "坐果"],
        },
    },
    {
        "code": "PK", "name": "花生", "sector": "软商品/农产品", "sort_order": 9,
        "aliases": ["花生", "花生油"],
        "keywords": ["花生", "鲁花", "油厂", "收购", "进口花生", "压榨"],
        "description": "郑商所花生期货，核心看鲁冀鲁豫产量、油厂收购价、进口替代。",
        "factors": {"供给": 0.9, "成本": 0.7, "需求": 0.7, "库存": 0.5, "政策": 0.5, "天气": 0.6, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["鲁花", "河南", "山东", "辽宁", "进口花生"],
            "需求": ["油厂", "压榨"],
            "库存": ["油厂库存"],
            "成本": ["收购价"],
        },
    },
    {
        "code": "OI", "name": "菜籽油", "sector": "软商品/农产品", "sort_order": 10,
        "aliases": ["菜油", "菜籽油"],
        "keywords": ["菜籽油", "菜油", "进口菜油", "加拿大菜籽", "沿海油厂"],
        "description": "郑商所菜籽油期货，核心看进口菜油到港、沿海油厂压榨、餐饮消费。",
        "factors": {"供给": 0.9, "需求": 0.7, "成本": 0.7, "库存": 0.6, "政策": 0.5, "天气": 0.4, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["进口菜油", "加拿大菜籽", "菜籽油期货"],
            "需求": ["餐饮", "消费"],
            "库存": ["沿海油厂库存"],
            "成本": ["菜籽", "原料"],
        },
    },
    {
        "code": "RM", "name": "菜籽粕", "sector": "软商品/农产品", "sort_order": 11,
        "aliases": ["菜粕", "菜籽粕"],
        "keywords": ["菜籽粕", "菜粕", "饲料", "水产养殖"],
        "description": "郑商所菜籽粕期货，核心看油厂压榨量、饲料企业需求、水产养殖开工。",
        "factors": {"供给": 0.85, "需求": 0.85, "库存": 0.6, "成本": 0.5, "政策": 0.4, "天气": 0.5, "宏观": 0.2},
        "factor_keywords": {
            "供给": ["压榨", "菜粕"],
            "需求": ["饲料", "水产养殖"],
            "库存": ["沿海菜粕库存"],
        },
    },
    {
        "code": "RS", "name": "油菜籽", "sector": "软商品/农产品", "sort_order": 12,
        "aliases": ["油菜籽", "菜籽"],
        "keywords": ["油菜籽", "菜籽", "湖北菜籽", "进口菜籽", "中加贸易"],
        "description": "郑商所油菜籽期货，核心看国内产量、中加贸易与进口菜籽到港。",
        "factors": {"供给": 0.9, "成本": 0.7, "库存": 0.6, "需求": 0.6, "政策": 0.6, "天气": 0.5, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["湖北菜籽", "进口菜籽", "加拿大"],
            "需求": ["油厂", "压榨"],
            "库存": ["菜籽库存"],
            "政策": ["中加", "贸易"],
        },
    },
    {
        "code": "TA", "name": "PTA", "sector": "能源化工", "sort_order": 13,
        "aliases": ["PTA"],
        "keywords": ["PTA", "PX", "聚酯", "瓶片", "PTA装置", "逸盛"],
        "description": "郑商所 PTA 期货，核心看 PX 成本、PTA 装置检修与开工、聚酯需求。",
        "factors": {"供给": 0.9, "成本": 0.85, "需求": 0.7, "库存": 0.6, "政策": 0.4, "天气": 0.3, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["PTA装置", "逸盛", "检修", "开工"],
            "需求": ["聚酯", "瓶片"],
            "库存": ["PTA库存"],
            "成本": ["PX", "石脑油", "原油"],
        },
    },
    {
        "code": "UR", "name": "尿素", "sector": "能源化工", "sort_order": 14,
        "aliases": ["尿素"],
        "keywords": ["尿素", "复合肥", "印度招标", "春季用肥", "天然气", "煤头"],
        "description": "郑商所尿素期货，核心看印度招标、煤/天然气成本、春季用肥旺季。",
        "factors": {"供给": 0.85, "成本": 0.85, "需求": 0.6, "政策": 0.7, "库存": 0.5, "天气": 0.2, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["装置", "开工", "检修"],
            "需求": ["印度招标", "复合肥", "用肥"],
            "库存": ["尿素库存"],
            "成本": ["煤炭", "天然气"],
            "政策": ["出口政策"],
        },
    },
    {
        "code": "PF", "name": "短纤", "sector": "能源化工", "sort_order": 15,
        "aliases": ["短纤", "涤纶"],
        "keywords": ["短纤", "涤纶短纤", "聚酯短纤", "下游纺纱"],
        "description": "郑商所短纤期货，核心看 PTA 成本、短纤装置开工、下游纺纱需求。",
        "factors": {"供给": 0.8, "成本": 0.9, "需求": 0.7, "库存": 0.5, "政策": 0.3, "天气": 0.2, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["短纤装置", "开工"],
            "需求": ["纺纱", "下游"],
            "库存": ["短纤库存"],
            "成本": ["PTA", "聚酯"],
        },
    },
    {
        "code": "PR", "name": "瓶片", "sector": "能源化工", "sort_order": 16,
        "aliases": ["瓶片", "聚酯瓶片"],
        "keywords": ["瓶片", "PET瓶片", "饮料包装", "矿泉水瓶"],
        "description": "郑商所瓶片期货，核心看 PTA 成本、瓶片装置开工、饮料包装旺季。",
        "factors": {"供给": 0.8, "成本": 0.9, "需求": 0.6, "库存": 0.5, "政策": 0.4, "天气": 0.3, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["瓶片装置", "开工"],
            "需求": ["饮料包装", "矿泉水瓶"],
            "库存": ["瓶片库存"],
            "成本": ["PTA"],
        },
    },
    {
        "code": "SH", "name": "烧碱", "sector": "能源化工", "sort_order": 17,
        "aliases": ["烧碱", "氧化铝"],
        "keywords": ["烧碱", "液碱", "片碱", "氧化铝", "电解铝", "烧碱装置"],
        "description": "郑商所烧碱期货，核心看氧化铝需求、烧碱装置检修/开工、铝行业景气。",
        "factors": {"供给": 0.9, "需求": 0.8, "成本": 0.7, "库存": 0.6, "政策": 0.5, "天气": 0.2, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["烧碱装置", "检修", "开工"],
            "需求": ["氧化铝", "电解铝"],
            "库存": ["烧碱库存"],
            "成本": ["原盐", "电力"],
        },
    },
    {
        "code": "PX", "name": "对二甲苯", "sector": "能源化工", "sort_order": 18,
        "aliases": ["PX"],
        "keywords": ["PX", "对二甲苯", "石脑油", "PX装置", "PTA原料"],
        "description": "郑商所 PX 期货，核心看 PX 装置开工、石脑油成本、PTA 需求传导。",
        "factors": {"供给": 0.9, "成本": 0.9, "需求": 0.7, "库存": 0.5, "政策": 0.4, "天气": 0.3, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["PX装置", "检修", "开工"],
            "需求": ["PTA"],
            "库存": ["PX库存"],
            "成本": ["石脑油", "原油"],
        },
    },
    {
        "code": "SF", "name": "硅铁", "sector": "铁合金", "sort_order": 19,
        "aliases": ["硅铁"],
        "keywords": ["硅铁", "兰炭", "电价", "宁夏", "青海", "钢铁"],
        "description": "郑商所硅铁期货，核心看宁夏/青海产量、兰炭/电力成本、钢铁需求。",
        "factors": {"供给": 0.9, "成本": 0.85, "需求": 0.7, "库存": 0.5, "政策": 0.5, "天气": 0.3, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["宁夏", "青海", "装置"],
            "需求": ["钢铁", "炼钢"],
            "库存": ["硅铁库存"],
            "成本": ["兰炭", "电价"],
            "政策": ["环保", "限产"],
        },
    },
    {
        "code": "SM", "name": "锰硅", "sector": "铁合金", "sort_order": 20,
        "aliases": ["锰硅"],
        "keywords": ["锰硅", "锰矿", "南非锰矿", "电力", "钢铁"],
        "description": "郑商所锰硅期货，核心看南非锰矿进口、电力成本、钢铁需求。",
        "factors": {"供给": 0.9, "成本": 0.85, "需求": 0.7, "库存": 0.5, "政策": 0.5, "天气": 0.3, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["南非锰矿", "锰矿", "装置"],
            "需求": ["钢铁", "炼钢"],
            "库存": ["锰硅库存"],
            "成本": ["锰矿", "电力"],
        },
    },
    {
        "code": "ZC", "name": "动力煤", "sector": "能源", "sort_order": 21,
        "aliases": ["动力煤", "郑煤"],
        "keywords": ["动力煤", "秦皇岛", "电厂", "长协煤", "蒙煤", "晋煤"],
        "description": "郑商所动力煤期货，核心看秦皇岛港口库存、电厂日耗、长协政策、蒙煤进口。",
        "factors": {"供给": 0.9, "需求": 0.85, "库存": 0.85, "政策": 0.8, "成本": 0.5, "天气": 0.6, "宏观": 0.4},
        "factor_keywords": {
            "供给": ["晋煤", "蒙煤", "长协煤", "产量"],
            "需求": ["电厂", "日耗"],
            "库存": ["秦皇岛", "电厂库存"],
            "政策": ["长协", "限价"],
        },
    },
    {
        "code": "WH", "name": "小麦", "sector": "农产品", "sort_order": 22,
        "aliases": ["小麦"],
        "keywords": ["小麦", "冬小麦", "麦收", "面粉", "托市收购", "最低收购价"],
        "description": "郑商所小麦期货，核心看冬小麦产量、托市收购、面粉消费。",
        "factors": {"供给": 0.9, "需求": 0.7, "政策": 0.8, "天气": 0.7, "库存": 0.6, "成本": 0.3, "宏观": 0.3},
        "factor_keywords": {
            "供给": ["麦收", "冬小麦", "河南小麦"],
            "需求": ["面粉", "食品"],
            "库存": ["托市库存", "粮库"],
            "政策": ["托市收购", "最低收购价"],
            "天气": ["干旱", "冻害"],
        },
    },
    {
        "code": "PL", "name": "丙烯", "sector": "能源化工", "sort_order": 23,
        "aliases": ["丙烯", "丙烯期货"],
        "keywords": ["丙烯", "丙烷", "PDH", "聚丙烯", "PP", "裂解", "丙烷脱氢", "石脑油"],
        "description": "郑商所丙烯期货，核心看丙烷/石脑油成本、PDH 与蒸汽裂解装置开工、聚丙烯需求。",
        "factors": {"成本": 0.9, "供给": 0.85, "需求": 0.75, "宏观": 0.5, "库存": 0.6, "政策": 0.4, "天气": 0.2},
        "factor_keywords": {
            "供给": ["PDH", "丙烷脱氢", "裂解", "装置", "开工", "检修"],
            "需求": ["聚丙烯", "PP", "下游"],
            "库存": ["丙烯库存", "港口库存"],
            "成本": ["丙烷", "石脑油", "原油", "天然气"],
        },
    },
]

SOURCES = [
    {"code": "czce_announce", "name": "郑商所公告通知", "type": "official", "level": "A",
     "url": "https://www.czce.com.cn/", "weight": 1.0, "interval_sec": 120, "priority": 1},
    {"code": "jin10_flash", "name": "金十快讯", "type": "news", "level": "C",
     "url": "https://www.jin10.com/", "weight": 0.65, "interval_sec": 60, "priority": 2},
    {"code": "eastmoney_flash", "name": "东方财富快讯", "type": "news", "level": "C",
     "url": "https://finance.eastmoney.com/", "weight": 0.65, "interval_sec": 60, "priority": 3},
    {"code": "sina_7x24", "name": "新浪财经7×24", "type": "news", "level": "C",
     "url": "https://finance.sina.com.cn/", "weight": 0.6, "interval_sec": 120, "priority": 3},
    {"code": "sina_rss", "name": "新浪财经滚动", "type": "news", "level": "C",
     "url": "https://rss.sina.com.cn/roll/finance/hot_roll.xml", "weight": 0.6,
     "interval_sec": 900, "priority": 4},
    {"code": "sina_oil", "name": "新浪原油行情", "type": "market", "level": "F",
     "url": "https://finance.sina.com.cn", "weight": 1.0,
     "interval_sec": 60, "priority": 2},
    {"code": "fred_brent", "name": "FRED Brent 日线", "type": "market", "level": "F",
     "url": "https://fred.stlouisfed.org/", "weight": 1.0, "interval_sec": 21600, "priority": 6},
    {"code": "manual", "name": "手工录入", "type": "manual", "level": "E",
     "url": "", "weight": 0.8, "interval_sec": 0, "priority": 9},
]

SAMPLES = [
    {
        "title": "【示例】广西部分糖厂开榨推迟，短期供给偏紧",
        "content": "【示例】广西部分糖厂开榨时间较往年推迟 7-10 天，当前新糖上市量偏低，现货报价小幅上调。市场预计 11 月上中旬供给偏紧格局延续。",
        "varieties": ["SR"], "direction": "bullish", "strength": 3, "confidence": 0.72,
        "factor": "供给", "event_type": "减产", "horizon": "short",
        "summary": "广西开榨推迟，短期白糖供给偏紧，现货报价上调。",
        "evidence": "广西部分糖厂开榨时间较往年推迟 7-10 天，当前新糖上市量偏低",
        "reasoning": "开榨推迟压缩短期新糖供应，利多近月价格；中期仍需观察总产量。",
        "source_weight": 0.85, "hours_ago": 1,
    },
    {
        "title": "【示例】巴西中南部糖产量同比增加 8%",
        "content": "【示例】巴西甘蔗行业协会数据显示，中南部地区累计糖产量同比增加 8%，制糖比高于市场预期，原糖期货承压下挫。",
        "varieties": ["SR"], "direction": "bearish", "strength": 4, "confidence": 0.8,
        "factor": "供给", "event_type": "增产", "horizon": "medium",
        "summary": "巴西糖产量同比增 8%，全球供给宽松预期升温。",
        "evidence": "中南部地区累计糖产量同比增加 8%，制糖比高于市场预期",
        "reasoning": "主产国增产提升全球供应，利空原糖与郑糖远期。",
        "source_weight": 0.7, "hours_ago": 5,
    },
    {
        "title": "【示例】新疆籽棉收购价上调，轧花厂成本抬升",
        "content": "【示例】新疆北疆籽棉收购价较上周上调 0.15 元/公斤，轧花厂收购进度加快，皮棉成本抬升，部分贸易商挺价。",
        "varieties": ["CF"], "direction": "bullish", "strength": 2, "confidence": 0.65,
        "factor": "成本", "event_type": "其他", "horizon": "short",
        "summary": "籽棉收购价上调，棉花成本支撑增强。",
        "evidence": "籽棉收购价较上周上调 0.15 元/公斤",
        "reasoning": "收购成本上升抬升皮棉成本，对棉价形成支撑。",
        "source_weight": 0.7, "hours_ago": 3,
    },
    {
        "title": "【示例】伊朗两套甲醇装置计划停车检修 20 天",
        "content": "【示例】伊朗两套合计 380 万吨/年甲醇装置计划于下周停车检修，预计持续 20 天，市场担忧后期进口量下滑。",
        "varieties": ["MA"], "direction": "bullish", "strength": 4, "confidence": 0.86,
        "factor": "供给", "event_type": "装置检修", "horizon": "short",
        "summary": "伊朗装置停车检修，甲醇进口预期收缩。",
        "evidence": "伊朗两套合计 380 万吨/年甲醇装置计划于下周停车检修",
        "reasoning": "伊朗是中国甲醇主要进口来源，检修减少到港量，利多港口价格。",
        "source_weight": 0.85, "hours_ago": 2,
    },
    {
        "title": "【示例】华东甲醇港口库存连续三周累积",
        "content": "【示例】华东港口甲醇库存增至 92 万吨，连续三周累积，提货速度偏慢，贸易商出货压力增加。",
        "varieties": ["MA"], "direction": "bearish", "strength": 3, "confidence": 0.75,
        "factor": "库存", "event_type": "库存", "horizon": "medium",
        "summary": "华东港口库存连续累积，甲醇上方承压。",
        "evidence": "华东港口甲醇库存增至 92 万吨，连续三周累积",
        "reasoning": "库存累积反映需求偏弱与到港集中，压制现货价格。",
        "source_weight": 0.8, "hours_ago": 6,
    },
    {
        "title": "【示例】纯碱企业开工率回升至 88%，供应趋于宽松",
        "content": "【示例】隆众数据显示，本周纯碱行业开工率回升至 88%，环比提高 3 个百分点，部分检修装置恢复生产，供应趋于宽松。",
        "varieties": ["SA"], "direction": "bearish", "strength": 3, "confidence": 0.7,
        "factor": "供给", "event_type": "复产", "horizon": "short",
        "summary": "纯碱开工率回升，供应宽松压制盘面。",
        "evidence": "本周纯碱行业开工率回升至 88%，环比提高 3 个百分点",
        "reasoning": "检修装置恢复提高供应，短期利空纯碱。",
        "source_weight": 0.75, "hours_ago": 4,
    },
    {
        "title": "【示例】光伏玻璃日熔量下降，纯碱需求走弱",
        "content": "【示例】近期部分光伏玻璃产线冷修，行业日熔量环比下降约 1.2%，重碱刚需采购放缓，纯碱需求端支撑减弱。",
        "varieties": ["SA"], "direction": "bearish", "strength": 2, "confidence": 0.62,
        "factor": "需求", "event_type": "需求", "horizon": "medium",
        "summary": "光伏玻璃冷修，纯碱重碱需求走弱。",
        "evidence": "部分光伏玻璃产线冷修，行业日熔量环比下降约 1.2%",
        "reasoning": "光伏玻璃是重碱主要下游，日熔量下降削弱纯碱需求。",
        "source_weight": 0.7, "hours_ago": 8,
    },
    {
        "title": "【示例】沙河玻璃产销率提升，库存小幅去化",
        "content": "【示例】沙河地区玻璃产销率提升至 110%，厂家库存小幅去化，贸易商补库意愿增强，现货价格企稳。",
        "varieties": ["FG"], "direction": "bullish", "strength": 2, "confidence": 0.68,
        "factor": "库存", "event_type": "库存", "horizon": "short",
        "summary": "沙河产销率回升，玻璃库存去化，现货企稳。",
        "evidence": "沙河地区玻璃产销率提升至 110%，厂家库存小幅去化",
        "reasoning": "产销率回升显示下游补库，库存下降对价格有支撑。",
        "source_weight": 0.75, "hours_ago": 7,
    },
    {
        "title": "【示例】保交楼资金加快落地，竣工端预期改善",
        "content": "【示例】多地保交楼专项借款加快拨付，房企竣工节奏有望提速，市场对玻璃竣工端需求预期改善。",
        "varieties": ["FG"], "direction": "bullish", "strength": 3, "confidence": 0.66,
        "factor": "政策", "event_type": "政策", "horizon": "medium",
        "summary": "保交楼资金落地，玻璃竣工需求预期改善。",
        "evidence": "多地保交楼专项借款加快拨付，房企竣工节奏有望提速",
        "reasoning": "竣工端是浮法玻璃核心需求，政策推动改善中期需求预期。",
        "source_weight": 0.8, "hours_ago": 10,
    },
    {
        "title": "【示例】布伦特原油回落，甲醇成本支撑减弱",
        "content": "【示例】布伦特原油跌破 84 美元/桶，能化板块成本重心下移，甲醇期货跟随走弱，市场情绪偏谨慎。",
        "varieties": ["MA"], "direction": "bearish", "strength": 2, "confidence": 0.6,
        "factor": "成本", "event_type": "成本", "horizon": "short",
        "summary": "原油回落拖累能化成本，甲醇跟随走弱。",
        "evidence": "布伦特原油跌破 84 美元/桶，能化板块成本重心下移",
        "reasoning": "原油是能化成本锚，回落削弱甲醇成本支撑与市场情绪。",
        "source_weight": 0.7, "hours_ago": 9,
    },
]


def _hash(title: str, content: str) -> str:
    payload = re.sub(r"\s+", "", title) + "|" + re.sub(r"\s+", "", content)[:3000]
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        first = db.execute(select(Variety).limit(1)).scalars().first()

        factors = {}
        for name, category, desc, color in FACTORS:
            f = db.execute(select(Factor).where(Factor.name == name)).scalars().first()
            if not f:
                f = Factor(name=name, category=category, description=desc, color=color)
                db.add(f)
                db.flush()
            factors[name] = f

        if first is None:
            # 全新库：一次性写入所有品种
            for item in ACTIVE_VARIETIES + FULL_VARIETIES:
                _upsert_variety(db, factors, item)
            for item in SOURCES:
                s = db.execute(select(Source).where(Source.code == item["code"])).scalars().first()
                if not s:
                    db.add(Source(**item, enabled=True))
            _seed_samples(db)
            db.commit()
            print(f"[seed] 已初始化 {len(ACTIVE_VARIETIES) + len(FULL_VARIETIES)} 个品种、{len(SOURCES)} 个数据源")
        else:
            # 已有库：增量补齐新因子 / 升级 placeholder 品种
            upgraded = 0
            for item in ACTIVE_VARIETIES + FULL_VARIETIES:
                v = db.execute(select(Variety).where(Variety.code == item["code"])).scalars().first()
                if v is None:
                    _upsert_variety(db, factors, item)
                    upgraded += 1
                    continue
                # 已有品种：补字段 / 补因子（PLACEHOLDER → 完整）
                need_save = False
                if not v.is_active:
                    v.is_active = True; need_save = True
                if not v.aliases:
                    v.aliases = item["aliases"]; need_save = True
                if not v.keywords or len(v.keywords) < 3:
                    v.keywords = item["keywords"]; need_save = True
                if not v.description:
                    v.description = item["description"]; need_save = True
                if v.sort_order is None or v.sort_order < 1:
                    v.sort_order = item["sort_order"]; need_save = True
                # 补 VarietyFactor
                existing_factors = {vf.factor.name for vf in v.factors}
                for fname, weight in item["factors"].items():
                    if fname not in existing_factors:
                        db.add(VarietyFactor(
                            variety_id=v.id, factor_id=factors[fname].id, weight=weight,
                            keywords=item["factor_keywords"].get(fname, []),
                        ))
                        need_save = True
                if need_save:
                    upgraded += 1
            for item in SOURCES:
                s = db.execute(select(Source).where(Source.code == item["code"])).scalars().first()
                if not s:
                    db.add(Source(**item, enabled=True))
                    upgraded += 1
            if upgraded:
                db.commit()
                print(f"[seed] 增量升级 {upgraded} 项")
            else:
                print("[seed] 已是最新，跳过")


def _upsert_variety(db, factors, item):
    v = Variety(
        code=item["code"], name=item["name"], sector=item["sector"],
        is_active=True, aliases=item["aliases"], keywords=item["keywords"],
        description=item["description"], sort_order=item["sort_order"],
    )
    db.add(v)
    db.flush()
    for fname, weight in item["factors"].items():
        db.add(VarietyFactor(
            variety_id=v.id, factor_id=factors[fname].id, weight=weight,
            keywords=item["factor_keywords"].get(fname, []),
        ))


def _seed_samples(db):
    manual = db.execute(select(Source).where(Source.code == "manual")).scalars().first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for idx, sample in enumerate(SAMPLES):
        published = now - timedelta(hours=sample["hours_ago"], minutes=idx * 3)
        doc = RawDoc(
            source_id=manual.id,
            source_name="示例数据（手工录入）",
            source_weight=sample["source_weight"],
            url="",
            title=sample["title"],
            content=sample["content"],
            published_at=published,
            first_seen_at=published,
            content_hash=_hash(sample["title"], sample["content"]),
            matched_varieties=sample["varieties"],
            status="analyzed",
            is_manual=True,
        )
        db.add(doc)
        db.flush()
        analysis = Analysis(
            doc_id=doc.id,
            model="demo-seed",
            prompt_version="v1",
            status="analyzed",
            varieties=sample["varieties"],
            direction=sample["direction"],
            strength=sample["strength"],
            confidence=sample["confidence"],
            horizon=sample["horizon"],
            factor=sample["factor"],
            event_type=sample["event_type"],
            summary=sample["summary"],
            evidence=sample["evidence"],
            reasoning=sample["reasoning"],
            latency_ms=0,
            created_at=published,
            updated_at=published,
        )
        db.add(analysis)
        db.flush()
        for code in sample["varieties"]:
            s = compute_score(
                sample["direction"], sample["strength"], sample["confidence"],
                sample["source_weight"], published, sample["horizon"], novelty=1.0,
            )
            db.add(Score(
                analysis_id=analysis.id, doc_id=doc.id, variety_code=code,
                direction=sample["direction"], score=s, importance=abs(s),
                confidence=sample["confidence"], factor=sample["factor"],
            ))
