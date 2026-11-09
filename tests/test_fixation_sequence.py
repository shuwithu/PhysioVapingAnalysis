import unittest
from decimal import Decimal
from physiovaping.fixation_sequence import add_sequence


class SequenceTests(unittest.TestCase):
    def test_order_gaps_categories_and_original_values(self):
        rows = [
            dict(SourceRow='1', Start_Unix='12', End_Unix='13', ObjectName='JoeAOI', ObjectTag='Vapers'),
            dict(SourceRow='2', Start_Unix='10', End_Unix='11', ObjectName='PhoneScreenAOI', ObjectTag='Others'),
            dict(SourceRow='3', Start_Unix='12', End_Unix='14', ObjectName='BBQSmoke1', ObjectTag='Smoke'),
        ]
        result = add_sequence(rows, Decimal('9'))
        self.assertEqual([r['SourceRow'] for r in result], ['2', '1', '3'])
        self.assertEqual(result[0]['PreviousObjectName'], '')
        self.assertEqual(result[0]['GapSincePreviousFixation_s'], '')
        self.assertEqual(result[0]['StartSinceSceneStart_s'], '1')
        self.assertEqual(result[1]['GapSincePreviousFixation_s'], '1')
        self.assertEqual(result[1]['PreviousCueCategory'], 'NonSocialVapingCue')
        self.assertEqual(result[2]['GapSincePreviousFixation_s'], '-1')
        self.assertEqual(result[2]['SameStartAsPrevious'], 'True')
        self.assertEqual(result[2]['OverlapsPrevious'], 'True')
        self.assertNotIn('FixationOrder', rows[0])
        self.assertEqual(add_sequence([], Decimal(0)), [])


if __name__ == '__main__':
    unittest.main()
