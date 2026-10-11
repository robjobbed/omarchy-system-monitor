import os
import tempfile
import unittest
from pathlib import Path
import backend as b

class Tests(unittest.TestCase):
    def record(self, pid, name, parent=0, ticks=0, start=1, pss=1024):
        return dict(pid=pid, name=name, comm=name, ppid=parent, ticks=ticks, start=start, rss=4096, pss=pss)

    def test_cpu_capacity_and_iowait(self):
        self.assertEqual(b.cpu_percent((100,40),(200,90)),50)
        self.assertIsNone(b.cpu_percent((100,40),(100,40)))

    def test_stat_name_with_parentheses(self):
        fields=['S','1']+['0']*22
        fields[11],fields[12],fields[19],fields[21]='12','3','123','2'
        p=b.parse_stat('99 (name (helper)) '+' '.join(fields))
        self.assertEqual(p['comm'],'name (helper)')
        self.assertEqual(p['ticks'],15)
        self.assertEqual(p['start'],123)
        self.assertEqual(p['rss'],2*b.PAGE)

    def test_vivaldi_helpers_merge_btop_rss_and_retain_pss(self):
        records={1:self.record(1,'vivaldi-bin',ticks=b.HZ),2:self.record(2,'vivaldi-bin',1,ticks=b.HZ),3:self.record(3,'chrome_crashpad_handler',1,ticks=b.HZ)}
        old={pid:dict(p,ticks=0) for pid,p in records.items()}
        groups=b.group_processes(records,old,1,4)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['name'],'Vivaldi')
        self.assertEqual(groups[0]['count'],3)
        self.assertEqual(groups[0]['cpu'],75)
        self.assertEqual(groups[0]['memory'],12288)
        self.assertEqual(groups[0]['rss'],12288)
        self.assertEqual(groups[0]['pss'],3072)

    def test_pid_reuse_does_not_spike(self):
        p=self.record(1,'example',ticks=100000,start=2,pss=None)
        groups=b.group_processes({1:p},{1:dict(p,ticks=0,start=1)},1,4)
        self.assertEqual(groups[0]['cpu'],0)
        self.assertEqual(groups[0]['memory'],4096)
        self.assertEqual(groups[0]['rss_fallback'],1)

    def test_incomplete_pss_is_unavailable_not_rss(self):
        records={1:self.record(1,'vivaldi-bin',pss=1024),2:self.record(2,'vivaldi-bin',1,pss=None)}
        group=b.group_processes(records,{},1,4)[0]
        self.assertEqual(group['memory'],8192)
        self.assertEqual(group['rss'],8192)
        self.assertIsNone(group['pss'])
        self.assertEqual(group['rss_fallback'],1)

    def test_pss_zero_is_not_replaced_with_rss(self):
        p=self.record(1,'example',pss=0)
        group=b.group_processes({1:p},{},1,4)[0]
        self.assertEqual(group['rss'],4096)
        self.assertEqual(group['pss'],0)
        self.assertEqual(group['rss_fallback'],0)

    def test_network_reset(self):
        self.assertEqual(b.rates({'eth0':(200,200)},{'eth0':(100,300)},2),[dict(name='eth0',read=0,write=50)])

    def test_closed_does_not_scan_processes(self):
        from unittest.mock import patch
        sampler=b.Sampler()
        with patch.object(b,'process_records',side_effect=AssertionError('unexpected scan')):
            result=sampler.sample(False)
        self.assertFalse(result['detailed'])
        self.assertNotIn('apps',result)
        self.assertTrue(0 <= result['memory']['percent'] <= 100)

    def fake_tree(self, root):
        root = Path(root)
        card = root/'drm'/'card1'
        (card/'device').mkdir(parents=True)
        (card/'device'/'vendor').write_text('0x8086\n')
        (card/'device'/'device').write_text('0x46a8\n')
        (card/'gt'/'gt0').mkdir(parents=True)
        (card/'gt'/'gt0'/'rps_act_freq_mhz').write_text('850\n')
        (card/'gt'/'gt0'/'rps_RP0_freq_mhz').write_text('1200\n')
        (card/'gt'/'gt0'/'rc6_residency_ms').write_text('10000\n')
        (root/'drm'/'card1-eDP-1').mkdir()
        (root/'drm'/'renderD128').mkdir()
        hw = root/'hwmon'
        (hw/'hwmon5').mkdir(parents=True)
        (hw/'hwmon5'/'name').write_text('coretemp\n')
        (hw/'hwmon5'/'temp1_label').write_text('Package id 0\n')
        (hw/'hwmon5'/'temp1_input').write_text('49000\n')
        (hw/'hwmon3').mkdir()
        (hw/'hwmon3'/'name').write_text('dell_ddv\n')
        (hw/'hwmon3'/'fan1_input').write_text('1306\n')
        (hw/'hwmon3'/'fan1_label').write_text('CPU Fan\n')
        (hw/'hwmon4').mkdir()
        (hw/'hwmon4'/'name').write_text('dell_smm\n')
        (hw/'hwmon4'/'fan1_input').write_text('1306\n')
        (hw/'hwmon4'/'pwm1').write_text('128\n')
        (hw/'hwmon4'/'fan2_input').write_text('900\n')
        (root/'pci.ids').write_text('# comment\n8086  Intel Corporation\n\t46a8  Alder Lake-UP3 GT2 [Iris Xe Graphics]\n\t\t1028 0b01  Subsystem\n10de  NVIDIA Corporation\n\t46a8  Not this one\n')
        (root/'proc'/'1'/'fdinfo').mkdir(parents=True)
        (root/'proc'/'self').mkdir()
        (root/'proc'/'1'/'fd').mkdir()
        return root

    def fdinfo(self, root, pid, fd, cid, render, memory='100 KiB', driver='i915', pdev=None, video=None):
        text = 'pos:\t0\nflags:\t02\ndrm-driver:\t%s\n' % driver + ('drm-pdev:\t%s\n' % pdev if pdev else '') + 'drm-client-id:\t%s\ndrm-engine-render:\t%d ns\ndrm-engine-copy:\t0 ns\ndrm-resident-system0:\t%s\ndrm-total-system0:\t%s\n' % (cid, render, memory, memory)
        if video is not None:
            text += 'drm-engine-capacity-video:\t2\ndrm-engine-video:\t%d ns\n' % video
        d = root/'proc'/str(pid)/'fdinfo'
        d.mkdir(parents=True, exist_ok=True)
        (d/str(fd)).write_text(text)
        links = root/'proc'/str(pid)/'fd'
        links.mkdir(exist_ok=True)
        if not (links/str(fd)).is_symlink():
            os.symlink('/dev/dri/renderD128', links/str(fd))
        if not (links/'0').is_symlink():
            os.symlink('/dev/null', links/'0')  # ordinary fd: never opened

    def test_pci_name_matches_vendor_and_device_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_tree(tmp)
            self.assertEqual(b.pci_name('8086', '46a8', root/'pci.ids'), 'Alder Lake-UP3 GT2 [Iris Xe Graphics]')
            self.assertIsNone(b.pci_name('8086', 'ffff', root/'pci.ids'))
            self.assertIsNone(b.pci_name('8086', '46a8', root/'missing'))

    def test_intel_gpu_engines_memory_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_tree(tmp)
            self.fdinfo(root, 1, 3, '5', render=0, memory='100 KiB')
            self.fdinfo(root, 1, 4, '5', render=0, memory='100 KiB')  # same client, second fd: counted once
            self.fdinfo(root, 2, 3, '6', render=0, memory='1 MiB', video=0)
            self.fdinfo(root, 3, 3, '9', render=0, driver='amdgpu')  # other card
            gpu = b.IntelGpu(drm=root/'drm', proc=root/'proc', hwmon=str(root/'hwmon'), database=root/'pci.ids')
            self.assertTrue(gpu.available)
            self.assertEqual(gpu.name, 'Intel Iris Xe Graphics')
            first = gpu.sample(16 * 1024**3)
            self.assertTrue(first['available'])
            self.assertIsNone(first['percent'], msg='no delta on the first sample')
            self.assertEqual(first['used'], 100*1024 + 1024**2)
            self.assertEqual(first['total'], 16 * 1024**3)
            self.assertEqual(first['memory_kind'], 'shared')
            self.assertEqual(first['temperature'], 49.0)
            self.assertEqual((first['frequency'], first['max_frequency']), (850, 1200))
            self.assertIsNone(first['power'])
            self.assertIsNone(first['fan'])
            gpu.time -= 1.0  # one second passed
            gpu.rc6 -= 700
            self.fdinfo(root, 1, 3, '5', render=int(0.5e9), memory='100 KiB')
            self.fdinfo(root, 1, 4, '5', render=int(0.5e9), memory='100 KiB')
            self.fdinfo(root, 2, 3, '6', render=int(0.1e9), memory='1 MiB', video=int(1.0e9))  # capacity 2: 50%
            second = gpu.sample(16 * 1024**3)
            self.assertAlmostEqual(second['engines']['render'], 60, delta=1.5)
            self.assertAlmostEqual(second['engines']['video'], 50, delta=1.5)
            self.assertEqual(second['engines']['copy'], 0)
            self.assertEqual(second['percent'], second['engines']['render'])
            self.assertAlmostEqual(second['awake'], 30, delta=1.5)
            self.assertEqual(second['clients'], 2)

    def test_intel_gpu_unreadable_fdinfo_and_exited_clients_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_tree(tmp)
            self.fdinfo(root, 1, 3, '5', render=int(5e9))
            gpu = b.IntelGpu(drm=root/'drm', proc=root/'proc', hwmon=str(root/'hwmon'), database=root/'pci.ids')
            gpu.sample(1)
            gpu.time -= 1.0
            (root/'proc'/'1'/'fdinfo'/'3').unlink()  # exited
            self.fdinfo(root, 7, 3, '8', render=int(9e9))  # new client: no baseline, no spike
            os.chmod(root/'proc'/'7'/'fdinfo'/'3', 0)
            try:
                result = gpu.sample(1)
            finally:
                os.chmod(root/'proc'/'7'/'fdinfo'/'3', 0o644)
            self.assertEqual(result['engines'], {})
            self.assertIsNone(result['percent'])

    def test_no_intel_card_is_unavailable_without_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'drm').mkdir()
            gpu = b.IntelGpu(drm=Path(tmp)/'drm', proc=Path(tmp), hwmon=tmp, database=Path(tmp)/'none')
            self.assertFalse(gpu.available)
            from unittest.mock import patch
            with patch.object(b.os, 'access', return_value=False):
                self.assertEqual(b.gpu(gpu, 1), {'available': False, 'error': 'GPU telemetry unavailable'})

    def test_fans_merge_mirrored_chips_keeping_label_and_pwm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_tree(tmp)
            fans = b.Fans(str(root/'hwmon'))
            self.assertEqual(fans.sample(), [dict(name='CPU Fan', rpm=1306, percent=50, chip='dell_ddv'), dict(name='dell_smm fan2', rpm=900, percent=None, chip='dell_smm')])
            (root/'hwmon'/'hwmon4'/'fan1_input').write_text('1400\n')  # chips disagree: no longer a mirror
            self.assertEqual([f['rpm'] for f in fans.sample()], [1306, 1400, 900])
            (root/'hwmon'/'hwmon3'/'fan1_input').unlink()  # vanished sensor is skipped, not fatal
            self.assertEqual([f['name'] for f in fans.sample()], ['dell_smm fan1', 'dell_smm fan2'])

    def test_sample_carries_fans_and_gpu_history(self):
        sampler = b.Sampler()
        result = sampler.sample(False)
        self.assertIsInstance(result['fans'], list)
        self.assertIn('gpu', result['history'][-1])

if __name__=='__main__':
    unittest.main()
