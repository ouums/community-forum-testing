# -*- coding: utf-8 -*-
"""分析 JMeter JTL 结果文件：按采样器统计通过/失败/错误码"""
import sys, csv
from collections import Counter, defaultdict

jtl = sys.argv[1] if len(sys.argv) > 1 else 'results_verify.jtl'

total = 0
by_sampler = defaultdict(lambda: Counter())
error_codes = Counter()

with open(jtl, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=',')
    for row in reader:
        if not row.get('label'):
            continue
        total += 1
        label = row['label']
        success = row['success'] == 'true'
        if success:
            by_sampler[label]['通过'] += 1
        else:
            by_sampler[label]['失败'] += 1
            error_codes[(label, row.get('responseCode', '?'), row.get('responseMessage', '?')[:30])] += 1

print(f"总样本: {total}\n")
print(f"{'采样器':<28}{'通过':>6}{'失败':>6}")
for label, c in by_sampler.items():
    print(f"{label:<28}{c['通过']:>6}{c['失败']:>6}")

print("\n错误详情 (label | code | message):")
for (label, code, msg), n in error_codes.most_common():
    print(f"  {n:>3}x  {label} | {code} | {msg}")

# 通过样本的响应时间统计
times = defaultdict(list)
with open(jtl, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=',')
    for row in reader:
        if row.get('label') and row['success'] == 'true':
            times[row['label']].append(int(row['elapsed']))

print("\n通过样本响应时间(ms): avg / p90 / max")
for label, lst in times.items():
    if not lst:
        print(f"  {label:<28} 无通过样本")
        continue
    lst.sort()
    avg = sum(lst) // len(lst)
    p90 = lst[int(len(lst)*0.9)-1]
    print(f"  {label:<28} {avg:>5} / {p90:>5} / {max(lst):>5}  (n={len(lst)})")
