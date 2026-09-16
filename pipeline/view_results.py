"""View analysis results: pull records judged as phishing from MongoDB by filter conditions and summarize.

Usage:
    python view_results.py --exp_name baseline_phishintention
    python view_results.py --exp_name baseline_phishintention --start 2026-08-06 --end 2026-09-07
"""

import argparse
from datetime import datetime
from collections import defaultdict, Counter

import tldextract
from pymongo import MongoClient

from common import EXP_NAMES, MONGO_URI, MONGO_DB_NAME


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exp_name', default=EXP_NAMES[0], choices=EXP_NAMES, help='Collection name (experiment name)')
    parser.add_argument('--start', default='2026-09-15', help='Start date YYYY-MM-DD (inclusive)')
    parser.add_argument('--end', default='2026-09-30', help='End date YYYY-MM-DD (exclusive)')
    return parser.parse_args()


def main():
    args = parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)

    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db[args.exp_name]

    query = {
        "phish_category": {"$in": [2]},
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

    # phish_category meanings:
    # 0: no logos detected
    # 1: match but benign (logo domain consistent)
    # 2: match and phish (logo domain inconsistent)
    # 3: logos detected but no match
    # 4: non-CRP / dynamic analysis cannot find CRP
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
       
        date = doc["timestamp"].strftime("%m-%d")

        if date not in date2brand2num:
            date2brand2num[date] = {}

        if pred_target not in date2brand2num[date]:
            date2brand2num[date][pred_target] = 0
        date2brand2num[date][pred_target] += 1

        l.append(formatted["ori_domain"])
        url = formatted["url"]
        ext = tldextract.extract(url)
        root_domain = f"{ext.domain}.{ext.suffix}"  # e.g. 'apple.com'
        domain_counter[pred_target][root_domain] += 1
        dif_brand_set.add(pred_target)
        print(formatted)

    print(f"\n===== Summary: {args.exp_name} =====")
    print(f"Total records: {len(l)}, brands involved: {len(dif_brand_set)}")
    print("\nCounts by date x brand:")
    for date in sorted(date2brand2num):
        print(f"  {date}: {dict(sorted(date2brand2num[date].items(), key=lambda x: -x[1]))}")
    print("\nTop domains per brand:")
    for brand, counter in sorted(domain_counter.items(), key=lambda x: -sum(x[1].values())):
        print(f"  {brand} (total {sum(counter.values())}): {counter.most_common(5)}")

    client.close()


if __name__ == '__main__':
    main()
