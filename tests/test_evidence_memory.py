import tempfile
import unittest
from pathlib import Path
from voxel_mapper.evidence_memory import EvidenceMemory


class MemoryTests(unittest.TestCase):
    def test_restart_reuses_exact_inputs_and_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'memory.sqlite'
            with EvidenceMemory(path) as memory:
                fact=memory.put('observation',{'sha':'a'}, {'candidate':True})
                self.assertEqual(fact,memory.put('observation',{'sha':'a'}, {'candidate':True}))
            with EvidenceMemory(path) as memory:
                self.assertEqual(memory.get('observation',{'sha':'a'})['id'],fact)
                self.assertIsNone(memory.get('observation',{'sha':'b'}))
                with self.assertRaisesRegex(ValueError,'Conflicting'):
                    memory.put('observation',{'sha':'a'}, {'candidate':False})
                self.assertEqual(memory.report()['training_labels_generated'],0)

    def test_rejection_invalidates_descendants_but_retains_independent_facts(self):
        with tempfile.TemporaryDirectory() as directory,EvidenceMemory(Path(directory)/'memory.sqlite') as memory:
            a=memory.put('survey',{'source':'a'},{'observed':True})
            b=memory.put('building',{'id':'b'},{'fit':True},[a])
            memory.put('path',{'id':'p'},{'fit':True},[b])
            c=memory.put('survey',{'source':'c'},{'observed':True})
            args={'reviewer':'review-1','reason':'incorrect physical correspondence','review_reference':'qa/17'}
            memory.reject(a,**args);memory.reject(a,**args)
            self.assertEqual(memory.report()['facts'],{'invalidated':2,'rejected':1,'retained':1})
            self.assertEqual(memory.report()['reviewed_rejections'],1)
            with self.assertRaisesRegex(ValueError,'invalidated'):memory.get('building',{'id':'b'},[a])
            with self.assertRaisesRegex(ValueError,'parent'):memory.put('path',{'id':'new'},{},[b])
            self.assertEqual(memory.get('survey',{'source':'c'})['id'],c)

    def test_corruption_and_unknown_parents_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory,EvidenceMemory(Path(directory)/'memory.sqlite') as memory:
            with self.assertRaisesRegex(ValueError,'parent'):memory.put('drawing',{}, {},['missing'])
            fact=memory.put('drawing',{}, {'value':1})
            with memory.db:memory.db.execute('UPDATE facts SET payload=? WHERE id=?',('{"value":2}',fact))
            with self.assertRaisesRegex(ValueError,'checksum'):memory.get('drawing',{})
