import json
import os
from unittest import TestCase
from unittest.mock import patch
from workbench.investigator import evidence_for, investigate, validate_report


SNAPSHOT = {'state':'stopped','reason':'Stopped by signal 11','registers':{'rip':'0x401100','rax':'0x0'},
            'stack':[{'name':'read_balance','location':'crash.cpp:4','address':'0x401100'}],
            'source':{'name':'crash.cpp','line':2,'text':'int read_balance(int* p) {\n return *p;\n}'},
            'disassembly':['401100: mov eax, DWORD PTR [rax]']}


class InvestigatorTests(TestCase):
    def test_evidence_contains_actual_stop_and_source(self):
        evidence = evidence_for(SNAPSHOT)
        self.assertEqual(evidence[0]['value'], 'Stopped by signal 11')
        self.assertEqual(len({item['id'] for item in evidence}), len(evidence))
        self.assertTrue(any('return *p' in item['value'] for item in evidence))

    def test_unknown_references_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'unknown evidence'):
            validate_report({'summary':'Possible pointer issue','hypotheses':[
                {'claim':'Pointer could be invalid','next_check':'Inspect RAX','evidence_ids':['E999']}]},evidence_for(SNAPSHOT))

    def test_missing_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_report({'summary':'Something happened','hypotheses':[
                {'claim':'Guess','next_check':'Inspect','evidence_ids':[]}]},evidence_for(SNAPSHOT))

    def test_no_model_configuration_is_explicit(self):
        with patch.dict(os.environ, {'STILLPOINT_AI_MODEL':''}):
            with self.assertRaisesRegex(ValueError,'No AI model configured'):
                investigate(SNAPSHOT, 'Explain')

    def test_external_provider_url_is_rejected(self):
        with patch.dict(os.environ, {'STILLPOINT_AI_MODEL':'test','STILLPOINT_AI_URL':'https://external.example'}):
            with self.assertRaisesRegex(ValueError,'local Ollama'):
                investigate(SNAPSHOT,'Explain')

    def test_model_adapter_sends_captured_evidence_and_validates_response(self):
        model_report = {'summary':'A memory access fault was observed.', 'hypotheses':[
            {'claim':'An invalid pointer may be involved.','evidence_ids':['E1'],'next_check':'Inspect the instruction operands.'}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,_): return json.dumps({'message':{'content':json.dumps(model_report)}}).encode()
        def model(request,timeout):
            payload=json.loads(request.data)
            self.assertFalse(payload['stream'])
            self.assertIn('Stopped by signal 11',payload['messages'][1]['content'])
            return Response()
        with patch.dict(os.environ, {'STILLPOINT_AI_MODEL':'test','STILLPOINT_AI_URL':'http://localhost:11434'}), patch('workbench.investigator.local_open',side_effect=model):
            result=investigate(SNAPSHOT,'Explain')
            self.assertEqual(result['status'],'hypothesis')
            self.assertEqual(result['model'],'test')
            self.assertEqual(result['hypotheses'][0]['evidence_ids'],['E1'])
