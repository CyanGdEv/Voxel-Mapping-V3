import copy
from concurrent.futures import CancelledError
import json
import threading
import time
import unittest

import requests

from voxel_mapper import local_reasoning as reasoning


class Response:
    def __init__(self, lines, status=200):
        self.lines = lines; self.status_code = status; self.closed = False

    def iter_content(self, chunk_size=1024):
        for line in self.lines:
            if isinstance(line, Exception):
                raise line
            raw = (line if isinstance(line, bytes) else json.dumps(line).encode())+b'\n'
            for i in range(0,len(raw),chunk_size):
                yield raw[i:i+chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, response=None, error=None):
        self.response = response; self.error = error; self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if self.error:
            raise self.error
        return self.response


def proposal():
    return {'summary': 'Inspect the source before choosing a roof.', 'proposals': [
        {'action': 'inspect_evidence', 'parameters': {'path': 'evidence/roof.json'},
         'rationale': 'The two reflected candidates still need source support.'}]}


def response(payload=None):
    text = json.dumps(payload if payload is not None else proposal())
    return Response([{'model': 'small-local:latest', 'message': {'thinking': 'private scratch reasoning', 'content': text[:20]}},
                     {'model': 'small-local:latest', 'message': {'content': text[20:]}, 'done': True,
                      'eval_count': 22, 'prompt_eval_count': 96}])


class LocalReasoningTests(unittest.TestCase):
    def test_streamed_local_model_returns_only_unexecuted_bounded_proposals(self):
        stream = response(); session = Session(stream); progress=[]
        receipt = reasoning.reason('Inspect the supplied roof evidence.', model='small-local:latest',
                                   memory='Two mirrored source matches.', session=session, progress=progress.append)
        self.assertEqual(receipt['summary'], proposal()['summary']); self.assertEqual(len(receipt['proposals']), 1)
        self.assertFalse(receipt['proposals_executed']); self.assertFalse(receipt['source_evidence_verified'])
        self.assertFalse(receipt['model_weights_updated']); self.assertEqual(receipt['training_labels_generated'], 0)
        self.assertNotIn('private scratch reasoning', json.dumps(receipt)); self.assertGreater(receipt['discarded_thinking_characters'], 0)
        self.assertTrue(stream.closed); self.assertEqual(len(progress), 2)
        url, call = session.calls[0]; self.assertEqual(url, reasoning.DEFAULT_ENDPOINT+'/api/chat')
        self.assertEqual(call['json']['keep_alive'], 0); self.assertEqual(call['json']['options']['num_ctx'], 2048)
        self.assertEqual(call['json']['options']['num_predict'], 512); self.assertEqual(call['json']['options']['num_thread'], 2)
        self.assertTrue(call['stream']); self.assertLessEqual(call['timeout'][1], 30)

    def test_empty_proposal_list_is_valid_without_claiming_successful_reconstruction(self):
        r = reasoning.reason('No sources are available.', model='small', session=Session(response({'summary': 'More evidence is needed.', 'proposals': []})))
        self.assertEqual(r['proposals'], []); self.assertFalse(r['geometry_export_authorized'])

    def test_all_registered_action_types_are_advisory(self):
        payload={'summary': 'Consider the registered operations.', 'proposals': [
            {'action': 'generate_world', 'parameters': {'job_path': 'job.json', 'output_path': 'new-output'}, 'rationale': 'A configured job is available.'},
            {'action': 'train_ranker', 'parameters': {'feedback_path': 'feedback.json', 'split_path': 'split.json'}, 'rationale': 'Reviewed data exists.'}]}
        r=reasoning.reason('Review this plan.', model='small', session=Session(response(payload)))
        self.assertEqual([p['action'] for p in r['proposals']], ['generate_world', 'train_ranker'])
        self.assertFalse(r['proposals_executed'])

    def test_missing_server_and_missing_model_have_distinct_display_errors(self):
        for session, code in [(Session(error=requests.ConnectionError()), 'backend_unavailable'), (Session(Response([],404)), 'model_unavailable')]:
            with self.assertRaises(reasoning.ReasoningError) as error:
                reasoning.reason('Inspect sources.', model='small', session=session)
            self.assertEqual(error.exception.code, code)

    def test_socket_timeout_is_bounded_and_reported(self):
        with self.assertRaises(reasoning.ReasoningError) as error:
            reasoning.reason('Inspect sources.', model='small', read_timeout_seconds=.25, session=Session(error=requests.ReadTimeout()))
        self.assertEqual(error.exception.code, 'backend_timeout')

    def test_precancel_does_not_contact_server(self):
        session=Session(response())
        with self.assertRaises(CancelledError):
            reasoning.reason('Inspect sources.', model='small', session=session, cancelled=lambda: True)
        self.assertEqual(session.calls, [])

    def test_cancellation_does_not_wait_for_blocked_http_reader(self):
        entered=threading.Event(); release=threading.Event(); cancel=threading.Event(); finished=threading.Event(); errors=[]
        class BlockedSession(Session):
            def post(self, *args, **kwargs):
                entered.set(); release.wait(3); return response()
        def call():
            try: reasoning.reason('Inspect sources.', model='small', session=BlockedSession(), cancelled=cancel.is_set)
            except BaseException as error: errors.append(error)
            finally: finished.set()
        worker=threading.Thread(target=call);worker.start();self.assertTrue(entered.wait(1));cancel.set()
        try:
            self.assertTrue(finished.wait(.5));self.assertIsInstance(errors[0], CancelledError)
        finally:
            release.set();worker.join(1)

    def test_stream_ending_without_done_never_returns_partial_proposals(self):
        with self.assertRaises(reasoning.ReasoningError) as error:
            reasoning.reason('Inspect sources.', model='small', session=Session(Response([{'message': {'content': json.dumps(proposal())}}])))
        self.assertEqual(error.exception.code, 'incomplete_response')

    def test_stream_and_generated_json_are_both_validated(self):
        streams=[Response([b'not json']), Response([{'message': {'content': 'not JSON'}, 'done': True}]),
                 Response([{'message': [], 'done': True}]), Response([{'error': 'missing model'}])]
        for stream in streams:
            with self.subTest(stream=stream), self.assertRaises(reasoning.ReasoningError):
                reasoning.reason('Inspect sources.', model='small', session=Session(stream))
            self.assertTrue(stream.closed)

    def test_model_cannot_return_commands_or_acceptance_flags(self):
        payloads=[]
        for action in ('run_shell','modify_code','accept_geometry', []):
            p=proposal();p['proposals'][0]['action']=action;payloads.append(p)
        p=proposal();p['proposals'][0]['parameters']['physical_identity_verified']=True;payloads.append(p)
        p=proposal();p['geometry_export_authorized']=True;payloads.append(p)
        for payload in payloads:
            with self.subTest(payload=payload),self.assertRaises(reasoning.ReasoningError):
                reasoning.reason('Inspect sources.', model='small', session=Session(response(payload)))

    def test_path_parameters_are_plain_bounded_strings(self):
        for value in ('', 'x'*1025, 'job\ncommand', {'command': 'run'}):
            p=proposal();p['proposals'][0]['parameters']['path']=value
            with self.subTest(value=value),self.assertRaises(reasoning.ReasoningError):
                reasoning.reason('Inspect sources.', model='small', session=Session(response(p)))

    def test_stream_budget_counts_discarded_thinking_too(self):
        stream=Response([{'message': {'thinking': 'x'*2000}}, {'message': {'content': json.dumps(proposal())}, 'done': True}])
        with self.assertRaises(reasoning.ReasoningError) as error:
            reasoning.reason('Inspect sources.', model='small', max_response_bytes=1024, session=Session(stream))
        self.assertEqual(error.exception.code, 'response_budget_exceeded')

    def test_unterminated_stream_is_byte_bounded_before_ndjson_buffering(self):
        class Unfinished(Response):
            blocks_read = 0
            def iter_content(self, **kwargs):
                for _ in range(100):
                    self.blocks_read += 1
                    yield b'x'*1024
        stream=Unfinished([])
        with self.assertRaises(reasoning.ReasoningError) as error:
            reasoning.reason('Inspect sources.', model='small', max_response_bytes=1024, session=Session(stream))
        self.assertEqual(error.exception.code, 'response_budget_exceeded')
        self.assertEqual(stream.blocks_read, 2)

    def test_model_identity_cannot_change_midstream(self):
        stream=Response([{'model': 'one', 'message': {'content': ''}}, {'model': 'two', 'message': {'content': json.dumps(proposal())}, 'done': True}])
        with self.assertRaises(reasoning.ReasoningError) as error:
            reasoning.reason('Inspect sources.', model='small', session=Session(stream))
        self.assertEqual(error.exception.code, 'invalid_response')

    def test_receipt_integrity_rejects_tampering_and_resealed_execution_claim(self):
        r=reasoning.reason('Inspect sources.', model='small', session=Session(response()));self.assertEqual(reasoning.validate_receipt(r),r)
        changed=copy.deepcopy(r);changed['summary']='Altered'
        with self.assertRaises(ValueError):reasoning.validate_receipt(changed)
        changed=copy.deepcopy(r);changed['proposals_executed']=True;changed['artifact_sha256']=reasoning._hash({k:v for k,v in changed.items() if k!='artifact_sha256'})
        with self.assertRaises(ValueError):reasoning.validate_receipt(changed)

    def test_invalid_models_endpoints_and_resource_options_never_contact_server(self):
        cases=[{'model':''},{'model':'small\ncommand'},{'endpoint':'file:///tmp/model'},{'endpoint':'http://user:pass@localhost:11434'},
               {'endpoint':'http://localhost:11434/path'},{'options':{'num_thread':3}},{'options':{'num_ctx':4096}},
               {'options':{'num_predict':513}},{'options':{'num_ctx':1024,'num_predict':512}},
               {'options':{'temperature':float('nan')}},{'options':{'unbounded':True}},
               {'memory':'x'*2049},{'prompt':'x'*4097},{'memory':'x'*2048,'prompt':'x'*2049}]
        for values in cases:
            session=Session(response());args={'prompt':'Inspect sources.','model':'small','session':session,**values}
            with self.subTest(values=values),self.assertRaises(ValueError):reasoning.reason(**args)
            self.assertEqual(session.calls,[])
