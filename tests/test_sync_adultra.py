import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sync_adultra.py'
spec = importlib.util.spec_from_file_location('sync_adultra', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fixture(newline='\n'):
    lines = [
        '#!name=APP启动页去广告ultra', '#!desc=保留上游说明', '# 保留原作者与中文说明',
        '[Rule]', 'DOMAIN,ads.example.com,REJECT',
        '[URL Rewrite]', '^https://ads.example.com - reject',
        '[Body Rewrite]', 'http-response ^https://example.com response-body foo response-body bar',
        '[Map Local]', '^https://example.com/ad data-type=text data=" " status-code=200',
        '[Script]',
        'qidian = type=http-response, pattern=^https://apps.teamair.cn/app/version, script-path=https://raw.githubusercontent.com/ddgksf2013/Scripts/refs/heads/master/qidian.js, requires-body=true',
        'qidian = type=http-response, pattern=^https://magev6.if.qidian.com/, script-path=' + sync.ORIGINAL_JS_URL + ', requires-body=true, max-size=-1, timeout=60',
        'other = type=http-response, pattern=^https://other.example.com, script-path=https://example.com/other.js',
        '[MITM]', 'hostname = %APPEND% magev6.if.qidian.com, other.example.com', ''
    ]
    return newline.join(lines).encode()


class SyncTests(unittest.TestCase):
    def test_changes_exactly_one_url(self):
        original = fixture()
        self.assertEqual(sync.render_module(original), original.replace(sync.ORIGINAL_JS_URL.encode(), sync.REPLACEMENT_JS_URL.encode(), 1))

    def test_other_qidian_and_all_surrounding_content_preserved(self):
        original = fixture()
        result = sync.render_module(original)
        self.assertIn(b'ddgksf2013/Scripts/refs/heads/master/qidian.js', result)
        self.assertEqual(result.replace(sync.REPLACEMENT_JS_URL.encode(), sync.ORIGINAL_JS_URL.encode(), 1), original)

    def test_published_module_stays_on_current_dependency(self):
        published = sync.TARGET.read_bytes()
        replacement = sync.REPLACEMENT_JS_URL.encode()
        original = sync.ORIGINAL_JS_URL.encode()
        self.assertEqual(published.count(replacement), 1)
        self.assertNotIn(original, published)
        restored = published.replace(replacement, original, 1)
        self.assertEqual(sync.render_module(restored), published)

    def test_crlf_preserved(self):
        original = fixture('\r\n')
        result = sync.render_module(original)
        self.assertEqual(result.count(b'\r\n'), original.count(b'\r\n'))
        self.assertEqual(result.replace(sync.REPLACEMENT_JS_URL.encode(), sync.ORIGINAL_JS_URL.encode(), 1), original)

    def test_all_required_sections_preserved(self):
        result = sync.render_module(fixture())
        for section in sync.REQUIRED_SECTIONS:
            self.assertIn(('[' + section + ']').encode(), result)

    def test_rejects_missing_sections(self):
        for section in sync.REQUIRED_SECTIONS:
            with self.subTest(section=section), self.assertRaises(sync.SyncError):
                sync.render_module(fixture().replace(('[' + section + ']').encode(), b'[Changed]'))

    def test_rejects_duplicate_sections(self):
        with self.assertRaises(sync.SyncError):
            sync.render_module(fixture() + b'\n[Script]\n')

    def test_rejects_missing_url(self):
        with self.assertRaises(sync.SyncError):
            sync.render_module(fixture().replace(sync.ORIGINAL_JS_URL.encode(), b'https://example.com/new.js'))

    def test_rejects_duplicate_url(self):
        with self.assertRaises(sync.SyncError):
            sync.render_module(fixture() + sync.ORIGINAL_JS_URL.encode())

    def test_rejects_already_patched_upstream(self):
        with self.assertRaises(sync.SyncError):
            sync.render_module(fixture() + b'\n# ' + sync.REPLACEMENT_JS_URL.encode())

    def test_rejects_url_only_in_comment(self):
        with self.assertRaises(sync.SyncError):
            sync.render_module(fixture().replace(b'qidian = type=http-response, pattern=^https://mage', b'# qidian = type=http-response, pattern=^https://mage'))

    def test_rejects_target_outside_script_section(self):
        source = fixture().replace(b'[Script]', b'[Extra]').replace(b'[MITM]', b'[Script]\n[MITM]')
        with self.assertRaises(sync.SyncError):
            sync.render_module(source)

    def test_rejects_changed_script_type(self):
        source = fixture().replace(b'qidian = type=http-response, pattern=^https://mage', b'qidian = type=http-request, pattern=^https://mage')
        with self.assertRaises(sync.SyncError):
            sync.render_module(source)

    def test_rejects_html(self):
        for content in (b'<!doctype html><html>Cloudflare challenge</html>', b' \n<HTML>403 Forbidden</HTML>'):
            with self.subTest(content=content), self.assertRaises(sync.SyncError):
                sync.render_module(content)

    def test_rejects_invalid_bytes_and_empty_source(self):
        for content in (b'', b'\xff\xfe', fixture() + b'\x00'):
            with self.subTest(content=content[:10]), self.assertRaises(sync.SyncError):
                sync.render_module(content)

    def test_rejects_oversize(self):
        with mock.patch.object(sync, 'MAX_BYTES', 10), self.assertRaises(sync.SyncError):
            sync.render_module(fixture())

    def test_unchanged_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'module.sgmodule'
            self.assertTrue(sync.sync_bytes(fixture(), target))
            before = target.stat().st_mtime_ns
            self.assertFalse(sync.sync_bytes(fixture(), target))
            self.assertEqual(target.stat().st_mtime_ns, before)

    def test_invalid_source_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'module.sgmodule'
            target.write_bytes(b'Existing known-good module')
            with self.assertRaises(sync.SyncError):
                sync.sync_bytes(b'<html>403</html>', target)
            self.assertEqual(target.read_bytes(), b'Existing known-good module')
            self.assertEqual([x.name for x in Path(directory).iterdir()], ['module.sgmodule'])

    def test_changed_source_writes_complete_validated_result(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'module.sgmodule'
            target.write_bytes(b'Previous version')
            source = fixture().replace(b'ads.example.com', b'new-ad.example.com')
            self.assertTrue(sync.sync_bytes(source, target))
            self.assertEqual(target.read_bytes(), sync.with_script_metadata(sync.render_module(source)))


class MetadataTests(unittest.TestCase):
    def test_module_displays_script_version_and_update_time(self):
        rendered = sync.render_module(fixture())
        version, updated = sync.script_metadata()
        stamped = sync.with_script_metadata(rendered)
        suffix = f' | 起点JS v{version}，更新于 {updated}'.encode()
        self.assertEqual(stamped, rendered.replace('#!desc=保留上游说明'.encode(), '#!desc=保留上游说明'.encode() + suffix, 1))

    def test_metadata_reapplication_is_idempotent(self):
        stamped = sync.with_script_metadata(sync.render_module(fixture()))
        self.assertEqual(sync.with_script_metadata(stamped), stamped)

    def test_metadata_preserves_crlf(self):
        rendered = sync.render_module(fixture('\r\n'))
        stamped = sync.with_script_metadata(rendered)
        self.assertEqual(stamped.count(b'\r\n'), rendered.count(b'\r\n'))

    def test_header_validation(self):
        valid = ' * @version 2026.11.28.2\n * @updated 2026-11-28 10:53:16 +08:00\n'
        self.assertEqual(sync.script_metadata(valid), ('2026.11.28.2', '2026-11-28 10:53:16 +08:00'))
        for source in ('', valid + valid, valid.replace('2026.11.28.2', 'unknown'), valid.replace('11-28', '99-99'), valid.replace('+08:00', '+00:00')):
            with self.subTest(source=source), self.assertRaises(sync.SyncError):
                sync.script_metadata(source)

    def test_missing_or_duplicate_description_rejected(self):
        rendered = sync.render_module(fixture())
        for source in (rendered.replace(b'#!desc=', b'# desc='), rendered + b'\n#!desc=duplicate'):
            with self.subTest(source=source[:30]), self.assertRaises(sync.SyncError):
                sync.with_script_metadata(source)

    def test_cache_version_mismatch_rejected(self):
        with mock.patch.object(sync, 'REPLACEMENT_JS_URL', 'https://example.com/qidian.js?v=wrong'), self.assertRaises(sync.SyncError):
            sync.with_script_metadata(sync.render_module(fixture()))

    def test_published_description_matches_script(self):
        published = sync.TARGET.read_bytes()
        self.assertEqual(sync.with_script_metadata(published), published)
        version, updated = sync.script_metadata()
        self.assertIn(f'起点JS v{version}，更新于 {updated}'.encode(), published)

    def test_metadata_only_change_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'module.sgmodule'
            self.assertTrue(sync.sync_bytes(fixture(), target))
            source = fixture()
            new_version, new_time = '2099.01.01.1', '2099-01-01 08:00:00 +08:00'
            with mock.patch.object(sync, 'script_metadata', return_value=(new_version, new_time)), mock.patch.object(sync, 'REPLACEMENT_JS_URL', 'https://example.com/qidian.js?v=' + new_version):
                self.assertTrue(sync.sync_bytes(source, target))
                self.assertIn(new_time.encode(), target.read_bytes())
                self.assertFalse(sync.sync_bytes(source, target))


if __name__ == '__main__':
    unittest.main()
