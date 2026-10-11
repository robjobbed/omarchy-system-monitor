"""Focused source-boundary checks; not a substitute for live QML acceptance."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent

class SecurityTests(unittest.TestCase):
    def test_ipc_surface_is_minimal_and_status_omits_telemetry(self):
        source = (ROOT / 'Panel.qml').read_text()
        block = source.split('    IpcHandler {', 1)[1].split('\n    Row {', 1)[0]
        methods = set(re.findall(r'function (\w+)\(', block))
        self.assertEqual(methods, {'open', 'close', 'toggle', 'status', 'memory', 'view', 'sort'})
        status = re.search(r'function status\(\).*', block).group(0)
        for field in ['root.data', 'root.details', 'root.apps', 'networkHistory']:
            self.assertNotIn(field, status, msg='status must not export local telemetry')

    def test_collectors_use_trusted_executables_and_argv(self):
        import backend
        from unittest.mock import patch
        import subprocess
        with patch.object(backend.os, 'access', return_value=True), patch.object(backend.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='GPU, 1, 2, 3, 4, 5, 6\n')) as run:
            backend.gpu()
        self.assertTrue(run.called, msg='GPU query boundary was not exercised')
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/nvidia-smi')
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertEqual(run.call_args.kwargs['timeout'], 1.5)
        panel = (ROOT / 'Panel.qml').read_text()
        self.assertIn('command: ["/usr/bin/python3", "-I", "-u", root.backend]', panel,
                      msg='isolate collector from user Python import configuration')

    def test_missing_gpu_does_not_spawn(self):
        import backend
        from unittest.mock import patch
        with patch.object(backend.os, 'access', return_value=False), patch.object(backend.subprocess, 'run') as run:
            self.assertFalse(backend.gpu()['available'])
            run.assert_not_called()

    def test_gpu_failures_are_sanitized(self):
        import backend
        import subprocess
        from unittest.mock import patch
        failures = [OSError('private diagnostic'), subprocess.TimeoutExpired('private command', 1.5)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(backend.os, 'access', return_value=True), patch.object(backend.subprocess, 'run', side_effect=failure):
                self.assertEqual(backend.gpu(), {'available': False, 'error': 'NVIDIA telemetry unavailable'})
                self.assertEqual(backend.nvidia_gpu(), {'available': False, 'error': 'NVIDIA telemetry unavailable'})
        with patch.object(backend.os, 'access', return_value=True), patch.object(backend.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='malformed, private data')):
            self.assertEqual(backend.gpu(), {'available': False, 'error': 'NVIDIA telemetry unavailable'})

    def test_untrusted_dashboard_labels_are_plain_text(self):
        source = (ROOT / 'Dashboard.qml').read_text()
        label = re.search(r'component Label: Text \{(.*?)\n    \}', source, re.S)
        self.assertIsNotNone(label, msg='shared label component missing')
        self.assertIn('textFormat: Text.PlainText', label.group(1))
        self.assertNotIn('Qt.openUrlExternally', source)
        self.assertNotIn('source:modelData', source)

    def test_manifest_and_qml_use_public_identity(self):
        import json
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        self.assertEqual(manifest['id'], 'cynricantao.system-monitor')
        self.assertEqual(manifest['author'], 'cynricantao')
        panel = (ROOT / 'Panel.qml').read_text()
        for field in ['moduleName', 'ipcTarget', 'target']:
            self.assertIn(field + ': "cynricantao.system-monitor"', panel)

    def test_intel_collector_reads_only_sysfs_proc_and_pci_database(self):
        import backend
        import inspect
        source = inspect.getsource(backend.IntelGpu) + inspect.getsource(backend.fans) + inspect.getsource(backend.pci_name)
        self.assertNotIn('subprocess', source, msg='Intel and fan telemetry must not spawn processes')
        self.assertNotIn('write_text', source)
        for path in ['/sys/class/drm', '/sys/class/hwmon', '/usr/share/hwdata/pci.ids']:
            self.assertIn(path, inspect.getsource(backend))

    def test_intel_card_emits_no_paths_or_pids(self):
        import backend
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card = root/'drm'/'card0'; (card/'device').mkdir(parents=True)
            (card/'device'/'vendor').write_text('0x8086'); (card/'device'/'device').write_text('0x46a8')
            fd = root/'proc'/'4242'/'fdinfo'; fd.mkdir(parents=True)
            (fd/'3').write_text('drm-driver:\ti915\ndrm-client-id:\t1\ndrm-engine-render:\t0 ns\ndrm-resident-system0:\t4 KiB\n')
            gpu = backend.IntelGpu(drm=root/'drm', proc=root/'proc', hwmon=tmp, database=root/'none')
            text = str(gpu.sample(1))
            self.assertNotIn('4242', text)
            self.assertNotIn(tmp, text)

if __name__ == '__main__':
    unittest.main()
