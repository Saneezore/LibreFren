"""Boot evidence must include every milestone and a clean emulator exit."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from librefren.safety import Refusal
from tools.check_coreboot_build import qemu_boot


class EmulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image'
        self.image.write_bytes(b'emulated-test-image')
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.markers = ['coreboot-test ramstage starting', 'SeaBIOS (version fixture)', 'No bootable device.']

    def run_case(self, markers, code=0):
        evidence = self.root / 'evidence'
        evidence.mkdir(exist_ok=True)
        for path in evidence.iterdir():
            path.unlink()
        process = Mock(returncode=code)
        process.wait.side_effect = [subprocess.TimeoutExpired('qemu', 45), code]
        process.poll.return_value = code
        def start(*args, **kwargs):
            (evidence / 'qemu-debug.log').write_text('\n'.join(markers))
            return process
        with patch('tools.check_coreboot_build.subprocess.check_output', return_value='QEMU fixture\n'), \
                patch('tools.check_coreboot_build.subprocess.Popen', side_effect=start):
            result = qemu_boot(self.image, self.digest, evidence)
        process.stdin.write.assert_called_once()
        process.stdin.close.assert_called_once()
        return result

    def test_all_markers_and_clean_exit_are_required(self):
        self.assertTrue(self.run_case(self.markers)['passed'])
        for missing in range(len(self.markers)):
            with self.subTest(missing=missing), self.assertRaises(Refusal):
                self.run_case(self.markers[:missing] + self.markers[missing+1:])
            result = json.loads((self.root / 'evidence/qemu.json').read_text())
            self.assertFalse(result['passed'])
        with self.assertRaises(Refusal):
            self.run_case(self.markers, code=1)

    def test_changed_candidate_cannot_start_emulation(self):
        with patch('tools.check_coreboot_build.subprocess.Popen') as start, self.assertRaises(Refusal):
            qemu_boot(self.image, '0' * 64, self.root)
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
