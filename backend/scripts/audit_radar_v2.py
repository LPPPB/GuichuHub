"""Read-only offline distribution audit. Input contains explicit observation provenance."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.radar_v2 import build_baseline, build_video_radar
from analytics.backtest import spearman


def audit_contexts(contexts, now):
    baseline = build_baseline(contexts, now, now+7*86400)
    radars = [build_video_radar(c, baseline, now) for c in contexts]
    axes = {}
    for i, first in enumerate(radars[0]['axes'] if radars else []):
        scores = [r['axes'][i]['score'] for r in radars if r['axes'][i]['score'] is not None]
        axes[first['id']] = dict(available=len(scores), missing=len(radars)-len(scores),
            ceiling=sum(s == 100 for s in scores), zero=sum(s == 0 for s in scores),
            distinct_scores=len(set(scores)), tied=len(scores)-len(set(scores)))
    correlations = {}
    for index in (1, 3):
        pairs = [r['axes'][index]['components'] for r in radars]
        pairs = [p for p in pairs if len(p) == 2 and all(c['score'] is not None for c in p)]
        correlations[radars[0]['axes'][index]['id'] if radars else str(index)] = {
            'samples': len(pairs), 'spearman': spearman([p[0]['score'] for p in pairs],
                                                      [p[1]['score'] for p in pairs]) if pairs else None}
    return dict(algorithm_version='radar-v2', reference_samples=baseline['sample_count'],
                baseline_version=baseline['version'], input_count=len(contexts), axes=axes,
                submetric_correlations=correlations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--now', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8-sig'))
    contexts = data['contexts'] if isinstance(data, dict) else data
    args.output.write_text(json.dumps(audit_contexts(contexts, args.now), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
