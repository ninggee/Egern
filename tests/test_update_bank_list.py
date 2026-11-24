import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/update_bank_list.py'
spec = importlib.util.spec_from_file_location('update_bank_list', SCRIPT)
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)


def bank_file(*domains):
    return '\n'.join('DOMAIN-SUFFIX,' + d for d in domains) + '\n'


def fixture_dir(directory):
    """Minimal upstream sources that satisfy every guard in collect()."""
    root = Path(directory)
    files = {
        'ICBC.list': bank_file('icbc.com.cn', '95588.com', 'shared.example.com', 'icbc',
                               *('dummy%d.example.com' % i for i in range(210))),
        'CCB.list': bank_file('ccb.com', 'shared.example.com'),
        'ABC.list': bank_file('abchina.com'),
        'BOC.list': bank_file('boc.cn'),
        'BOCOM.list': bank_file('bankcomm.com'),
        'PSBC.list': bank_file('psbc.com'),
        'CMB.list': bank_file('cmbchina.com'),
        'CITIC.list': bank_file('citicbank.com', '集团.中信'),
        'CEB.list': bank_file('cebbank.com'),
        'CGB.list': bank_file('cgbchina.com.cn'),
        'PingAn.list': bank_file('pingan.com.cn'),
        'category-bank-cn': '\n'.join([
            'include:icbc @-!cn',
            '# comment',
            '',
            'spdb.com.cn',
            'cib.com.cn',
            'cmbc.com.cn',
            'hxb.com.cn',
            'full:exact.example.com',
            'keyword:bank',
        ]) + '\n',
    }
    for name, content in files.items():
        (root / name).write_text(content, encoding='utf-8')
    return root


def flatten(groups):
    return {name: items for name, items in groups}


class UpdateTests(unittest.TestCase):
    def test_to_ascii_lowercases_and_punycode(self):
        self.assertEqual(bank.to_ascii('集团.中信'), 'xn--3bst00m.xn--fiq64b')
        self.assertEqual(bank.to_ascii('ICBC.COM.CN'), 'icbc.com.cn')
        self.assertEqual(bank.to_ascii(''), '')

    def test_is_domain_rejects_bare_words(self):
        self.assertTrue(bank.is_domain('icbc.com.cn'))
        self.assertTrue(bank.is_domain('xn--3bst00m.xn--fiq64b'))
        for bad in ('icbc', 'citic', '', 'a.', '.com', 'a b.com', 'a_b.com'):
            with self.subTest(bad=bad):
                self.assertFalse(bank.is_domain(bad))

    def test_parse_lm_firefly(self):
        text = '## > ICBC\nDOMAIN-SUFFIX,icbc.com.cn\nDOMAIN-SUFFIX,95588.com\n'
        self.assertEqual(bank.parse_lm_firefly(text, 'ICBC.list'), ['icbc.com.cn', '95588.com'])

    def test_parse_lm_firefly_rejects_empty(self):
        with self.assertRaises(bank.UpdateError):
            bank.parse_lm_firefly('## > empty\n', 'EMPTY.list')

    def test_parse_v2fly_skips_includes_comments_keywords(self):
        text = 'include:icbc @-!cn\n# note\n\nspdb.com.cn\nfull:exact.example.com\ndomain:other.example.com\nkeyword:bank\n'
        self.assertEqual(bank.parse_v2fly(text), ['spdb.com.cn', 'exact.example.com', 'other.example.com'])

    def test_parse_v2fly_rejects_empty(self):
        with self.assertRaises(bank.UpdateError):
            bank.parse_v2fly('include:icbc\n# only\n')

    def test_render_exact_bytes(self):
        result = bank.render([('工商银行', ['b.example.com', 'a.example.com']), ('平安', ['pingan.com.cn'])])
        expected = '\n'.join(bank.HEADER + ['', '# 工商银行', 'DOMAIN-SUFFIX,a.example.com',
                                           'DOMAIN-SUFFIX,b.example.com', '', '# 平安',
                                           'DOMAIN-SUFFIX,pingan.com.cn', ''])
        self.assertEqual(result, expected.encode('utf-8'))

    def test_collect_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            groups, _ = bank.collect(fixture_dir(directory))
            flat = flatten(groups)
            self.assertEqual([name for name, _ in groups][:2], ['工商银行', '建设银行'])
            self.assertIn('icbc.com.cn', flat['工商银行'])
            self.assertIn('shared.example.com', flat['工商银行'])
            self.assertNotIn('shared.example.com', flat['建设银行'])
            self.assertNotIn('icbc', flat['工商银行'])
            self.assertIn('xn--3bst00m.xn--fiq64b', flat['中信银行'])
            self.assertIn('spdb.com.cn', flat['其他银行（v2fly）'])
            self.assertIn('exact.example.com', flat['其他银行（v2fly）'])
            self.assertNotIn('bank', flat['其他银行（v2fly）'])
            self.assertIn('czbank.com', flat['浙商银行'])
            self.assertIn('unionpay.com', flat['银联 / 支付'])
            total = sum(len(items) for items in flat.values())
            self.assertGreaterEqual(total, bank.MIN_TOTAL)

    def test_collect_rejects_missing_required_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture_dir(directory)
            (root / 'category-bank-cn').write_text('spdb.com.cn\ncib.com.cn\ncmbc.com.cn\n', encoding='utf-8')
            with self.assertRaises(bank.UpdateError):
                bank.collect(root)

    def test_collect_rejects_empty_bank_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture_dir(directory)
            (root / 'PSBC.list').write_text('## > empty\n', encoding='utf-8')
            with self.assertRaises(bank.UpdateError):
                bank.collect(root)

    def test_update_no_rewrite_when_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture_dir(directory)
            target = Path(directory) / 'bank_direct_all.list'
            groups, _ = bank.collect(root)
            target.write_bytes(bank.render(groups))
            before = target.stat().st_mtime_ns
            self.assertFalse(bank.update(root, target))
            self.assertEqual(target.stat().st_mtime_ns, before)

    def test_update_writes_on_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture_dir(directory)
            target = Path(directory) / 'bank_direct_all.list'
            target.write_bytes(b'Previous version\n')
            self.assertTrue(bank.update(root, target))
            groups, _ = bank.collect(root)
            self.assertEqual(target.read_bytes(), bank.render(groups))


if __name__ == '__main__':
    unittest.main()
