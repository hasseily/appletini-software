"""Tests of tools/fetch_upstream.py. They use local fixtures only: a git
repository and a file made in build/, never the network."""

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
import fetch_upstream


def git(directory, *arguments):
    """Run git in `directory` with a fixed identity and no signing."""
    return subprocess.run(
        ['git', '-C', str(directory), '-c', 'user.name=Test',
         '-c', 'user.email=test@example.invalid',
         '-c', 'commit.gpgsign=false'] + list(arguments),
        check=True, stdout=subprocess.PIPE,
        universal_newlines=True).stdout.strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(
            prefix='test-fetch-', dir=str(support.BUILD)))
        self.addCleanup(shutil.rmtree, str(self.directory))


@unittest.skipUnless(shutil.which('git'), 'git is not installed')
class FetchClone(Fixture):
    def setUp(self):
        super().setUp()
        self.source = self.directory / 'source'
        self.source.mkdir()
        git(self.source, 'init', '--quiet')
        (self.source / 'file.s').write_text('first\n')
        git(self.source, 'add', 'file.s')
        git(self.source, 'commit', '--quiet', '-m', 'first')
        self.first = git(self.source, 'rev-parse', 'HEAD')
        (self.source / 'file.s').write_text('second\n')
        git(self.source, 'commit', '--quiet', '-am', 'second')
        (self.source / 'untracked.bin').write_text('generated\n')
        self.target = self.directory / 'build' / 'upstream'

    def fetch(self):
        return fetch_upstream.fetch_clone(
            self.target, str(self.source), self.first, origin='https://x/y')

    def test_checks_out_the_pinned_commit(self):
        self.assertTrue(self.fetch())
        self.assertEqual((self.target / 'file.s').read_text(), 'first\n')
        self.assertEqual(git(self.target, 'rev-parse', 'HEAD'), self.first)

    def test_takes_tracked_files_only(self):
        self.fetch()
        self.assertFalse((self.target / 'untracked.bin').exists())

    def test_origin_is_upstream_not_the_local_path(self):
        self.fetch()
        self.assertEqual(git(self.target, 'remote', 'get-url', 'origin'),
                         'https://x/y')

    def test_second_run_does_nothing(self):
        self.fetch()
        self.assertFalse(self.fetch())

    def test_modified_clone_is_refused(self):
        self.fetch()
        (self.target / 'file.s').write_text('edited\n')
        with self.assertRaises(fetch_upstream.FetchError):
            self.fetch()

    def test_clone_at_another_commit_is_refused(self):
        self.fetch()
        with self.assertRaises(fetch_upstream.FetchError):
            fetch_upstream.fetch_clone(
                self.target, str(self.source),
                git(self.source, 'rev-parse', 'HEAD'))

    def test_directory_that_is_not_a_clone_is_refused(self):
        self.target.mkdir(parents=True)
        with self.assertRaises(fetch_upstream.FetchError):
            self.fetch()

    def test_commit_that_does_not_exist(self):
        with self.assertRaises(fetch_upstream.FetchError):
            fetch_upstream.fetch_clone(
                self.target, str(self.source), '0' * 40)


class FetchRelease(Fixture):
    def setUp(self):
        super().setUp()
        self.source = self.directory / 'image.hdv'
        self.source.write_bytes(b'disk image' * 1000)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.target = self.directory / 'release' / 'doom-hd.hdv'

    def test_copies_and_verifies(self):
        self.assertTrue(fetch_upstream.fetch_release(
            self.target, str(self.source), self.digest))
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_second_run_does_nothing(self):
        fetch_upstream.fetch_release(
            self.target, str(self.source), self.digest)
        self.source.unlink()            # a second run must not need it
        self.assertFalse(fetch_upstream.fetch_release(
            self.target, str(self.source), self.digest))

    def test_wrong_digest_leaves_nothing_behind(self):
        with self.assertRaises(fetch_upstream.FetchError):
            fetch_upstream.fetch_release(
                self.target, str(self.source), '0' * 64)
        self.assertEqual(list(self.target.parent.iterdir()), [])

    def test_damaged_target_is_replaced(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'damaged')
        self.assertTrue(fetch_upstream.fetch_release(
            self.target, str(self.source), self.digest))
        self.assertEqual(fetch_upstream.sha256(self.target), self.digest)


class Pins(unittest.TestCase):
    def test_pinned_values(self):
        self.assertTrue(fetch_upstream.UPSTREAM_COMMIT.startswith('8ea2eac'))
        self.assertEqual(len(fetch_upstream.UPSTREAM_COMMIT), 40)
        self.assertEqual(
            fetch_upstream.RELEASE_SHA256,
            '2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d')

    @support.needs_upstream
    def test_fetched_clone_is_at_the_pinned_commit(self):
        self.assertEqual(fetch_upstream.clone_state(support.UPSTREAM),
                         fetch_upstream.UPSTREAM_COMMIT)

    @support.needs_release
    def test_fetched_image_has_the_pinned_digest(self):
        self.assertEqual(fetch_upstream.sha256(support.RELEASE_IMAGE),
                         fetch_upstream.RELEASE_SHA256)


if __name__ == '__main__':
    unittest.main()
