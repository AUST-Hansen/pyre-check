# Copyright 2004-present Facebook.  All rights reserved.

import glob
import json
import subprocess
import unittest
from collections import OrderedDict, namedtuple
from unittest.mock import call, mock_open, patch

from .. import buck, log


BuckOut = namedtuple("BuckOut", "source_directories targets_not_found")


class BuckTest(unittest.TestCase):
    def test_presumed_target_root(self) -> None:
        self.assertEqual(
            buck.presumed_target_root("//path/directory/..."), "path/directory"
        )
        self.assertEqual(
            buck.presumed_target_root("/path/directory:target"), "/path/directory"
        )
        self.assertEqual(
            buck.presumed_target_root("prefix//path/directory/..."), "path/directory"
        )
        self.assertEqual(
            buck.presumed_target_root("prefix//path/directory:target"), "path/directory"
        )

    @patch("{}.find_root".format(buck.__name__), return_value="/root")
    def test_find_built_source_directories(self, find_root) -> None:
        trees = [
            "blah-vs_debugger#link-tree",
            "blah-blah#link-tree",
            "blah-interp#link-tree",
            "blah-ipython#link-tree",
        ]
        with patch.object(glob, "glob", return_value=trees) as glob_glob:
            self.assertEqual(
                buck._find_built_source_directories(["target"]),
                BuckOut(["blah-blah#link-tree"], []),
            )
        with patch.object(glob, "glob") as glob_glob:
            buck._find_built_source_directories(
                [
                    "//path/targets:name",
                    "//path/targets:namelibrary",
                    "//path/...",
                    "prefix//path/targets:name",
                ]
            )
            glob_glob.assert_has_calls(
                [
                    call("/root/buck-out/gen/path/targets/name#*link-tree"),
                    call("/root/buck-out/gen/path/targets/namelibrary#*link-tree"),
                    call("/root/buck-out/gen/path/...#*link-tree"),
                    call("/root/buck-out/gen/path/targets/name#*link-tree"),
                ],
                any_order=True,
            )

        with patch.object(glob, "glob", return_value=["new_tree"]) as glob_glob:
            found_trees = buck._find_built_source_directories(
                OrderedDict(
                    [
                        ("//path/...", None),
                        ("//path/targets:another", "buck-out/path/another"),
                        ("//path/targets:name", None),
                        ("//path/targets:namelibrary", None),
                    ]
                )
            )
            self.assertEqual(
                found_trees,
                BuckOut(["new_tree", "new_tree", "new_tree", "new_tree"], []),
            )

        with patch.object(glob, "glob", return_value=[]) as glob_glob:
            found_trees = buck._find_built_source_directories(
                [
                    "//path/...",
                    "//path/targets:another",
                    "//path/targets:name",
                    "//path/targets:namelibrary",
                ]
            )
            self.assertEqual(
                found_trees,
                BuckOut(
                    [],
                    [
                        "//path/...",
                        "//path/targets:another",
                        "//path/targets:name",
                        "//path/targets:namelibrary",
                    ],
                ),
            )
            # Order doesn't matter.
            found_trees = buck._find_built_source_directories(
                [
                    "//path/targets:name",
                    "//path/targets:namelibrary",
                    "//path/targets:another",
                    "//path/...",
                ]
            )
            self.assertEqual(
                found_trees,
                BuckOut(
                    [],
                    [
                        "//path/...",
                        "//path/targets:another",
                        "//path/targets:name",
                        "//path/targets:namelibrary",
                    ],
                ),
            )

        with patch.object(glob, "glob", return_value=[]) as glob_glob:
            found_trees = buck._find_built_source_directories(
                ["//path/targets:name", "//path/..."]
            )
            self.assertEqual(
                found_trees, BuckOut([], ["//path/...", "//path/targets:name"])
            )

    @patch("%s.open" % buck.__name__, new_callable=mock_open, read_data="")
    def test_normalize(self, mock_open) -> None:
        with patch.object(subprocess, "check_output") as buck_targets:
            buck_targets.return_value = "a\nb".encode("utf-8")
            buck._normalize(["target_path"])
            buck_targets.assert_has_calls(
                [
                    call(
                        [
                            "buck",
                            "targets",
                            "--show-output",
                            "target_path",
                            "--type",
                            "python_binary",
                            "python_test",
                        ],
                        stderr=subprocess.PIPE,
                        timeout=600,
                    )
                ]
            )

    def test_build_targets(self) -> None:
        with patch.object(subprocess, "check_output") as buck_build:
            buck._build_targets(["//t:subtarget", "//t:subtarget2"], ["//t/..."])
            buck_build.assert_called_once_with(
                ["buck", "build", "//t:subtarget", "//t:subtarget2"],
                stderr=subprocess.PIPE,
            )

    def test_map_normalized_targets_to_original(self) -> None:
        self.assertEqual(
            sorted(
                buck._map_normalized_targets_to_original(
                    ["//t/target1", "//t/target2", "//s:exact_target", "//unknown"],
                    ["//t/...", "//s:exact_target"],
                )
            ),
            ["//s:exact_target", "//t/...", "//unknown"],
        )

    @patch.object(log, "get_yes_no_input", return_value=False)
    @patch.object(buck, "_normalize")
    @patch.object(buck, "_find_built_source_directories")
    def test_generate_source_directories(
        self, mock_find_built_source_directories, mock_normalize, mock_input
    ) -> None:
        mock_find_built_source_directories.return_value = BuckOut(  # noqa
            ["new_tree"], ["empty_target"]
        )

        with patch.object(buck, "_normalize") as mock_normalize:
            with self.assertRaises(buck.BuckException):
                buck.generate_source_directories(["target"], build=False, prompt=True)
                buck.generate_source_directories(
                    ["target1", "target2"], build=False, prompt=True
                )
                mock_normalize.assert_has_calls(
                    [call(["target"]), call(["target1", "target2"])], any_order=True
                )

        mock_find_built_source_directories.return_value = BuckOut(
            ["new_tree"], []
        )  # noqa
        with patch.object(buck, "_normalize") as mock_normalize:
            with patch.object(buck, "_build_targets") as mock_build:
                mock_normalize.return_value = ["normalized"]
                buck.generate_source_directories(["target"], build=True, prompt=True)
                mock_build.assert_has_calls([call(["normalized"], ["target"])])

    @patch.object(buck, "find_buck_root", return_value="/BUCK_ROOT")
    def test_resolve_relative_paths(self, find_buck_root):
        with patch.object(subprocess, "check_output") as buck_query:
            buck_query.return_value = json.dumps(
                {
                    "ownerA": {
                        "buck.base_path": "src/python",
                        "srcs": {"a.py": "a.py", "b/c.py": "otherDirectory/c.py"},
                    },
                    "ownerB": {
                        "buck.base_path": "src/python",
                        "buck.base_module": "com.companyname",
                        "srcs": {"package.py": "package.py"},
                    },
                }
            ).encode("utf-8")

            paths = [
                "/BUCK_ROOT/src/python/a.py",  # tracked paths
                "/BUCK_ROOT/src/python/b/c.py",
                "/BUCK_ROOT/src/python/package.py",
                "/BUCK_ROOT/src/java/python/a.py",  # untracked paths
                "/BUCK_ROOT/com/companyname/package.py"
                "/OTHER_PROJECT/src/python/a.py",
            ]
            self.assertDictEqual(
                buck.resolve_relative_paths(paths),
                {
                    "/BUCK_ROOT/src/python/a.py": "src/python/a.py",
                    "/BUCK_ROOT/src/python/b/c.py": "src/python/otherDirectory/c.py",
                    "/BUCK_ROOT/src/python/package.py": "com/companyname/package.py",
                },
            )
