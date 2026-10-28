from whycode.code.diff import LineChange, changed_lines, entities_changed
from whycode.code.entities import parse_file

SRC = '''"""Compatibility shims."""
DEFAULT_ENCODING = "utf-8"
MAX_BYTES = 4096


class Detector:
    LIMIT = 10

    def detect(self, data, limit=MAX_BYTES):
        return DEFAULT_ENCODING


def detect(data):
    return Detector().detect(data)
'''


def parsed():
    return parse_file("psf/requests", "src/requests/compat.py", SRC)


def names(changes):
    return {c.entity.qualified_name: (c.added, c.removed) for c in changes}


def test_added_lines_get_new_side_numbers():
    patch = "@@ -1,3 +1,4 @@\n line1\n+added2\n line3\n+added4\n"
    assert changed_lines(patch) == [LineChange(2, True), LineChange(4, True)]


def test_removed_line_is_marked_on_the_line_before_it():
    patch = "@@ -10,3 +10,2 @@\n keep10\n-gone\n keep11\n"
    assert changed_lines(patch) == [LineChange(10, False)]


def test_removal_at_the_top_of_a_hunk_marks_the_hunk_start():
    assert changed_lines("@@ -5,2 +5,1 @@\n-gone\n keep5\n") == [LineChange(5, False)]


def test_several_hunks_restart_numbering_and_no_newline_marker_is_ignored():
    patch = "@@ -1,1 +1,1 @@\n-a\n+b\n@@ -20,1 +20,2 @@\n c20\n+d21\n\\ No newline at end of file\n"
    assert changed_lines(patch) == [
        LineChange(1, False),
        LineChange(1, True),
        LineChange(21, True),
    ]


def test_no_patch_means_no_changes():
    assert changed_lines(None) == [] and changed_lines("") == []


def test_change_in_a_method_counts_for_the_method_not_its_class():
    # line 10 is the method body
    patch = (
        "@@ -9,2 +9,2 @@\n     def detect(self, data, limit=MAX_BYTES):\n"
        "-        return 'x'\n+        return DEFAULT_ENCODING\n"
    )
    assert names(entities_changed(parsed(), patch)) == {"Detector.detect": (1, 1)}


def test_change_in_a_class_body_outside_methods_counts_for_the_innermost_entity():
    # line 7 is `LIMIT = 10`: inside the class, outside any method. LIMIT is not a module
    # constant (class bodies are not scanned for config keys), so the class gets it.
    patch = "@@ -6,2 +6,2 @@\n class Detector:\n-    LIMIT = 5\n+    LIMIT = 10\n"
    assert names(entities_changed(parsed(), patch)) == {"Detector": (1, 1)}


def test_module_constant_and_function_in_one_patch():
    patch = (
        '@@ -2,2 +2,2 @@\n DEFAULT_ENCODING = "utf-8"\n-MAX_BYTES = 1024\n+MAX_BYTES = 4096\n'
        "@@ -14,1 +14,1 @@\n-    return detect_old(data)\n+    return Detector().detect(data)\n"
    )
    assert names(entities_changed(parsed(), patch)) == {"MAX_BYTES": (1, 1), "detect": (1, 1)}


def test_change_outside_any_entity_is_ignored():
    patch = "@@ -1,1 +1,1 @@\n-'''Old docstring.'''\n+\"\"\"Compatibility shims.\"\"\"\n"
    assert entities_changed(parsed(), patch) == []


def test_replacement_is_marked_on_the_replacing_line():
    patch = "@@ -3,3 +3,3 @@\n ctx3\n-old4\n-old4b\n+new4\n ctx5\n"
    assert changed_lines(patch) == [
        LineChange(4, False),
        LineChange(4, False),
        LineChange(4, True),
    ]


def test_pure_deletion_at_the_end_of_a_hunk_marks_the_line_before():
    assert changed_lines("@@ -4,3 +4,2 @@\n a4\n b5\n-gone\n") == [LineChange(5, False)]
