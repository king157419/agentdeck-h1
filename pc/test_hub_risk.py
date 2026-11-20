"""Pure apply_patch risk checks; no user configuration or device access."""
import unittest

from hub_risk import classify


class PatchRiskTests(unittest.TestCase):
    def test_delete_file_is_high_for_all_patch_input_shapes(self):
        patch = "*** Begin Patch\n*** Delete File: pc/obsolete.py\n*** End Patch\n"
        for tool_input in (patch, {"command": patch}, {"patch": patch}, {"input": patch}):
            with self.subTest(tool_input=tool_input):
                self.assertEqual(classify("apply_patch", tool_input), "high")

    def test_add_and_update_patches_stay_low_for_all_input_shapes(self):
        for operation in ("Add", "Update"):
            patch = "*** Begin Patch\n*** %s File: pc/example.py\n+pass\n*** End Patch\n" % operation
            for tool_input in (patch, {"command": patch}, {"patch": patch}, {"input": patch}):
                with self.subTest(operation=operation, tool_input=tool_input):
                    self.assertEqual(classify("apply_patch", tool_input), "low")

    def test_delete_inside_nested_json_input_is_high(self):
        patch = "*** Begin Patch\n*** Delete File: pc/obsolete.py\n*** End Patch\n"
        for tool_input in ({"input": {"patch": patch}}, {"args": [patch]}):
            with self.subTest(tool_input=tool_input):
                self.assertEqual(classify("apply_patch", tool_input), "high")
        self.assertEqual(classify("apply_patch", {"input": {"patch": patch.replace("Delete", "Update")}}), "low")

    def test_delete_marker_must_start_its_line(self):
        self.assertEqual(classify("apply_patch", "*** Delete File: pc/example.py"), "high")
        self.assertEqual(classify("apply_patch", "*** Begin Patch\r\n*** Delete File: pc/example.py"), "high")
        self.assertEqual(classify("apply_patch", "text *** Delete File: pc/example.py"), "low")
        self.assertEqual(classify("apply_patch", "+*** Delete File: pc/example.py"), "low")


if __name__ == "__main__":
    unittest.main(verbosity=2)
