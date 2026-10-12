from copy import deepcopy
from scripts.audit_radar_v2 import audit_contexts
from tests.test_radar_v2 import context, NOW


def test_audit_reports_inadequate_reference_without_inventing_scores():
    rows = [context()]
    before = deepcopy(rows)
    result = audit_contexts(rows, NOW)
    assert result['reference_samples'] == 1
    assert result['axes']['reach']['available'] == 0
    assert result['axes']['reach']['missing'] == 1
    assert rows == before


def test_audit_reports_broad_reference_and_separate_behavior_distributions():
    result = audit_contexts([context(i) for i in range(240)], NOW)
    assert result['reference_samples'] == 240
    assert result['axes']['reach']['available'] == 240
    assert result['axes']['reach']['ceiling'] == 0
    assert 'approval' in result['axes']
