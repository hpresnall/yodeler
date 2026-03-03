# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest

import util.parse as parse


class TestParse(unittest.TestCase):
    def test_non_empty_dict_none_location(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict(None, {"test": True})  # type: ignore

    def test_non_empty_dict_empty_location(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("", {"test": True})

    def test_non_empty_dict_none_value(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", None)

    def test_non_empty_dict_list(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", ["test"])  # type: ignore

    def test_non_empty_dict_empty(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", {})

    def test_non_empty_list_none_location(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list(None, ["test"])  # type: ignore

    def test_non_empty_list_empty_location(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("", ["test"])

    def test_non_empty_list_none_value(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", None)

    def test_non_empty_list_dict(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", {"test": True})  # type: ignore

    def test_non_empty_list_empty(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", [])

    def test_get_string_none_location(self):
        with self.assertRaises(ValueError):
            parse.get_string(None, "test", {"test": "value"})  # type: ignore

    def test_get_string_empty_location(self):
        with self.assertRaises(ValueError):
            parse.get_string("", "test", {"test": "value"})

    def test_get_string_none_key(self):
        with self.assertRaises(KeyError):
            parse.get_string("test", None, {"test": "value"})  # type: ignore

    def test_get_string_empty_key(self):
        with self.assertRaises(KeyError):
            parse.get_string("test", "", {"test": "value"})

    def test_get_string_none_dict(self):
        with self.assertRaises(ValueError):
            parse.get_string("test", "test", None)

    def test_get_string_empty_dict(self):
        with self.assertRaises(ValueError):
            parse.get_string("test", "test", {})

    def test_get_string_missing_key(self):
        with self.assertRaises(KeyError):
            parse.get_string("test", "missing", {"test": "value"})

    def test_get_string_non_str_value(self):
        with self.assertRaises(ValueError):
            parse.get_string("test", "test", {"test": True})

    def test_get_string_empty_value(self):
        with self.assertRaises(ValueError):
            parse.get_string("test", "test", {"test": ""})

    def test_get_string_valid(self):
        self.assertEqual("value", parse.get_string("test", "test", {"test": "value"}))

    def test_set_string_default_none_location(self):
        with self.assertRaises(ValueError):
            parse.set_string_default(None, "test", {"test": "value"}, "default")  # type: ignore

    def test_set_string_default_empty_location(self):
        with self.assertRaises(ValueError):
            parse.set_string_default("", "test", {"test": "value"}, "default")

    def test_set_string_default_none_key(self):
        with self.assertRaises(KeyError):
            parse.set_string_default("test", None, {"test": "value"}, "default")  # type: ignore

    def test_set_string_default_empty_key(self):
        with self.assertRaises(KeyError):
            parse.set_string_default("test", "", {"test": "value"}, "default")

    def test_set_string_default_none_dict(self):
        with self.assertRaises(ValueError):
            parse.set_string_default("test", "test", None, "default")

    def test_set_string_default_empty_dict(self):
        cfg = {}
        value = parse.set_string_default("test", "test", cfg, "default")
        self.assertEqual("default", value)
        self.assertEqual("default", cfg["test"])

    def test_set_string_default_missing_key(self):
        cfg = {"test": "value"}
        value = parse.set_string_default("test", "missing", cfg, "default")
        self.assertEqual("default", value)
        self.assertEqual("default", cfg["missing"])

    def test_set_string_default_empty_default(self):
        with self.assertRaises(ValueError):
            parse.set_string_default("test", "test", {"test": "value"}, "")

    def test_set_string_default_none_default(self):
        with self.assertRaises(ValueError):
            parse.set_string_default("test", "test", {"test": "value"}, None)  # type: ignore

    def test_set_string_default_empty_value(self):
        cfg = {"test": ""}
        value = parse.set_string_default("test", "test", cfg, "default")
        self.assertEqual("default", value)
        self.assertEqual("default", cfg["test"])

    def test_set_string_default_none_value(self):
        cfg = {"test": None}
        value = parse.set_string_default("test", "test", cfg, "default")
        self.assertEqual("default", value)
        self.assertEqual("default", cfg["test"])

    def test_set_string_default_int_value(self):
        with self.assertRaises(ValueError):
            value = parse.set_string_default("test", "test", {"test": 1}, "default")

    def test_list_none_location(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals(None, {"key"}, {"key": ["test1, test2"]})  # type: ignore

    def test_list_empty_location(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("", {"key"}, {"key": ["test1, test2"]})

    def test_list_none_keys(self):
        with self.assertRaises(KeyError):
            parse.get_string_list_plurals("test", None, {"key": ["test1, test2"]})  # type: ignore

    def test_list_empty_keys(self):
        with self.assertRaises(KeyError):
            parse.get_string_list_plurals("test", set(), {"key": ["test1, test2"]})

    def test_list_none_key_value(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("test", {None}, {"key": ["test1, test2"]})  # type: ignore

    def test_list_empty_key_value(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("test", {""}, {"key": ["test1, test2"]})

    def test_list_empty_dict(self):
        # optional values are allow, so an empty list can be returned
        values = parse.get_string_list_plurals("test", {"key"}, {})
        self.assertEqual(0, len(values))

    def test_list_none_dict(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("test", {"key"}, None)

    def test_list_none_value(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("test", {"key"}, {"key": None})

    def test_list_value_empty_list(self):
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("", {"key"}, {"key": []})

    def test_list_value_empty_str(self):
        # empty string value ok, but do not return it
        values = parse.get_string_list_plurals("test", {"key"}, {"key": ""},)
        self.assertIsNotNone(values)
        self.assertEqual(0, len(values))

    def test_list_value_list_empty_str(self):
        # empty string value ok, but do not return it
        values = parse.get_string_list_plurals("test", {"key"}, {"key": [""]},)
        self.assertIsNotNone(values)
        self.assertEqual(0, len(values))

    def test_list_value_list_none_str(self):
        # None is not a str, so raise error on invalid type
        with self.assertRaises(ValueError):
            parse.get_string_list_plurals("test", {"key"}, {"key": [None]},)

    def test_list_value_list_empty_one(self):
        values = parse.get_string_list_plurals("test", {"key"}, {"key": ["test1", ""]})
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertIn("test1", values)

    def test_list_value_str(self):
        values = parse.get_string_list_plurals("test", {"key"}, {"key": "test1"})
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertEqual("test1", values[0])

    def test_list_value_str_unique(self):
        values = parse.get_string_list_plurals("test", {"key", "keys "}, {"key": "test1", "keys": ["test1"]})
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertEqual("test1", values[0])

    def test_list_value_list(self):
        values = parse.get_string_list_plurals("test", {"key"}, {"key": ["test1", "test2"]})
        self.assertIsNotNone(values)
        self.assertEqual(2, len(values))
        self.assertIn("test1", values)
        self.assertIn("test2", values)

    def test_list_value_lists(self):
        values = parse.get_string_list_plurals(
            "test", {"key", "keys"}, {"key": ["test1", "test2", ""], "keys": ["test1", "test3"]})
        self.assertIsNotNone(values)
        self.assertEqual(3, len(values))
        self.assertIn("test1", values)
        self.assertIn("test2", values)
        self.assertIn("test3", values)

    def test_cfg_def_none_location(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults(None, {"key": "test"}, {"key": str}, {})  # type: ignore

    def test_cfg_def_empty_location(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("", {"key": "test"}, {"key": str}, {})

    def test_cfg_def_none_default(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", None, {"key": str}, {})  # type: ignore

    def test_cfg_def_empty_default(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {}, {"key": str}, {})

    def test_cfg_def_none_types(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, None, {})  # type: ignore

    def test_cfg_def_empty_types(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, {}, {})

    def test_cfg_def_mismatched_size(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, {"key": str, "mismatch": str}, {})

    def test_cfg_def_none_cfg(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, {"key": str}, None)  # type: ignore

    def test_cfg_def_no_type(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": "test"}, {"unused": str}, {})

    def test_cfg_def_invalid_type_def(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": []}, {"key": str}, {})

    def test_cfg_def_invalid_type_cfg(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": "test"}, {"key": str}, {"key": []})

    def test_cfg_def_use_default(self):
        cfg = {}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("test", cfg["key"])

    def test_cfg_def_use_cfg(self):
        cfg = {"key": "cfg_test"}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("cfg_test", cfg["key"])

    def test_cfg_def_allow_empty(self):
        cfg = {"key": ""}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("", cfg["key"])
