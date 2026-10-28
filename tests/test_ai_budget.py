import json
from unittest.mock import patch
from tests.test_translation import TranslationTests


class AIBudgetTests(TranslationTests):
    def test_missing_month_cap_blocks_even_explicit_translation(self):
        rid = self.record(title='Public original')
        jid = self.call(f'/api/records/{rid}/translations', {'version':1,'request_id':'budget-gate'}).json['id']
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'synthetic-secret', 'AI_MONTHLY_CAP':'', 'DEEPSEEK_PRICING_JSON':'{}'}):
            with patch('urllib.request.OpenerDirector.open', return_value=self.provider('译题','')) as network:
                result = self.call(f'/api/translations/{jid}/run')
        self.assertEqual(result.json['status'], 'failed')
        network.assert_not_called()
        state = self.get('/api/admin/ai', user='admin')
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json['held_units'], 0)
