import json, os, tempfile, unittest
from pathlib import Path
from src import hermes_homes as hh


def can_symlink():
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(d, Path(d) / 'link', target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            return False


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name)
        (self.task / 'plugin').mkdir()
        (self.task / hh.ROOT_HOME / 'memories').mkdir(parents=True)
        (self.task / hh.ROOT_HOME / 'skills').mkdir()

    def home(self, name, learn=False):
        return hh.create_home(self.task, name, learn=learn, link_plugin=False)

    def test_new_home_has_its_own_stores_and_config(self):
        h = self.home('v08-0', learn=True)
        self.assertEqual(h, self.task / hh.PROFILES / 'v08-0')
        cfg = json.loads((h / 'config.yaml').read_text(encoding='utf-8'))
        self.assertEqual(cfg['memory'], {'nudge_interval': 1})
        self.assertEqual(cfg['skills'], {'creation_nudge_interval': 1})
        self.assertEqual(cfg['plugins']['enabled'], ['soulo-research'])
        self.assertNotIn('memory', json.loads((self.home('v08-1') / 'config.yaml').read_text(encoding='utf-8')))
        self.assertEqual(hh.learned_files(h), {})
        with self.assertRaises(ValueError):
            self.home('v08-0')  # never reused
        for bad in ('', '../x', 'A', '.hidden', 'a/b'):
            with self.assertRaises(ValueError):
                hh.home_path(self.task, bad)

    def test_home_path_must_sit_in_profiles_with_a_config(self):
        h = self.home('v08-2')
        self.assertEqual(hh.check_home_path(self.task, h), h.resolve())
        for bad in (self.task / hh.ROOT_HOME, self.task / 'elsewhere'):
            bad.mkdir(parents=True, exist_ok=True)
            (bad / 'config.yaml').write_text('{}')
            with self.assertRaises(ValueError):
                hh.check_home_path(self.task, bad)
        (h / 'config.yaml').unlink()
        with self.assertRaises(ValueError):
            hh.check_home_path(self.task, h)

    def test_manifest_ignores_telemetry_and_snapshot_round_trips(self):
        h = self.home('v08-0')
        (h / 'memories' / 'MEMORY.md').write_text('a\n§\nb', encoding='utf-8')
        (h / 'skills' / 'seo').mkdir()
        (h / 'skills' / 'seo' / 'SKILL.md').write_text('---\nname: seo\n---\n1. step', encoding='utf-8')
        (h / 'skills' / '.usage.json').write_text('{}')
        (h / 'skills' / '.usage.json.lock').write_text('')
        (h / 'skills' / '.locks').mkdir()
        (h / 'skills' / '.locks' / '3f2a.lock').write_text('')
        (h / 'memories' / 'MEMORY.md.lock').write_text('')
        (h / 'skills' / 'seo' / 'references').mkdir()
        (h / 'skills' / 'seo' / 'references' / 'notes.lock').write_text('learned text in an odd file name')
        m = hh.learned_files(h)
        # Only Hermes' own telemetry paths are left out; a learned file named *.lock is still learned content.
        self.assertEqual(sorted(m), ['memories/MEMORY.md', 'skills/seo/SKILL.md', 'skills/seo/references/notes.lock'])
        snap = self.task / 'snap'
        self.assertEqual(hh.snapshot(h, snap), m)
        with self.assertRaises(ValueError):
            hh.snapshot(h, snap)
        (h / 'memories' / 'MEMORY.md').write_text('changed', encoding='utf-8')
        (h / 'skills' / 'new').mkdir()
        (h / 'skills' / 'new' / 'SKILL.md').write_text('x')
        self.assertNotEqual(hh.learned_files(h), m)
        self.assertEqual(hh.restore(snap, h, self.task), m)
        self.assertEqual(hh.learned_files(h), m)
        with self.assertRaises(ValueError):
            hh.restore(snap, self.task / 'elsewhere', self.task)

    @unittest.skipUnless(can_symlink(), 'symlinks need privileges on this system')
    def test_linked_stores_are_refused(self):
        a, b = self.home('v08-1'), self.home('v08-2')
        (b / 'memories').rmdir()
        os.symlink(a / 'memories', b / 'memories', target_is_directory=True)
        with self.assertRaises(ValueError):
            hh.learned_files(b)

    def test_isolation_check_allows_only_the_own_learning_home_to_change(self):
        a, b = self.home('v08-0'), self.home('v08-1')
        user = self.task / 'user'
        user.mkdir()
        before = hh.isolation_state(self.task, user)
        (a / 'memories' / 'MEMORY.md').write_text('learned')
        after = hh.isolation_state(self.task, user)
        self.assertEqual(hh.isolation_check(before, after, 'v08-0'), [])
        self.assertEqual(len(hh.isolation_check(before, after, 'v08-1', hh.EMPTY)), 1)  # another home changed
        frozen = hh.isolation_check(before, after, 'v08-0', before['homes']['v08-0'])
        self.assertIn('frozen', frozen[0])
        (b / 'skills' / 'x.md').write_text('leak')
        (self.task / hh.ROOT_HOME / 'memories' / 'MEMORY.md').write_text('root')
        (user / '.hermes' / 'memories').mkdir(parents=True)
        (user / '.hermes' / 'memories' / 'MEMORY.md').write_text('shared')
        problems = hh.isolation_check(before, hh.isolation_state(self.task, user), 'v08-0')
        self.assertEqual(len(problems), 3, problems)

    def test_learned_items_split_memory_entries_and_skill_text(self):
        h = self.home('v08-0')
        (h / 'memories' / 'MEMORY.md').write_text('fact one\n§\nfact two\n§\n', encoding='utf-8')
        (h / 'memories' / 'USER.md').write_text('prefers short reports', encoding='utf-8')
        (h / 'skills' / 'seo').mkdir()
        (h / 'skills' / 'seo' / 'references').mkdir()
        (h / 'skills' / 'seo' / 'SKILL.md').write_text(
            '---\nname: seo-research\ndescription: Research a competitor.\n---\n# Steps\n\n1. Read robots.txt.\n'
            '2. Read the homepage\n   and its links.\n\nA paragraph\nover two lines.\n\n```\ncode\n```\n', encoding='utf-8')
        (h / 'skills' / 'seo' / 'references' / 'pitfalls.md').write_text('- Avoid site: queries.', encoding='utf-8')
        (h / 'skills' / '.curator_ledger.jsonl').write_text('{}')
        self.assertEqual([i['text'] for i in hh.memory_items(h)], ['fact one', 'fact two', 'prefers short reports'])
        items = hh.skill_items(h)
        main = [i for i in items if i['source'] == 'skills/seo/SKILL.md']
        # The front matter is one item without the name; the rest splits into list items, paragraphs and code.
        self.assertEqual([i['text'] for i in main], [
            'description: Research a competitor.', '1. Read robots.txt.',
            '2. Read the homepage\nand its links.', 'A paragraph\nover two lines.', '```\ncode\n```'])
        self.assertEqual([i['section'] for i in main[:2]], ['front matter', 'Steps'])
        self.assertEqual([i['text'] for i in items if 'references' in i['source']], ['- Avoid site: queries.'])
        self.assertEqual(len(items), 6)  # the hidden curator ledger is not an item


if __name__ == '__main__':
    unittest.main()
