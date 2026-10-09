import unittest
from types import SimpleNamespace as S
from support import session, prop
from BL4ThirdPersonPOC.omni.native_idle_scope import IDLE_NAMES

class IdleScopeTests(unittest.TestCase):
    def setup_scope(self):
        o, _ = session()
        properties = [prop(name, 'StructProperty', i*100,
                          Struct=S(Name='GbxAnimNode_IdleTurns'))
                      for i,name in enumerate(sorted(IDLE_NAMES))]
        anim = S(Class=S(_superfields=lambda: (), _properties=lambda: properties),
                 _get_address=lambda: 10000)
        o.anim_ref=lambda: anim
        o.anim_address=10000
        o.native.read=lambda address,size: (20000).to_bytes(8,'little')
        worker=o.idle_native
        worker.table=20000
        # install() creates this metadata before calling bind_scope().
        o.report['idle_root_native_binding'] = {}
        return worker,properties

    def test_only_exact_reflected_local_nodes_published(self):
        worker,props=self.setup_scope()
        worker.bind_scope()
        self.assertEqual(len(worker.scope_nodes),5)
        self.assertEqual(list(worker.control)[5:9],[10000,10100,10300,10400])
        self.assertEqual(worker.control[0],0)

    def test_missing_node_fails_before_extra_receiver_publication(self):
        worker,props=self.setup_scope();props.pop()
        with self.assertRaisesRegex(RuntimeError,'node set'):
            worker.bind_scope()
        self.assertEqual(list(worker.control)[5:9],[0]*4)

    def test_changed_vtable_fails_before_extra_receiver_publication(self):
        worker,props=self.setup_scope()
        worker.capture.native.read=lambda address,size: (20001).to_bytes(8,'little')
        with self.assertRaisesRegex(RuntimeError,'vtable'):
            worker.bind_scope()
        self.assertEqual(list(worker.control)[5:9],[0]*4)
