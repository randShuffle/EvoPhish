"""查看分析结果：从 MongoDB 按条件捞出判定为钓鱼的记录并统计。

用法：
    python view_results.py --exp_name baseline_phishintention
    python view_results.py --exp_name baseline_phishintention --start 2026-08-06 --end 2026-09-07 --min-conf 0.85
"""

import argparse
from datetime import datetime
from collections import defaultdict, Counter

import tldextract
from pymongo import MongoClient

from common import EXP_NAMES, MONGO_URI, MONGO_DB_NAME


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exp_name', required=True, choices=EXP_NAMES, help='集合名称（实验名）')
    parser.add_argument('--start', default='2026-08-06', help='开始日期 YYYY-MM-DD（含）')
    parser.add_argument('--end', default='2026-09-07', help='结束日期 YYYY-MM-DD（不含）')
    parser.add_argument('--min-conf', type=float, default=0.85, help='siamese_conf 下限')
    parser.add_argument('--exclude-brand', nargs='*', default=[""], help='要排除的 pred_target')
    return parser.parse_args()


def main():
    args = parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)

    # 建立连接
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db[args.exp_name]

    query = {
        "pred_target": {"$nin": args.exclude_brand},
        "phish_category": {"$in": [2]},
        "siamese_conf": {"$gte": args.min_conf},
        "$or": [
            {
                "timestamp": {
                    "$gte": start,
                    "$lt": end,
                }
            },
        ]
    }

    date2brand2num = {}
    results = collection.find(query)

    # phish_category 含义：
    # 0：no logos detected
    # 1：match but benign(logo domain consistent)
    # 2：match and phish(logo domain inconsistent)
    # 3：logos detected but no match
    # 4：non-CRP / dynamic analysis cannot find CRP
    domain_counter = defaultdict(Counter)

    l = []
    dif_brand_set = set()

    for doc in results:
        formatted = {
            "pred_target": str(doc.get("pred_target", "")),
            "phish_category": doc.get("phish_category"),
            "url": doc.get("url", ""),
            "siamese_conf": float(doc.get("siamese_conf", 0.0)) if doc.get("siamese_conf") else 0.0,
            "ori_domain": str(doc.get("ori_domain", "")),
            "is_typo": doc.get("is_typo", ""),
        }

        pred_target = formatted["pred_target"]
        if pred_target == "百度" and formatted["ori_domain"].endswith(".cfd"):
            continue

        date = doc["timestamp"].strftime("%m-%d")

        if date not in date2brand2num:
            date2brand2num[date] = {}

        if pred_target not in date2brand2num[date]:
            date2brand2num[date][pred_target] = 0
        date2brand2num[date][pred_target] += 1

        l.append(formatted["ori_domain"])
        url = formatted["url"]
        ext = tldextract.extract(url)
        root_domain = f"{ext.domain}.{ext.suffix}"  # 如 'apple.com'
        domain_counter[pred_target][root_domain] += 1
        dif_brand_set.add(pred_target)

        print(formatted)

    print(f"\n===== 汇总：{args.exp_name} =====")
    print(f"总条数: {len(l)}，涉及品牌数: {len(dif_brand_set)}")
    print("\n按日期 x 品牌统计:")
    for date in sorted(date2brand2num):
        print(f"  {date}: {dict(sorted(date2brand2num[date].items(), key=lambda x: -x[1]))}")
    print("\n各品牌 top 域名:")
    for brand, counter in sorted(domain_counter.items(), key=lambda x: -sum(x[1].values())):
        print(f"  {brand} (共 {sum(counter.values())}): {counter.most_common(5)}")

    client.close()


if __name__ == '__main__':
    main()
