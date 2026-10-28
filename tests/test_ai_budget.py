import json
from unittest.mock import patch
from tests.test_translation import TranslationTests


class AIBudgetTests(TranslationTests):
    def test_admin_persists_cap_and_members_cannot_change_it(self):
        result = self.call('/api/admin/ai/config', {'cap':'0.125','currency':'USD'}, user='admin')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['cap_units'], 125000)
        self.assertEqual(self.get('/api/admin/ai', 'admin').json['currency'], 'USD')
        self.assertEqual(self.call('/api/admin/ai/config', {'cap':'5','currency':'USD'}).status_code, 403)
        self.assertEqual(self.clients['admin'].post('/api/admin/ai/config', json={'cap':'5','currency':'USD'}).status_code, 403)

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
