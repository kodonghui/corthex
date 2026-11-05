"""TC-390 partial: Native identity evidence on this fixture filesystem, not migration authority."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import maintenance_identity as identity


class MaintenanceIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent/'original'; self.root.mkdir()
        self.file = self.root/'metadata'; self.file.write_bytes(b'original')

    def test_node_capture_is_readonly_and_does_not_open_contents(self):
        with mock.patch.object(Path, 'open', side_effect=AssertionError('no content read')):
            binding = identity.bind(self.root)
            binding.check()
            self.assertEqual(identity.capture(self.file, entry='file').document()['entry'], 'file')
        self.assertEqual(self.file.read_bytes(), b'original')
        self.assertEqual(list(self.root.iterdir()), [self.file])

    def test_contents_and_children_do_not_change_node_identity(self):
        directory, file = identity.bind(self.root), identity.bind(self.file, entry='file')
        self.file.write_bytes(b'changed'); (self.root/'other').write_bytes(b'new')
        directory.check(); file.check()

    def test_identical_bytes_in_distinct_nodes_have_distinct_identity(self):
        other = self.root/'copy'; other.write_bytes(self.file.read_bytes())
        self.assertNotEqual(identity.capture(self.file, entry='file'), identity.capture(other, entry='file'))

    def test_a_hardlink_is_the_same_file_node(self):
        other = self.root/'alias'; os.link(str(self.file), str(other))
        self.assertEqual(identity.capture(self.file, entry='file'), identity.capture(other, entry='file'))

    def test_directory_replacement_is_sticky_even_after_original_returns(self):
        binding = identity.bind(self.root)
        saved = self.parent/'saved'; self.root.rename(saved); self.root.mkdir()
        with self.assertRaises(identity.IdentityUnavailable): binding.check()
        self.root.rmdir(); saved.rename(self.root)
        with self.assertRaises(identity.IdentityUnavailable): binding.check()
        identity.bind(self.root).check()

    def test_file_replacement_is_observed_without_inode_reuse(self):
        binding = identity.bind(self.file, entry='file')
        self.file.rename(self.root/'saved'); self.file.write_bytes(b'original')
        with self.assertRaises(identity.IdentityUnavailable): binding.check()

    def test_missing_relative_traversal_and_wrong_kinds_refuse(self):
        for path, entry in [(self.parent/'missing', 'directory'), (Path('relative'), 'file'),
                            (self.root/'..'/'original', 'directory'), (self.file, 'directory'),
                            (self.root, 'file'), (self.root, 'unknown')]:
            with self.subTest(entry=entry), self.assertRaises(identity.IdentityUnavailable):
                identity.capture(path, entry=entry)

    def test_target_link_is_never_followed(self):
        alias = self.parent/'alias'
        if os.name == 'nt':
            command = Path(os.environ['SystemRoot'])/'System32/cmd.exe'
            done = subprocess.run([str(command), '/d', '/c', 'mklink', '/J', str(alias), str(self.root)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(done.returncode, 0); self.addCleanup(alias.rmdir)
        else:
            alias.symlink_to(self.root, target_is_directory=True); self.addCleanup(alias.unlink)
        with self.assertRaises(identity.IdentityUnavailable): identity.capture(alias)

    def test_failures_have_fixed_messages_and_revoke_the_binding(self):
        binding = identity.bind(self.root)
        with mock.patch.object(identity, 'capture', side_effect=OSError('private path')):
            with self.assertRaisesRegex(identity.IdentityUnavailable, '^maintenance identity unavailable$'): binding.check()
        with self.assertRaises(identity.IdentityUnavailable): binding.check()

    def test_parent_process_binding_cannot_be_revived_by_another_pid(self):
        binding = identity.bind(self.root)
        with mock.patch.object(identity.os, 'getpid', return_value=binding.pid+1):
            with self.assertRaises(identity.IdentityUnavailable): binding.check()
        with self.assertRaises(identity.IdentityUnavailable): binding.check()

    def test_roundtrip_detaches_data_and_keeps_private_values_out_of_repr(self):
        value = identity.capture(self.root)
        self.assertEqual(value, identity.parse(value.encoded))
        changed = value.document(); changed['file'] = 'f'*32
        self.assertNotEqual(changed, value.document())
        self.assertNotIn(value.document()['volume'], repr(value))
        self.assertNotIn(str(self.root), repr(identity.bind(self.root)))

    def test_all_128_bits_and_volume_and_filesystem_bits_are_retained(self):
        value = dict(version=1, kind='windows-file-id', entry='file', volume='fedcba9876543210', file='f'*32)
        self.assertEqual(identity.parse(json.dumps(value).encode()).document(), value)
        value.update(kind='posix-fstat', filesystem='f'*16)
        first = identity.parse(json.dumps(value).encode())
        for name in ('file', 'volume', 'filesystem'):
            other = dict(value); other[name] = '0'*len(other[name])
            self.assertNotEqual(first, identity.parse(json.dumps(other).encode()))

    def test_malformed_identity_documents_are_refused(self):
        valid = identity.capture(self.root).document()
        bad = [b'null', b'[]', b'{"version":1,"version":1}', b'\xff']
        for change in [dict(version=True), dict(version=2), dict(file='F'*32), dict(volume='0'*15),
                       dict(kind='opaque'), dict(entry='link'), dict(extra=1)]:
            bad.append(json.dumps(dict(valid, **change)).encode())
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(identity.IdentityUnavailable): identity.parse(raw)

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor race')
    def test_path_swap_during_open_refuses_and_closes_descriptor(self):
        original, descriptors = os.open, []
        def replaced(path, flags):
            self.file.rename(self.root/'saved'); self.file.write_bytes(b'original')
            descriptor = original(path, flags); descriptors.append(descriptor); return descriptor
        with mock.patch.object(identity.os, 'open', side_effect=replaced):
            with self.assertRaises(identity.IdentityUnavailable): identity.capture(self.file, entry='file')
        with self.assertRaises(OSError): os.fstat(descriptors[0])

    @unittest.skipIf(os.name == 'nt', 'POSIX FIFO')
    def test_fifo_is_refused_before_opening(self):
        fifo = self.root/'fifo'; os.mkfifo(str(fifo))
        with mock.patch.object(identity.os, 'open', side_effect=AssertionError('no open')):
            with self.assertRaises(identity.IdentityUnavailable): identity.capture(fifo, entry='file')

    @unittest.skipIf(os.name == 'nt', 'POSIX filesystem query')
    def test_unsupported_native_query_refuses_and_closes_descriptor(self):
        with mock.patch.object(identity.os, 'fstatvfs', side_effect=OSError('unsupported')), \
                mock.patch.object(identity.os, 'close', wraps=os.close) as close:
            with self.assertRaises(identity.IdentityUnavailable): identity.capture(self.root)
            self.assertEqual(close.call_count, 1)


if __name__ == '__main__': unittest.main()
