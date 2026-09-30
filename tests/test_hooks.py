"""Isolated regressions for hook routing and task-start scope preservation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugins/codex/hooks'
spec = importlib.util.spec_from_file_location('scope_audit', HOOKS / 'subagent-scope-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ScopeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo / 'tracked.txt').write_text('original')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline')
        self.snapshot = self.root / 'snapshot'
        self.snapshot.mkdir()
        self.manifests = self.root / 'codex-fixer-manifests'
        self.manifests.mkdir()
        self.scope = ['in-scope.txt']

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo)

    def baseline(self):
        data = audit.fingerprints(self.repo, self.scope)
        (self.snapshot / 'fingerprints-before.json').write_text(json.dumps(data))
        (self.manifests / 'fixture.json').write_text(json.dumps({
            'cwd': str(self.repo), 'snap_dir': str(self.snapshot), 'scope_files': self.scope,
        }))

    def warning(self):
        env = dict(os.environ, TMPDIR=str(self.root))
        result = subprocess.run([sys.executable, str(HOOKS / 'subagent-scope-audit.py')],
                                input=json.dumps({'cwd': str(self.repo), 'agent_type': 'codex:fixer'}),
                                env=env, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['hookSpecificOutput']['additionalContext'] if result.stdout else ''

    def test_already_dirty_file_changed_again(self):
        file = self.repo / 'tracked.txt'
        file.write_text('user WIP')
        self.baseline()
        file.write_text('delegate overwrites WIP')
        self.assertIn('tracked.txt', self.warning())

    def test_clean_file_change_is_detected_without_snapshot_copy(self):
        self.baseline()
        (self.repo / 'tracked.txt').write_text('delegate change')
        warning = self.warning()
        self.assertIn('tracked.txt', warning)
        self.assertIn('if no snapshot exists', warning)

    def test_scope_edit_is_allowed_and_consumed(self):
        self.baseline()
        (self.repo / 'in-scope.txt').write_text('allowed')
        self.assertEqual(self.warning(), '')
        self.assertTrue((self.manifests / 'fixture.json.done').exists())

    def test_raw_unicode_newline_and_arrow_paths(self):
        file = self.repo / '日本語 -> name\n.txt'
        file.write_text('user WIP')
        self.baseline()
        file.unlink()
        self.assertIn(file.name, self.warning())

    def test_mode_and_symlink_target_changes(self):
        link = self.repo / 'link'
        link.symlink_to('tracked.txt')
        self.baseline()
        (self.repo / 'tracked.txt').chmod(0o755)
        link.unlink()
        link.symlink_to('in-scope.txt')
        warning = self.warning()
        self.assertIn('tracked.txt', warning)
        self.assertIn('link', warning)

    def test_missing_baseline_reports_unavailable(self):
        self.baseline()
        (self.snapshot / 'fingerprints-before.json').unlink()
        self.assertIn('Scope audit unavailable', self.warning())

    def test_subdirectory_and_symlink_resolve_to_repository_root(self):
        before = audit.fingerprints(self.repo, self.scope)
        nested = self.repo / 'nested'
        nested.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(nested, target_is_directory=True)
        self.assertEqual(audit.fingerprints(alias, self.scope), before)

    def test_scope_cannot_escape_repository(self):
        with self.assertRaises(ValueError):
            audit.fingerprints(self.repo, ['../outside.txt'])

    def test_in_scope_deleted_file_resurrection_is_visible_to_lead(self):
        before = audit.fingerprints(self.repo, ['deleted.txt'])
        (self.repo / 'deleted.txt').write_text('resurrected')
        after = audit.fingerprints(self.repo, ['deleted.txt'])
        self.assertEqual(before['deleted.txt'], 'absent')
        self.assertNotEqual(before['deleted.txt'], after['deleted.txt'])


class RoutingTests(unittest.TestCase):
    def test_slash_command_skips_nudge(self):
        result = subprocess.run([sys.executable, str(HOOKS / 'routing-nudge.py')],
                                input=json.dumps({'prompt': '/codex-review'}),
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, '')

    def test_implementation_prompt_gets_routing_context(self):
        result = subprocess.run([sys.executable, str(HOOKS / 'routing-nudge.py')],
                                input=json.dumps({'prompt': 'Implement a feature'}),
                                capture_output=True, text=True, check=True)
        self.assertIn('codex:fixer', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])


if __name__ == '__main__':
    unittest.main()
