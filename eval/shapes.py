"""List case shapes (rules fired + scenario-specific document types) with sample case IDs to label.

python3 eval/shapes.py <institution> [samples per shape, default 2]
Labelling 1-2 cases per shape (3-4 for big ones) covers the whole development set.
"""

import sys
from collections import defaultdict

from _common import bundles, shape

inst = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
groups = defaultdict(list)
for b in bundles(inst):
    groups[shape(b)].append(b.case["case_id"])

for i, ((rules, docs), ids) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
    k = n + (2 if len(ids) >= 60 else 0)
    print(f"{i:>2}. {len(ids):>4} cases  {'+'.join(rules):<20} {', '.join(docs) or '(no scenario docs)'}")
    print(f"      label: {' '.join(ids[:k])}")
